#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "states.json").read_text(encoding="utf-8"))
DOCS = ROOT / "docs"
CAT = DOCS / "catalogos"
REPORT = DOCS / "relatorios"

states = []
rows = []
for state in CONFIG["states"]:
    uf = state["uf"]
    path = CAT / f"{uf}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"normas": []}
    count = len(data.get("normas", []))
    status = data.get("status", "ausente")
    direct = sum(1 for n in data.get("normas", []) if n.get("texto_direto"))
    external = sum(1 for n in data.get("normas", []) if n.get("documento_externo"))
    states.append(
        {
            "uf": uf,
            "estado": state["estado"],
            "arquivo": f"catalogos/{uf}.json",
            "portal_oficial": state.get("portal", ""),
            "quantidade": count,
            "texto_direto": direct,
            "documentos_externos": external,
            "status": status,
        }
    )
    status_class = "ok" if status == "atualizado" else "bad"
    rows.append(
        f"<tr><td><a href='catalogos/{uf}.json'>{uf}</a></td>"
        f"<td>{html.escape(state['estado'])}</td><td>{count}</td><td>{direct}</td>"
        f"<td>{external}</td><td class='{status_class}'>{html.escape(status)}</td></tr>"
    )

manifest = {
    "schema_version": 2,
    "catalog_version": max(
        [json.loads((CAT / f"{s['uf']}.json").read_text(encoding="utf-8")).get("catalog_version", "") for s in CONFIG["states"] if (CAT / f"{s['uf']}.json").exists()]
        or [""]
    ),
    "owner": "JAStos63",
    "repository": "direitos-em-segundos-catalogo",
    "states": states,
}
(DOCS / "index.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

page = f"""<!doctype html>
<html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Direitos em Segundos — Catálogo Nacional V2</title>
<style>body{{font-family:system-ui;margin:0;background:#eef3f7;color:#142535}}main{{max-width:1050px;margin:30px auto;background:white;padding:24px;border-radius:14px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #dfe7ec;text-align:left}}th{{background:#143d59;color:white}}.ok{{color:#146c43;font-weight:700}}.bad{{color:#b02a37;font-weight:700}}code{{background:#eef3f7;padding:2px 5px}}</style></head>
<body><main><h1>Direitos em Segundos — Catálogo Nacional V2</h1>
<p>Relatório público dos catálogos estaduais. A atualização só é aceita quando cada unidade federativa atinge o mínimo configurado.</p>
<table><thead><tr><th>UF</th><th>Estado</th><th>Normas</th><th>HTML pesquisável</th><th>Documentos externos</th><th>Status</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p>Manifesto: <a href='index.json'><code>index.json</code></a></p></main></body></html>"""
(DOCS / "index.html").write_text(page, encoding="utf-8")
print(f"Índice criado para {len(states)} UFs")
