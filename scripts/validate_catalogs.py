#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "states.json").read_text(encoding="utf-8"))
CAT = ROOT / "docs" / "catalogos"
REPORT = ROOT / "docs" / "relatorios"
errors: list[str] = []
summary: list[dict[str, object]] = []

for state in CONFIG["states"]:
    uf = state["uf"]
    minimum = int(state.get("minimum_collected", state.get("minimum_records", CONFIG.get("minimum_records_default", 25))))
    path = CAT / f"{uf}.json"
    report_path = REPORT / f"{uf}.json"
    if not path.exists():
        errors.append(f"{uf}: catálogo ausente"); continue
    if not report_path.exists():
        errors.append(f"{uf}: relatório da coleta ausente"); continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{uf}: JSON inválido: {exc}"); continue
    norms = data.get("normas")
    if not isinstance(norms, list):
        errors.append(f"{uf}: normas não é lista"); continue
    collected = int(report.get("collected_count", 0) or 0)
    seeds = int(report.get("seed_count", report.get("curated_seed_count", 0)) or 0)
    if report.get("status") != "atualizado":
        errors.append(f"{uf}: relatório com status {report.get('status')}")
    if collected < minimum:
        errors.append(f"{uf}: {collected} normas realmente coletadas; mínimo {minimum}; sementes {seeds}")
    ids: set[str] = set(); invalid_urls = 0; missing = 0
    for norm in norms:
        if not norm.get("id") or not norm.get("titulo") or not norm.get("tipo") or not norm.get("url_oficial"):
            missing += 1; continue
        if norm["id"] in ids:
            errors.append(f"{uf}: id duplicado {norm['id']}")
        ids.add(norm["id"])
        parsed = urlparse(norm["url_oficial"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            invalid_urls += 1
    if missing: errors.append(f"{uf}: {missing} normas sem campos obrigatórios")
    if invalid_urls: errors.append(f"{uf}: {invalid_urls} URLs inválidas")
    summary.append({
        "uf": uf, "coletadas": collected, "sementes": seeds,
        "total_catalogo": len(norms), "mínimo": minimum,
        "status": report.get("status"), "estratégia": state.get("strategy"),
    })

print(json.dumps(summary, ensure_ascii=False, indent=2))
if errors:
    print("\nFALHAS DE VALIDAÇÃO V3:", file=sys.stderr)
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Catálogos V3 validados: todas as UFs atingiram o mínimo com normas realmente coletadas.")
