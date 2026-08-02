#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "states.json").read_text(encoding="utf-8"))
CAT = ROOT / "docs" / "catalogos"
errors: list[str] = []
summary: list[dict[str, object]] = []

for state in CONFIG["states"]:
    uf = state["uf"]
    minimum = int(state.get("minimum_records", CONFIG.get("minimum_records_default", 25)))
    path = CAT / f"{uf}.json"
    if not path.exists():
        errors.append(f"{uf}: arquivo ausente")
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{uf}: JSON inválido: {exc}")
        continue
    if data.get("uf") != uf:
        errors.append(f"{uf}: campo uf divergente")
    norms = data.get("normas")
    if not isinstance(norms, list):
        errors.append(f"{uf}: normas não é uma lista")
        continue
    if len(norms) < minimum:
        errors.append(f"{uf}: somente {len(norms)} normas; mínimo {minimum}")
    ids: set[str] = set()
    invalid_urls = 0
    missing = 0
    for norm in norms:
        if not norm.get("id") or not norm.get("titulo") or not norm.get("tipo") or not norm.get("url_oficial"):
            missing += 1
            continue
        if norm["id"] in ids:
            errors.append(f"{uf}: id duplicado {norm['id']}")
        ids.add(norm["id"])
        parsed = urlparse(norm["url_oficial"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            invalid_urls += 1
    if missing:
        errors.append(f"{uf}: {missing} normas sem campos obrigatórios")
    if invalid_urls:
        errors.append(f"{uf}: {invalid_urls} URLs inválidas")
    summary.append({"uf": uf, "quantidade": len(norms), "mínimo": minimum, "status": data.get("status")})

print(json.dumps(summary, ensure_ascii=False, indent=2))
if errors:
    print("\nFALHAS DE VALIDAÇÃO:", file=sys.stderr)
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Catálogos nacionais validados com sucesso.")
