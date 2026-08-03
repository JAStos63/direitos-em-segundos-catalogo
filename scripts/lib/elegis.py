from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import Norm, classify_type, clean_ws, deduplicate, extract_number_year, normalize, stable_id
from .http import HttpClient


class ElegisConnector:
    """Coletor específico do eLegis da Assembleia Legislativa do Amapá.

    A listagem pública expõe o título/ementa da lei e um vínculo para a
    proposição. O texto integral usa uma rota estável derivada dessa proposição:
    /portal/proposicao/<id>/texto-integral.
    """

    def __init__(self, client: HttpClient, base_url: str, uf: str = "AP"):
        self.client = client
        self.base = base_url.rstrip("/")
        self.uf = uf
        self.listing = f"{self.base}/portal/legislacao"

    def collect(self, max_records: int = 10000, max_pages: int = 400) -> list[Norm]:
        out: list[Norm] = []
        seen_ids: set[str] = set()
        errors: list[str] = []

        # Primeiro tenta a listagem geral. Em alguns períodos o eLegis responde
        # com HTTP 500 quando precisa montar todas as milhares de normas.
        try:
            self._collect_query(
                params={}, out=out, seen_ids=seen_ids,
                max_records=max_records, max_pages=max_pages,
            )
        except Exception as exc:
            errors.append(f"listagem geral: {exc!r}")

        # Fallback: consultas anuais são muito menores e costumam continuar
        # funcionando mesmo quando a listagem geral está sobrecarregada. Também
        # complementa anos eventualmente omitidos pela paginação geral.
        if len(out) < max_records:
            current_year = datetime.now(UTC).year
            for year in range(current_year, 1989, -1):
                try:
                    self._collect_query(
                        params={"ano": year}, out=out, seen_ids=seen_ids,
                        max_records=max_records, max_pages=min(max_pages, 80),
                    )
                except Exception as exc:
                    errors.append(f"ano {year}: {exc!r}")
                    continue
                if len(out) >= max_records:
                    break

        if not out:
            detail = "; ".join(errors[-5:])
            raise RuntimeError(
                "eLegis não apresentou leis na listagem pública"
                + (f": {detail}" if detail else "")
            )
        return deduplicate(out)

    def _collect_query(
        self,
        params: dict[str, object],
        out: list[Norm],
        seen_ids: set[str],
        max_records: int,
        max_pages: int,
    ) -> None:
        expected_pages: int | None = None
        empty_streak = 0

        for page in range(1, max_pages + 1):
            query = dict(params)
            query["page"] = page
            response = self.client.get(self.listing, params=query, timeout=75)
            norms, total = self.parse_listing(response.text, response.url)

            if expected_pages is None and total:
                per_page = max(len(norms), 1)
                expected_pages = max(1, math.ceil(total / per_page))

            added = 0
            for norm in norms:
                if norm.id in seen_ids:
                    continue
                seen_ids.add(norm.id)
                out.append(norm)
                added += 1
                if len(out) >= max_records:
                    return

            empty_streak = empty_streak + 1 if added == 0 else 0
            if expected_pages and page >= expected_pages:
                break
            if empty_streak >= 2:
                break

    def parse_listing(self, html: str, page_url: str | None = None) -> tuple[list[Norm], int]:
        soup = BeautifulSoup(html, "lxml")
        page_url = page_url or self.listing
        text = clean_ws(soup.get_text(" ", strip=True))
        total = 0
        match = re.search(r"([\d.]+)\s+itens?\s+encontrados?", normalize(text))
        if match:
            total = int(match.group(1).replace(".", ""))

        out: list[Norm] = []
        # Primary layout: table rows with law identification, ementa and a
        # proposition link. This is stable across current eLegis pages.
        for row in soup.select("table tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            title = clean_ws(cells[0].get_text(" ", strip=True))
            final_type = classify_type(title)
            if final_type not in {"Lei Ordinária", "Lei Complementar", "Constituição Estadual", "Emenda Constitucional", "Lei Delegada"}:
                continue
            proposition = row.find("a", href=re.compile(r"/portal/proposicao/\d+(?:/)?$"))
            if proposition is None:
                # Some deployments place the link in a data attribute or a button.
                proposition = row.find("a", href=re.compile(r"/portal/proposicao/\d+"))
            if proposition is None:
                continue
            detail = urljoin(page_url, proposition.get("href"))
            pid_match = re.search(r"/portal/proposicao/(\d+)", detail)
            if not pid_match:
                continue
            pid = pid_match.group(1)
            official = f"{self.base}/portal/proposicao/{pid}/texto-integral"
            ementa = clean_ws(cells[1].get_text(" ", strip=True))
            data = ""
            date_match = re.search(r"\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b", title)
            if date_match:
                data = date_match.group(0)
            number, year = extract_number_year(title, data)
            out.append(Norm(
                id=f"elegis-{self.uf.lower()}-{pid}",
                titulo=title,
                tipo=final_type,
                numero=number,
                ano=year,
                data=data,
                ementa=ementa,
                assuntos=[],
                url_oficial=official,
                url_detalhe=detail,
                texto_direto=True,
                documento_externo=False,
                fonte_catalogo="eLegis — listagem oficial",
            ))

        # Fallback for HTML variations without a semantic table.
        if not out:
            for link in soup.find_all("a", href=re.compile(r"/portal/proposicao/\d+")):
                container = link.find_parent(["tr", "article", "li", "div"])
                if not container:
                    continue
                block = clean_ws(container.get_text(" ", strip=True))
                title_match = re.search(
                    r"((?:Lei\s+Complementar|Lei\s+Ordin[aá]ria|Lei\s+Delegada|Constitui[cç][aã]o(?:\s+Estadual)?|Emenda\s+Constitucional)\s+(?:n[º°o.]?\s*)?[\d.]+[^|]{0,90})",
                    block, re.I,
                )
                if not title_match:
                    continue
                title = clean_ws(title_match.group(1))
                final_type = classify_type(title)
                detail = urljoin(page_url, link.get("href"))
                pid_match = re.search(r"/portal/proposicao/(\d+)", detail)
                if not pid_match:
                    continue
                pid = pid_match.group(1)
                number, year = extract_number_year(title, block)
                out.append(Norm(
                    id=f"elegis-{self.uf.lower()}-{pid}", titulo=title, tipo=final_type,
                    numero=number, ano=year, ementa="", assuntos=[],
                    url_oficial=f"{self.base}/portal/proposicao/{pid}/texto-integral",
                    url_detalhe=detail, texto_direto=True, documento_externo=False,
                    fonte_catalogo="eLegis — listagem oficial",
                ))
        return deduplicate(out), total
