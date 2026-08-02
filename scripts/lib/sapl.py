from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, parse_qs

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
    stable_id,
)
from .http import HttpClient


class SaplConnector:
    """Coleta normas de instalações SAPL 3 e, como contingência, SAPL 2/HTML."""

    def __init__(self, client: HttpClient, base_url: str, uf: str, legacy: bool = False):
        self.client = client
        self.base = base_url.rstrip("/")
        self.uf = uf
        self.legacy = legacy

    def collect(self, max_records: int = 20000) -> list[Norm]:
        errors: list[str] = []
        if not self.legacy:
            try:
                norms = self._collect_api(max_records=max_records)
                if norms:
                    return deduplicate(norms)
            except Exception as exc:  # fallback is intentional
                errors.append(f"API: {exc!r}")
        try:
            norms = self._collect_html(max_records=max_records)
            if norms:
                return deduplicate(norms)
        except Exception as exc:
            errors.append(f"HTML: {exc!r}")
        raise RuntimeError("; ".join(errors) or "SAPL sem resultados")

    @staticmethod
    def _find_results(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("results", "resultados", "data", "items", "objects"):
            value = payload.get(key)
            if isinstance(value, list) and (not value or isinstance(value[0], dict)):
                return value
        for value in payload.values():
            found = SaplConnector._find_results(value)
            if found:
                return found
        return []

    @staticmethod
    def _next_url(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        direct = payload.get("next")
        if isinstance(direct, str):
            return direct
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            for key in ("next", "next_url"):
                value = pagination.get(key)
                if isinstance(value, str):
                    return value
            links = pagination.get("links")
            if isinstance(links, dict) and isinstance(links.get("next"), str):
                return links["next"]
        links = payload.get("links")
        if isinstance(links, dict) and isinstance(links.get("next"), str):
            return links["next"]
        return ""

    @staticmethod
    def _count(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        for key in ("count", "total", "total_entries", "total_count"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            return SaplConnector._count(pagination)
        return None

    def _type_map(self) -> dict[str, str]:
        url = f"{self.base}/api/norma/tiponormajuridica/?page_size=1000"
        payload = self.client.get_json(url)
        mapping: dict[str, str] = {}
        for item in self._find_results(payload):
            identifier = item.get("id")
            description = (
                item.get("descricao")
                or item.get("description")
                or item.get("sigla")
                or item.get("nome")
                or ""
            )
            if identifier is not None:
                mapping[str(identifier)] = clean_ws(str(description))
        return mapping

    def _collect_api(self, max_records: int) -> list[Norm]:
        type_map = self._type_map()
        page = 1
        page_size = 100
        url = f"{self.base}/api/norma/normajuridica/?page={page}&page_size={page_size}"
        out: list[Norm] = []
        seen_urls: set[str] = set()
        total: int | None = None

        while url and url not in seen_urls and len(out) < max_records:
            seen_urls.add(url)
            payload = self.client.get_json(url)
            items = self._find_results(payload)
            if total is None:
                total = self._count(payload)
            if not items:
                break
            for item in items:
                norm = self._api_item_to_norm(item, type_map)
                if norm is not None:
                    out.append(norm)
                    if len(out) >= max_records:
                        break
            next_url = self._next_url(payload)
            if next_url:
                url = absolutize(self.base + "/", next_url)
                continue
            if len(items) < page_size:
                break
            page += 1
            if total is not None and (page - 1) * page_size >= total:
                break
            url = f"{self.base}/api/norma/normajuridica/?page={page}&page_size={page_size}"
        return out

    def _api_item_to_norm(self, item: dict[str, Any], type_map: dict[str, str]) -> Norm | None:
        raw_type = item.get("tipo") or item.get("tipo_id") or item.get("tipo_norma")
        if isinstance(raw_type, dict):
            type_text = clean_ws(
                str(raw_type.get("descricao") or raw_type.get("sigla") or raw_type.get("nome") or "")
            )
        else:
            type_text = type_map.get(str(raw_type), clean_ws(str(raw_type or "")))

        number = clean_ws(str(item.get("numero") or ""))
        year = clean_ws(str(item.get("ano") or ""))
        data = clean_ws(str(item.get("data") or item.get("data_norma") or ""))
        ementa = clean_ws(str(item.get("ementa") or ""))
        title = clean_ws(str(item.get("titulo") or ""))
        if not title:
            type_display = type_text or "Norma"
            title = f"{type_display} nº {number}" + (f"/{year}" if year else "")

        final_type = classify_type(type_text + " " + title)
        if not final_type:
            return None

        item_id = item.get("id") or item.get("pk")
        detail_url = f"{self.base}/norma/{item_id}" if item_id else ""
        text_value = (
            item.get("texto_integral")
            or item.get("texto_original")
            or item.get("arquivo")
            or item.get("url_texto_integral")
            or ""
        )
        if isinstance(text_value, dict):
            text_value = text_value.get("url") or text_value.get("arquivo") or ""
        official_url = absolutize(self.base + "/", str(text_value)) if text_value else detail_url
        if not official_url:
            return None

        subjects_raw = item.get("assuntos") or item.get("assunto") or []
        subjects: list[str] = []
        if isinstance(subjects_raw, list):
            for value in subjects_raw:
                if isinstance(value, dict):
                    value = value.get("assunto") or value.get("descricao") or value.get("nome") or ""
                if value:
                    subjects.append(clean_ws(str(value)))
        elif subjects_raw:
            subjects = [clean_ws(str(subjects_raw))]
        indexation = clean_ws(str(item.get("indexacao") or ""))
        if indexation:
            subjects.extend([clean_ws(x) for x in re.split(r"[,;]", indexation) if clean_ws(x)])

        return Norm(
            id=f"sapl-{self.uf.lower()}-{item_id or stable_id(self.uf, title, official_url)}",
            titulo=title,
            tipo=final_type,
            numero=number,
            ano=year,
            data=data,
            ementa=ementa,
            assuntos=subjects,
            url_oficial=official_url,
            url_detalhe=detail_url,
            texto_direto=not official_url.lower().split("?", 1)[0].endswith(".pdf"),
            documento_externo=official_url.lower().split("?", 1)[0].endswith(".pdf"),
            fonte_catalogo="SAPL OpenAPI",
        )

    def _collect_html(self, max_records: int) -> list[Norm]:
        search_url = self._html_search_url(1)
        first = self.client.get(search_url)
        soup = BeautifulSoup(first.text, "lxml")
        total = self._extract_total(soup.get_text(" ", strip=True))
        detail_urls = self._extract_detail_urls(soup)
        per_page = max(len(detail_urls), 1)
        pages = min(math.ceil(total / per_page) if total else 1, 2000)

        # Pull remaining result pages and collect stable detail URLs.
        for page in range(2, pages + 1):
            if len(detail_urls) >= max_records:
                break
            response = self.client.get(self._html_search_url(page))
            page_soup = BeautifulSoup(response.text, "lxml")
            new_urls = self._extract_detail_urls(page_soup)
            before = len(detail_urls)
            detail_urls.update(new_urls)
            if len(detail_urls) == before and page > 3:
                break

        urls = list(detail_urls)[:max_records]
        out: list[Norm] = []
        workers = 8
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._parse_detail, url): url for url in urls}
            for future in as_completed(futures):
                try:
                    norm = future.result()
                    if norm is not None:
                        out.append(norm)
                except Exception:
                    continue
        return out

    def _html_search_url(self, page: int) -> str:
        if self.legacy:
            # SAPL 2 installations use a different application tree. The form accepts
            # an empty query, which lists the registered norms.
            return (
                f"{self.base}/sapl/generico/norma_juridica_pesquisar_form?"
                f"incluir=0&lst_tip_norma=&txt_numero=&txt_ano=&page={page}"
            )
        return (
            f"{self.base}/norma/pesquisar?ano=&assuntos=&data_0=&data_1=&"
            f"data_publicacao_0=&data_publicacao_1=&ementa=&numero=&page={page}&"
            "salvar=Pesquisar&tipo="
        )

    @staticmethod
    def _extract_total(text: str) -> int:
        patterns = [
            r"foram encontradas\s+([\d.]+)\s+normas",
            r"foram encontrados\s+([\d.]+)\s+registros",
            r"total(?: de)?\s*:?\s*([\d.]+)",
        ]
        ntext = normalize(text)
        for pattern in patterns:
            match = re.search(pattern, ntext, re.I)
            if match:
                return int(match.group(1).replace(".", ""))
        return 0

    def _extract_detail_urls(self, soup: BeautifulSoup) -> set[str]:
        urls: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = absolutize(self.base + "/", link.get("href"))
            path = urlparse(href).path
            if re.search(r"/norma/\d+/?$", path):
                urls.add(href)
            elif self.legacy and "norma_juridica_mostrar_proc" in href:
                urls.add(href)
        return urls

    def _parse_detail(self, url: str) -> Norm | None:
        response = self.client.get(url)
        soup = BeautifulSoup(response.text, "lxml")
        heading = soup.find("h1") or soup.find("h2") or soup.find("title")
        title = clean_ws(heading.get_text(" ", strip=True) if heading else "")
        if not is_law_title(title):
            return None
        final_type = classify_type(title)
        number, year = extract_number_year(title)
        body_text = clean_ws(soup.get_text(" ", strip=True))
        data_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", body_text)
        data = data_match.group(0) if data_match else ""
        ementa = self._extract_label_value(soup, "Ementa")
        indexation = self._extract_label_value(soup, "Indexação")
        subjects = [clean_ws(x) for x in re.split(r"[,;]", indexation) if clean_ws(x)]

        official_url = ""
        for link in soup.find_all("a", href=True):
            text = normalize(link.get_text(" ", strip=True))
            href = absolutize(url, link.get("href"))
            if any(token in text for token in ("texto original", "texto integral", "texto compilado")):
                official_url = href
                break
            if href.lower().split("?", 1)[0].endswith((".pdf", ".doc", ".docx", ".html", ".htm")):
                official_url = href
                break
        if not official_url:
            official_url = url

        id_match = re.search(r"/norma/(\d+)", url)
        identifier = f"sapl-{self.uf.lower()}-{id_match.group(1)}" if id_match else stable_id(self.uf, title, official_url)
        return Norm(
            id=identifier,
            titulo=title,
            tipo=final_type,
            numero=number,
            ano=year,
            data=data,
            ementa=ementa,
            assuntos=subjects,
            url_oficial=official_url,
            url_detalhe=url,
            texto_direto=not official_url.lower().split("?", 1)[0].endswith(".pdf"),
            documento_externo=official_url.lower().split("?", 1)[0].endswith(".pdf"),
            fonte_catalogo="SAPL HTML",
        )

    @staticmethod
    def _extract_label_value(soup: BeautifulSoup, label: str) -> str:
        target = normalize(label)
        for node in soup.find_all(string=True):
            if normalize(str(node)).rstrip(":") == target:
                parent = node.parent
                # Common SAPL layout: label in dt/div followed by dd/div.
                sibling = parent.find_next_sibling() if parent else None
                if sibling:
                    value = clean_ws(sibling.get_text(" ", strip=True))
                    if value:
                        return value
                following = parent.find_next() if parent else None
                if following:
                    value = clean_ws(following.get_text(" ", strip=True))
                    if value and normalize(value) != target:
                        return value
        return ""
