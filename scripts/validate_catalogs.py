#!/usr/bin/env python3
from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'docs/index.json').read_text(encoding='utf-8'))
assert len(manifest['states'])==27
errors=[]
for s in manifest['states']:
 p=root/'docs'/s['arquivo']
 try:
  d=json.loads(p.read_text(encoding='utf-8'))
  assert d['uf']==s['uf'] and isinstance(d['normas'],list)
  ids=set()
  for n in d['normas']:
   assert n.get('id') and n.get('titulo') and n.get('url_oficial')
   if n['id'] in ids: errors.append(f"{s['uf']}: id duplicado {n['id']}")
   ids.add(n['id'])
 except Exception as e: errors.append(f"{s['uf']}: {e}")
if errors:
 print('\n'.join(errors));sys.exit(1)
print('Catálogos válidos:',len(manifest['states']))
