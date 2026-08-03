from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import Norm, absolutize, classify_type, clean_ws, deduplicate, extract_number_year, normalize, stable_id
from .http import HttpClient


_ALLOWED_TYPES = {"Lei Ordinária", "Lei Complementar", "Constituição Estadual", "Emenda Constitucional", "Lei Delegada"}


class SaplConnector:
    """Coleta normas de SAPL 3 e SAPL 2.

    V3 prioriza a própria página pública de resultados, pois ela já expõe o
    título, a ementa, o detalhe e o Texto Original. A API continua como primeira
    tentativa, com descoberta de diferentes rotas usadas pelas versões do SAPL.
    """

    API_PATHS = (
        "/api/norma/normajuridica/",
        "/api/norma/norma-juridica/",
        "/api/norma/normajuridica",
    )
    TYPE_PATHS = (
        "/api/norma/tiponormajuridica/",
        "/api/norma/tipo-norma-juridica/",
    )

    def __init__(self, client: HttpClient, base_url: str, uf: str, legacy: bool = False):
        self.client = client
        self.base = base_url.rstrip("/")
        self.uf = uf
        self.legacy = legacy

    def collect(self, max_records: int = 20000) -> list[Norm]:
        errors: list[str] = []
        combined: list[Norm] = []

        # A listagem HTML pública é mais estável entre versões do SAPL e evita
        # bloqueios 403 observados em algumas APIs. Também permite filtrar os
        # tipos de norma antes de percorrer milhares de decretos e resoluções.
        try:
            combined.extend(self._collect_html(max_records=max_records))
        except Exception as exc:
            errors.append(f"HTML: {exc!r}")

        # Quando o HTML retorna poucos itens, tenta complementar pela API. Isso
        # corrige instalações que exibem só uma parte dos tipos na interface.
        if not self.legacy and len(deduplicate(combined)) < min(100, max_records):
            for api_path in self.API_PATHS:
                try:
                    api_norms = self._collect_api(api_path, max_records)
                    if api_norms:
                        combined.extend(api_norms)
                        break
                except Exception as exc:
                    errors.append(f"API {api_path}: {exc!r}")

        result = deduplicate(combined)
        if result:
            return result[:max_records]
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
        if isinstance(payload.get("next"), str):
            return payload["next"]
        for root in (payload.get("pagination"), payload.get("links")):
            if isinstance(root, dict):
                if isinstance(root.get("next"), str):
                    return root["next"]
                if isinstance(root.get("next_url"), str):
                    return root["next_url"]
                links = root.get("links")
                if isinstance(links, dict) and isinstance(links.get("next"), str):
                    return links["next"]
        return ""

    def _load_type_map(self) -> dict[str, str]:
        for path in self.TYPE_PATHS:
            try:
                payload = self.client.get_json(self.base + path, params={"page_size": 1000}, timeout=45)
            except Exception:
                continue
            mapping: dict[str, str] = {}
            for item in self._find_results(payload):
                ident = item.get("id") or item.get("pk")
                desc = item.get("descricao") or item.get("description") or item.get("sigla") or item.get("nome")
                if ident is not None and desc:
                    mapping[str(ident)] = clean_ws(str(desc))
            if mapping:
                return mapping
        return {}

    def _collect_api(self, api_path: str, max_records: int) -> list[Norm]:
        type_map = self._load_type_map()
        out: list[Norm] = []
        page = 1
        seen: set[str] = set()
        url = self.base + api_path
        while url and url not in seen and len(out) < max_records:
            seen.add(url)
            payload = self.client.get_json(url, params=None if "?" in url else {"page": page, "page_size": 100}, timeout=60)
            items = self._find_results(payload)
            if not items:
                break
            for item in items:
                norm = self._api_item_to_norm(item, type_map)
                if norm:
                    out.append(norm)
                    if len(out) >= max_records:
                        break
            nxt = self._next_url(payload)
            if nxt:
                url = absolutize(self.base + "/", nxt)
            else:
                if len(items) < 100:
                    break
                page += 1
                url = f"{self.base}{api_path}?page={page}&page_size=100"
        return out

    def _api_item_to_norm(self, item: dict[str, Any], type_map: dict[str, str]) -> Norm | None:
        raw_type = item.get("tipo") or item.get("tipo_id") or item.get("tipo_norma")
        if isinstance(raw_type, dict):
            type_text = clean_ws(str(raw_type.get("descricao") or raw_type.get("sigla") or raw_type.get("nome") or ""))
        else:
            type_text = type_map.get(str(raw_type), clean_ws(str(raw_type or "")))
        number = clean_ws(str(item.get("numero") or ""))
        year = clean_ws(str(item.get("ano") or ""))
        data = clean_ws(str(item.get("data") or item.get("data_norma") or ""))
        title = clean_ws(str(item.get("titulo") or "")) or f"{type_text or 'Norma'} nº {number}" + (f"/{year}" if year else "")
        final_type = classify_type(type_text + " " + title)
        if final_type not in _ALLOWED_TYPES:
            return None
        item_id = item.get("id") or item.get("pk")
        detail = f"{self.base}/norma/{item_id}" if item_id else ""
        text_value = item.get("texto_integral") or item.get("texto_original") or item.get("arquivo") or item.get("url_texto_integral") or ""
        if isinstance(text_value, dict):
            text_value = text_value.get("url") or text_value.get("arquivo") or ""
        official = absolutize(self.base + "/", str(text_value)) if text_value else detail
        if not official:
            return None
        subjects_raw = item.get("assuntos") or item.get("assunto") or []
        subjects: list[str] = []
        if isinstance(subjects_raw, list):
            for val in subjects_raw:
                if isinstance(val, dict):
                    val = val.get("assunto") or val.get("descricao") or val.get("nome") or ""
                if val: subjects.append(clean_ws(str(val)))
        elif subjects_raw:
            subjects.append(clean_ws(str(subjects_raw)))
        index = clean_ws(str(item.get("indexacao") or ""))
        if index:
            subjects.extend(clean_ws(x) for x in re.split(r"[,;]", index) if clean_ws(x))
        external = official.lower().split("?", 1)[0].endswith((".pdf", ".doc", ".docx"))
        return Norm(
            id=f"sapl-{self.uf.lower()}-{item_id or stable_id(self.uf, title, official)}",
            titulo=title, tipo=final_type, numero=number, ano=year, data=data,
            ementa=clean_ws(str(item.get("ementa") or "")), assuntos=subjects,
            url_oficial=official, url_detalhe=detail, texto_direto=not external,
            documento_externo=external, fonte_catalogo="SAPL OpenAPI",
        )

    def _discover_target_type_ids(self) -> list[str]:
        if self.legacy:
            return []
        try:
            response = self.client.get(f"{self.base}/norma/pesquisar", timeout=45)
        except Exception:
            return []
        soup = BeautifulSoup(response.text, "lxml")
        ids: list[str] = []
        for select in soup.find_all("select"):
            name = str(select.get("name") or "").lower()
            if "tipo" not in name:
                continue
            for option in select.find_all("option"):
                value = clean_ws(str(option.get("value") or ""))
                label = clean_ws(option.get_text(" ", strip=True))
                if value and classify_type(label) in _ALLOWED_TYPES:
                    ids.append(value)
        return list(dict.fromkeys(ids))

    def _collect_html(self, max_records: int) -> list[Norm]:
        out: list[Norm] = []
        seen_keys: set[str] = set()
        type_ids = self._discover_target_type_ids() or [""]

        for type_id in type_ids:
            page = 1
            empty_streak = 0
            expected_pages: int | None = None

            while len(out) < max_records and page <= 2500:
                html, final_url = self._fetch_result_page(page, type_id=type_id)
                page_norms, total = self.parse_results(html, final_url)
                if total and expected_pages is None:
                    per_page = max(len(page_norms), 1)
                    expected_pages = max(1, (total + per_page - 1) // per_page)
                added = 0
                for norm in page_norms:
                    key = norm.id or f"{norm.tipo}|{norm.numero}|{norm.ano}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    out.append(norm)
                    added += 1
                    if len(out) >= max_records:
                        break
                empty_streak = empty_streak + 1 if added == 0 else 0
                if expected_pages and page >= expected_pages:
                    break
                if empty_streak >= 2:
                    break
                page += 1

        return deduplicate(out)

    def _fetch_result_page(self, page: int, type_id: str = "") -> tuple[str, str]:
        if self.legacy:
            candidates = [
                f"{self.base}/sapl/generico/norma_juridica_pesquisar_form?incluir=0&lst_tip_norma={type_id}&txt_numero=&txt_ano=&page={page}",
            ]
        else:
            full = (
                f"{self.base}/norma/pesquisar?ano=&assuntos=&data_0=&data_1=&"
                f"data_publicacao_0=&data_publicacao_1=&data_vigencia_0=&data_vigencia_1=&"
                f"ementa=&indexacao=&iframe=-1&numero=&o=&orgao=&page={page}&"
                f"salvar=Pesquisar&tipo={type_id}"
            )
            candidates = [
                full,
                f"{self.base}/norma/pesquisar?salvar=Pesquisar&iframe=-1&tipo={type_id}&page={page}",
                f"{self.base}/norma/pesquisar?salvar=Pesquisar&tipo={type_id}&page={page}",
            ]
        errors: list[str] = []
        for url in candidates:
            try:
                response = self.client.get(url, timeout=75)
            except Exception as exc:
                errors.append(repr(exc))
                continue
            soup = BeautifulSoup(response.text, "lxml")
            text = normalize(soup.get_text(" ", strip=True))
            if self.legacy or soup.find("a", href=re.compile(r"/norma/\d+")) or "pesquisa concluida" in text:
                return response.text, response.url
        raise RuntimeError("SAPL não retornou a lista de resultados: " + "; ".join(errors))

    def parse_results(self, html: str, page_url: str) -> tuple[list[Norm], int]:
        soup = BeautifulSoup(html, "lxml")
        text = clean_ws(soup.get_text(" ", strip=True))
        total = 0
        for pattern in (
            r"foram encontradas\s+([\d.]+)\s+normas",
            r"foram encontrados\s+([\d.]+)\s+registros",
            r"total(?:\s+de)?\s*:?[ ]*([\d.]+)",
        ):
            m = re.search(pattern, normalize(text))
            if m:
                total = int(m.group(1).replace(".", "")); break

        out: list[Norm] = []
        for link in soup.find_all("a", href=re.compile(r"/norma/\d+")):
            title = clean_ws(link.get_text(" ", strip=True))
            final_type = classify_type(title)
            if final_type not in _ALLOWED_TYPES:
                continue
            detail = urljoin(page_url, link.get("href"))
            container = self._result_container(link)
            ementa = self._extract_ementa_from_container(container)
            official = self._find_text_link(container, page_url) or detail
            number, year = extract_number_year(title, clean_ws(container.get_text(" ", strip=True)) if container else "")
            date_match = re.search(r"\b\d{1,2}\s+de\s+[a-zç]+\s+de\s+(?:19|20)\d{2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b", title, re.I)
            data = date_match.group(0) if date_match else ""
            id_match = re.search(r"/norma/(\d+)", detail)
            external = official.lower().split("?", 1)[0].endswith((".pdf", ".doc", ".docx"))
            out.append(Norm(
                id=f"sapl-{self.uf.lower()}-{id_match.group(1) if id_match else stable_id(self.uf, title, official)}",
                titulo=title, tipo=final_type, numero=number, ano=year, data=data,
                ementa=ementa, assuntos=[], url_oficial=official, url_detalhe=detail,
                texto_direto=not external, documento_externo=external,
                fonte_catalogo="SAPL — resultado oficial",
            ))
        return deduplicate(out), total

    @staticmethod
    def _result_container(link):
        # Bootstrap SAPL versions use list-group-item; older/custom themes may
        # use cards, table rows or generic blocks.
        for selector in (".list-group-item", ".card", "tr", "article", "li"):
            node = link.find_parent(selector)
            if node is not None:
                return node
        node = link.parent
        for _ in range(5):
            if node is None: break
            txt = normalize(node.get_text(" ", strip=True))
            if "ementa" in txt and ("texto original" in txt or "texto integral" in txt):
                return node
            node = node.parent
        return link.parent

    @staticmethod
    def _extract_ementa_from_container(container) -> str:
        if container is None:
            return ""
        text = clean_ws(container.get_text(" ", strip=True))
        m = re.search(r"ementa\s*:\s*(.+?)(?:texto\s+(?:original|integral|compilado)|norma\s+sem|relacionamentos|$)", text, re.I)
        return clean_ws(m.group(1))[:5000] if m else ""

    @staticmethod
    def _find_text_link(container, page_url: str) -> str:
        if container is None:
            return ""
        fallback = ""
        for a in container.find_all("a", href=True):
            href = urljoin(page_url, a.get("href"))
            label = normalize(a.get_text(" ", strip=True))
            low = href.lower().split("?", 1)[0]
            if any(x in label for x in ("texto original", "texto integral", "texto compilado", "inteiro teor")):
                return href
            if not fallback and low.endswith((".pdf", ".doc", ".docx", ".html", ".htm")):
                fallback = href
        return fallback
