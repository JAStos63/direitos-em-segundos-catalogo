#!/usr/bin/env python3
from __future__ import annotations
import html, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/states.json').read_text(encoding='utf-8'))
DOCS=ROOT/'docs'; CAT=DOCS/'catalogos'; REPORT=DOCS/'relatorios'
states=[]; rows=[]
for state in CONFIG['states']:
    uf=state['uf']; cp=CAT/f'{uf}.json'; rp=REPORT/f'{uf}.json'
    data=json.loads(cp.read_text(encoding='utf-8')) if cp.exists() else {'normas':[]}
    report=json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else {}
    norms=data.get('normas',[]); collected=int(report.get('collected_count',0) or 0)
    seeds=int(report.get('seed_count',report.get('curated_seed_count',0)) or 0)
    status=report.get('status',data.get('status','ausente'))
    direct=sum(1 for n in norms if n.get('texto_direto')); external=sum(1 for n in norms if n.get('documento_externo'))
    states.append({'uf':uf,'estado':state['estado'],'arquivo':f'catalogos/{uf}.json','relatorio':f'relatorios/{uf}.json','portal_oficial':state.get('portal',''),'coletadas':collected,'sementes':seeds,'quantidade':len(norms),'texto_direto':direct,'documentos_externos':external,'status':status,'strategy':state.get('strategy')})
    css='ok' if status=='atualizado' else 'bad'
    rows.append(f"<tr><td><a href='catalogos/{uf}.json'>{uf}</a></td><td>{html.escape(state['estado'])}</td><td>{html.escape(state.get('strategy',''))}</td><td>{collected}</td><td>{seeds}</td><td>{len(norms)}</td><td>{direct}</td><td>{external}</td><td class='{css}'>{html.escape(status)}</td></tr>")
manifest={'schema_version':3,'owner':'JAStos63','repository':'direitos-em-segundos-catalogo','states':states}
(DOCS/'index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
page=f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Direitos em Segundos — Catálogo Nacional V3</title><style>body{{font-family:system-ui;margin:0;background:#eef3f7;color:#142535}}main{{max-width:1200px;margin:30px auto;background:white;padding:24px;border-radius:14px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #dfe7ec;text-align:left;white-space:nowrap}}th{{background:#143d59;color:white}}.ok{{color:#146c43;font-weight:700}}.bad{{color:#b02a37;font-weight:700}}</style></head><body><main><h1>Direitos em Segundos — Catálogo Nacional V3</h1><p><b>Coletadas</b> conta apenas normas obtidas na execução atual. Sementes não servem para aprovação.</p><table><thead><tr><th>UF</th><th>Estado</th><th>Conector</th><th>Coletadas</th><th>Sementes</th><th>Total</th><th>HTML</th><th>Externos</th><th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></main></body></html>"""
(DOCS/'index.html').write_text(page,encoding='utf-8')
print(f'Índice V3 criado para {len(states)} UFs')
