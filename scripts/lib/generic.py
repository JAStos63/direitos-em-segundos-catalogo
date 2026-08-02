from __future__ import annotations

import gzip
import json
import io
import re
import xml.etree.ElementTree as ET
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .common import (
    Norm,
    absolutize,
    classify_type,
    clean_ws,
    deduplicate,
    extract_number_year,
    is_law_title,
    normalize,
    same_host_or_allowed,
    stable_id,
)
from .http import HttpClient

PAGE_WORDS = ("proxima", "proximo", "next", "seguinte", "mais", "pagina")
PAGE_PARAMS = {"page", "pagina", "p", "pg", "offset", "start", "inicio"}


class GenericPortalConnector:
    """Descobre normas em portais oficiais via sitemap e navegação de listagens.

    O conector é deliberadamente conservador: somente mantém páginas cujo título
    identifica Constituição, Lei, Lei Complementar, Lei Delegada ou Emenda
    Constitucional. URLs externas não entram no catálogo.
    """

    def __init__(
        self,
        client: HttpClient,
        uf: str,
        portal: str,
        allowed_hosts: list[str],
        start_urls: list[str],
        detail_patterns: list[str],
        cc_queries: list[str] | None = None,
    ):
        self.client = client
        self.uf = uf
        self.portal = portal
        self.allowed_hosts = allowed_hosts
        self.start_urls = start_urls or [portal]
        self.detail_patterns = [re.compile(p, re.I) for p in detail_patterns]
        self.cc_queries = cc_queries or []

    def collect(self, max_records: int = 20000, max_listing_pages: int = 500) -> list[Norm]:
        candidates: set[str] = set()
        candidates.update(self._discover_sitemaps(max_urls=max_records * 4))
        candidates.update(self._crawl_listings(max_pages=max_listing_pages, max_detail=max_records * 2))
        # Common Crawl is used only to discover URLs already published on the
        # official domains. Every candidate is subsequently downloaded and
        # validated from the government/legislative portal itself.
        candidates.update(self._discover_commoncrawl(max_urls=max_records * 4))
        candidates = {u for u in candidates if self._looks_like_detail_url(u)}
        if not candidates:
            raise RuntimeError("nenhum endereço de norma descoberto")

        out: list[Norm] = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._parse_detail, url): url for url in list(candidates)[: max_records * 2]}
            for future in as_completed(futures):
                try:
                    norm = future.result()
                    if norm:
                        out.append(norm)
                except Exception:
                    continue
                if len(out) >= max_records:
                    break
        return deduplicate(out)

    def _looks_like_detail_url(self, url: str) -> bool:
        if not same_host_or_allowed(url, self.allowed_hosts):
            return False
        return any(pattern.search(url) for pattern in self.detail_patterns)

    def _discover_sitemaps(self, max_urls: int) -> set[str]:
        roots: set[str] = set()
        origin = self._origin(self.portal)
        try:
            robots = self.client.get(urljoin(origin, "/robots.txt"), timeout=20).text
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    roots.add(line.split(":", 1)[1].strip())
        except Exception:
            pass
        roots.update(
            {
                urljoin(origin, "/sitemap.xml"),
                urljoin(origin, "/sitemap_index.xml"),
                urljoin(origin, "/sitemap-index.xml"),
                urljoin(origin, "/wp-sitemap.xml"),
            }
        )

        found: set[str] = set()
        queue = deque((url, 0) for url in roots)
        visited: set[str] = set()
        while queue and len(found) < max_urls:
            sitemap_url, depth = queue.popleft()
            if sitemap_url in visited or depth > 3:
                continue
            visited.add(sitemap_url)
            try:
                response = self.client.get(sitemap_url, timeout=40)
                content = response.content
                if sitemap_url.lower().endswith(".gz") or response.headers.get("content-type", "").startswith("application/gzip"):
                    content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
                root = ET.fromstring(content)
            except Exception:
                continue
            locs = [clean_ws(node.text) for node in root.iter() if node.tag.lower().endswith("loc") and node.text]
            is_index = root.tag.lower().endswith("sitemapindex") or any(x.lower().endswith((".xml", ".xml.gz")) for x in locs[:10])
            if is_index:
                for loc in locs:
                    if same_host_or_allowed(loc, self.allowed_hosts):
                        queue.append((loc, depth + 1))
            else:
                for loc in locs:
                    if self._looks_like_detail_url(loc):
                        found.add(loc)
                        if len(found) >= max_urls:
                            break
        return found

    def _discover_commoncrawl(self, max_urls: int) -> set[str]:
        """Discover official URLs through the latest Common Crawl index.

        This is a discovery fallback, not a legal-data source: records are only
        accepted after the official page itself is downloaded and parsed.
        """
        try:
            collections = self.client.get_json("https://index.commoncrawl.org/collinfo.json", timeout=30)
            api = next((x.get("cdx-api") for x in collections if x.get("cdx-api")), "")
        except Exception:
            return set()
        if not api:
            return set()

        found: set[str] = set()
        wildcards: list[str] = list(self.cc_queries)
        if not wildcards:
            for host in self.allowed_hosts:
                for pattern in self.detail_patterns:
                    raw = pattern.pattern.replace("\\/", "/")
                    literal = re.split(r"[\[\]().+?{}|$^]", raw, maxsplit=1)[0].strip("/")
                    if literal:
                        wildcards.append(f"{host}/{literal}*")
                if not self.detail_patterns:
                    wildcards.append(f"{host}/*")

        for wildcard in wildcards:
            if len(found) >= max_urls:
                break
            base_params = {
                "url": wildcard,
                "output": "json",
                "filter": "status:200",
                "collapse": "urlkey",
                "fl": "url,mime,status",
                "pageSize": "5",
            }
            pages = 1
            try:
                response = self.client.get(api, params={**base_params, "showNumPages": "true"}, timeout=60)
                info = response.json()
                if isinstance(info, dict):
                    pages = min(int(info.get("pages", 1) or 1), 30)
            except Exception:
                pages = 1

            for page in range(pages):
                if len(found) >= max_urls:
                    break
                try:
                    response = self.client.get(api, params={**base_params, "page": str(page)}, timeout=90)
                except Exception:
                    continue
                for line in response.text.splitlines():
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    url = row.get("url", "")
                    mime = str(row.get("mime", "")).lower()
                    if not url or not same_host_or_allowed(url, self.allowed_hosts):
                        continue
                    if mime and not any(x in mime for x in ("html", "pdf", "text")):
                        continue
                    if self._looks_like_detail_url(url):
                        found.add(url)
                        if len(found) >= max_urls:
                            break
        return found

    def _crawl_listings(self, max_pages: int, max_detail: int) -> set[str]:
        queue = deque(self.start_urls)
        visited: set[str] = set()
        detail: set[str] = set()
        while queue and len(visited) < max_pages and len(detail) < max_detail:
            url = queue.popleft()
            if url in visited or not same_host_or_allowed(url, self.allowed_hosts):
                continue
            visited.add(url)
            try:
                response = self.client.get(url, timeout=45)
            except Exception:
                continue
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower() and b"<html" not in response.content[:1000].lower():
                continue
            soup = BeautifulSoup(response.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = absolutize(url, link.get("href"))
                if not same_host_or_allowed(href, self.allowed_hosts):
                    continue
                text = normalize(link.get_text(" ", strip=True))
                if self._looks_like_detail_url(href):
                    detail.add(href)
                    continue
                if self._is_pagination_or_listing(href, text, url):
                    queue.append(href)
            # Common query pagination when the page does not expose a next link.
            for generated in self._increment_page_urls(url):
                if generated not in visited:
                    queue.append(generated)
        return detail

    def _is_pagination_or_listing(self, href: str, text: str, current_url: str) -> bool:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        if any(p in params for p in PAGE_PARAMS):
            return True
        if any(word in text for word in PAGE_WORDS):
            return True
        # Follow nearby paths inside the same legislation section, but never assets.
        path = parsed.path.lower()
        if path.endswith((".css", ".js", ".jpg", ".jpeg", ".png", ".svg", ".pdf", ".zip")):
            return False
        current_path = urlparse(current_url).path.rstrip("/")
        if current_path and path.startswith(current_path.lower()) and len(path) <= len(current_path) + 80:
            return True
        return False

    @staticmethod
    def _increment_page_urls(url: str) -> Iterable[str]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in PAGE_PARAMS:
            if key in query and query[key]:
                try:
                    value = int(query[key][0])
                except ValueError:
                    continue
                next_query = {k: v[:] for k, v in query.items()}
                next_query[key] = [str(value + 1)]
                yield urlunparse(parsed._replace(query=urlencode(next_query, doseq=True)))

    def _parse_detail(self, url: str) -> Norm | None:
        response = self.client.get(url, timeout=60)
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or url.lower().split("?", 1)[0].endswith(".pdf"):
            # A PDF URL alone normally has no reliable title. It is only catalogued
            # when the filename clearly identifies a law.
            filename = urlparse(url).path.rsplit("/", 1)[-1]
            title = clean_ws(filename.replace("_", " ").replace("-", " "))
            if not is_law_title(title):
                return None
            final_type = classify_type(title)
            number, year = extract_number_year(title)
            return Norm(
                id=stable_id(self.uf, title, url),
                titulo=title,
                tipo=final_type,
                numero=number,
                ano=year,
                url_oficial=url,
                url_detalhe=url,
                texto_direto=False,
                documento_externo=True,
                fonte_catalogo="Portal oficial — sitemap",
            )

        soup = BeautifulSoup(response.text, "lxml")
        title = self._extract_title(soup)
        if not is_law_title(title):
            return None
        final_type = classify_type(title)
        if not final_type:
            return None
        number, year = extract_number_year(title, soup.get_text(" ", strip=True)[:2000])
        ementa = self._extract_ementa(soup)
        date = self._extract_date(soup.get_text(" ", strip=True)[:3000])
        subjects = self._extract_subjects(soup)

        # Prefer the HTML page because WebView can search its text. Use a linked PDF
        # only when the page itself does not contain a meaningful legal text.
        visible_text = clean_ws(soup.get_text(" ", strip=True))
        official_url = url
        direct = len(visible_text) >= 500 or "art." in normalize(visible_text)
        external = False
        if not direct:
            document = self._find_document_link(soup, url)
            if document:
                official_url = document
                external = document.lower().split("?", 1)[0].endswith((".pdf", ".doc", ".docx"))
                direct = not external

        return Norm(
            id=stable_id(self.uf, title, official_url),
            titulo=title,
            tipo=final_type,
            numero=number,
            ano=year,
            data=date,
            ementa=ementa,
            assuntos=subjects,
            url_oficial=official_url,
            url_detalhe=url,
            texto_direto=direct,
            documento_externo=external,
            fonte_catalogo="Portal oficial — catálogo nacional V2",
        )

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        selectors = [
            "h1",
            "article h2",
            ".titulo",
            ".title",
            ".page-title",
            "meta[property='og:title']",
            "title",
        ]
        candidates: list[str] = []
        for selector in selectors:
            for node in soup.select(selector):
                value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
                value = clean_ws(value)
                if value:
                    candidates.append(value)
        legal = [value for value in candidates if is_law_title(value)]
        if legal:
            return max(legal, key=len)

        # Lotus Notes and older government portals often use a generic HTML
        # <title> and place the norm identification in the first body lines.
        body = soup.get_text("\n", strip=True)
        for line in body.splitlines()[:120]:
            value = clean_ws(line)
            if is_law_title(value) and re.search(r"\d", value):
                return value[:500]
        match = re.search(
            r"((?:LEI\s+COMPLEMENTAR|LEI\s+ORDIN[ÁA]RIA|LEI\s+DELEGADA|LEI|CONSTITUI[ÇC][ÃA]O(?:\s+ESTADUAL)?|EMENDA\s+CONSTITUCIONAL)\s+(?:N[º°O.]?\s*)?[\d.]+(?:[/\-]\d{4})?(?:\s*,?\s*DE[^\n]{0,80})?)",
            body[:12000],
            re.I,
        )
        if match:
            return clean_ws(match.group(1))
        return candidates[0] if candidates else ""

    @staticmethod
    def _extract_ementa(soup: BeautifulSoup) -> str:
        for node in soup.find_all(string=True):
            if normalize(str(node)).rstrip(":") in {"ementa", "sumula", "assunto"}:
                parent = node.parent
                sibling = parent.find_next_sibling() if parent else None
                if sibling:
                    text = clean_ws(sibling.get_text(" ", strip=True))
                    if 10 <= len(text) <= 5000:
                        return text
                next_node = parent.find_next() if parent else None
                if next_node:
                    text = clean_ws(next_node.get_text(" ", strip=True))
                    if 10 <= len(text) <= 5000 and normalize(text) != normalize(str(node)):
                        return text
        meta = soup.select_one("meta[name='description']")
        if meta and meta.get("content"):
            return clean_ws(meta.get("content"))[:5000]
        # First paragraph after heading is often the ementa.
        heading = soup.find(["h1", "h2"])
        if heading:
            p = heading.find_next("p")
            if p:
                return clean_ws(p.get_text(" ", strip=True))[:5000]
        return ""

    @staticmethod
    def _extract_date(text: str) -> str:
        match = re.search(r"\b\d{1,2}[\-/]\d{1,2}[\-/](?:19|20)\d{2}\b", text)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_subjects(soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for selector in ("meta[name='keywords']", ".tags a", ".assuntos a", ".tag"):
            for node in soup.select(selector):
                value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
                if value:
                    values.extend(clean_ws(x) for x in re.split(r"[,;]", value) if clean_ws(x))
        return list(dict.fromkeys(values))[:50]

    @staticmethod
    def _find_document_link(soup: BeautifulSoup, page_url: str) -> str:
        preferred: list[str] = []
        fallback: list[str] = []
        for link in soup.find_all("a", href=True):
            href = absolutize(page_url, link.get("href"))
            low = href.lower().split("?", 1)[0]
            text = normalize(link.get_text(" ", strip=True))
            if low.endswith((".pdf", ".doc", ".docx", ".html", ".htm")):
                fallback.append(href)
                if any(x in text for x in ("texto integral", "texto original", "inteiro teor", "baixar", "download")):
                    preferred.append(href)
        return (preferred or fallback or [""])[0]

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
