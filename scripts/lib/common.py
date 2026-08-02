from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

LAW_RE = re.compile(
    r"\b(lei\s+complementar|lei\s+ordin[aá]ria|lei\s+delegada|lei|constitui[cç][aã]o(?:\s+estadual)?|emenda\s+constitucional)\b",
    re.I,
)
NUMBER_RE = re.compile(r"(?:n[º°o.]?\s*)?([\d.]+)(?:\s*[/\-]\s*(\d{4}))?", re.I)
YEAR_RE = re.compile(r"\b(18|19|20)\d{2}\b")


def normalize(text: str | None) -> str:
    text = text or ""
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    ).lower().strip()


def clean_ws(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_law_title(text: str | None) -> bool:
    return bool(LAW_RE.search(clean_ws(text)))


def classify_type(text: str | None) -> str:
    n = normalize(text)
    if "constituicao" in n and "emenda" not in n:
        return "Constituição Estadual"
    if "emenda constitucional" in n:
        return "Emenda Constitucional"
    if "lei complementar" in n:
        return "Lei Complementar"
    if "lei delegada" in n:
        return "Lei Delegada"
    if "lei" in n:
        return "Lei Ordinária"
    return ""


def extract_number_year(title: str, data: str = "") -> tuple[str, str]:
    title = clean_ws(title)
    number = ""
    year = ""
    # Prefer number after the type name.
    m_type = LAW_RE.search(title)
    search_part = title[m_type.end():] if m_type else title
    m = NUMBER_RE.search(search_part)
    if m:
        number = m.group(1).replace(".", "")
        year = m.group(2) or ""
    if not year:
        years = YEAR_RE.findall(title + " " + data)
        # findall with group returns prefix; use finditer instead
        matches = list(YEAR_RE.finditer(title + " " + data))
        if matches:
            year = matches[-1].group(0)
    return number, year


def stable_id(uf: str, title: str, official_url: str = "") -> str:
    basis = f"{uf}|{normalize(title)}|{official_url}".encode("utf-8")
    return f"{uf.lower()}-{hashlib.sha1(basis).hexdigest()[:18]}"


def absolutize(base: str, value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value)


def same_host_or_allowed(url: str, allowed_hosts: Iterable[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {h.lower() for h in allowed_hosts}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(slots=True)
class Norm:
    id: str
    titulo: str
    tipo: str
    numero: str = ""
    ano: str = ""
    data: str = ""
    ementa: str = ""
    assuntos: list[str] | None = None
    url_oficial: str = ""
    url_detalhe: str = ""
    url_lexml: str = ""
    texto_direto: bool = False
    documento_externo: bool = False
    fonte_catalogo: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["assuntos"] = self.assuntos or []
        return d


def deduplicate(norms: Iterable[Norm]) -> list[Norm]:
    by_key: dict[str, Norm] = {}
    for norm in norms:
        if not norm.titulo or not norm.url_oficial:
            continue
        key = (
            normalize(norm.tipo),
            re.sub(r"\D", "", norm.numero or ""),
            norm.ano or "",
        )
        if not key[1] and not key[2]:
            key = (normalize(norm.titulo), "", "")
        skey = "|".join(key)
        old = by_key.get(skey)
        if old is None:
            by_key[skey] = norm
            continue
        # Prefer direct HTML and richer metadata.
        old_score = int(old.texto_direto) * 10 + len(old.ementa) + len(old.assuntos or []) * 10
        new_score = int(norm.texto_direto) * 10 + len(norm.ementa) + len(norm.assuntos or []) * 10
        if new_score > old_score:
            by_key[skey] = norm
    return sorted(
        by_key.values(),
        key=lambda n: (int(n.ano) if str(n.ano).isdigit() else 0, int(re.sub(r"\D", "", n.numero) or 0)),
        reverse=True,
    )
