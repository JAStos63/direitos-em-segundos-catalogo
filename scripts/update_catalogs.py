#!/usr/bin/env python3
"""Execução sequencial para diagnóstico local ou manual.

No GitHub Actions, prefira o workflow matricial, que coleta as UFs em paralelo.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'config/states.json').read_text(encoding='utf-8'))
failed=[]
for state in config['states']:
    uf=state['uf']
    print(f'\n===== {uf} — {state["estado"]} =====', flush=True)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/collect_state.py'),'--uf',uf],cwd=ROOT)
    if result.returncode:
        failed.append(uf)
subprocess.run([sys.executable,str(ROOT/'scripts/build_index.py')],cwd=ROOT,check=True)
if failed:
    print('Falharam:',', '.join(failed),file=sys.stderr)
    raise SystemExit(1)
subprocess.run([sys.executable,str(ROOT/'scripts/validate_catalogs.py')],cwd=ROOT,check=True)
