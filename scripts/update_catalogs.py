#!/usr/bin/env python3
"""Atualiza os 27 catálogos usando o Webservice SRU/XML do LexML.

O script preserva as sementes existentes quando a fonte externa falha. Ele foi
projetado para GitHub Actions, onde o resultado é publicado pelo GitHub Pages.
"""
from __future__ import annotations
import json, os, re, time, unicodedata
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/'docs'/'catalogos'
INDEX=ROOT/'docs'/'index.json'
SRU='https://www.lexml.gov.br/busca/SRU'
UA='DireitosEmSegundosCatalogo/1.0 (+https://github.com/JAStos63/direitos-em-segundos-catalogo)'
NS={'srw':'http://www.loc.gov/zing/srw/','dc':'http://purl.org/dc/elements/1.1/'}
PAGE=100
MAX_RECORDS_PER_STATE=int(os.environ.get('MAX_RECORDS_PER_STATE','10000'))

SERVANT_WORDS=('servidor','funcionario','funcionário','regime juridico','regime jurídico','cargo','carreira','vencimento','remuneracao','remuneração','aposentadoria','previdencia','previdência','pensao','pensão','magisterio','magistério','policial','militar')

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD',s or '') if unicodedata.category(c)!='Mn').lower()

def get(session,url,**kwargs):
    last=None
    for attempt in range(4):
        try:
            r=session.get(url,timeout=60,headers={'User-Agent':UA,'Accept':'application/xml,text/xml,text/html;q=0.8,*/*;q=0.5'},**kwargs)
            if r.status_code==200 and len(r.content)>100: return r
            last=RuntimeError(f'HTTP {r.status_code}')
        except Exception as e: last=e
        time.sleep(2**attempt)
    raise last or RuntimeError('falha de rede')

def parse_record(rec):
    data=rec.find('.//srw:recordData',NS)
    if data is None: return None
    def texts(tag): return [x.text.strip() for x in data.findall('.//dc:'+tag,NS) if x.text and x.text.strip()]
    titles=texts('title'); desc=texts('description'); ids=texts('identifier'); types=texts('type'); dates=texts('date'); subjects=texts('subject')
    if not titles: return None
    urn=next((x for x in ids if x.startswith('urn:lex:')), '')
    lexml='https://www.lexml.gov.br/urn/'+quote(urn,safe='') if urn else ''
    official=next((x for x in ids if x.startswith('https://') and ('lexml.gov.br' not in x)), '')
    if not official:
        official=next((x.replace('http://','https://',1) for x in ids if x.startswith('http://') and 'lexml.gov.br' not in x), '')
    title=titles[0]
    typ=next((x for x in types if 'Lei Complementar' in x), '') or next((x for x in types if 'Lei' in x), '') or (types[0] if types else '')
    number=''; year=''
    if urn:
        m=re.search(r':(\d{4})-\d{2}-\d{2};([^;]+)',urn)
        if m: year=m.group(1); number=m.group(2)
    text=' '.join([title]+desc+subjects)
    return {'id':urn or re.sub(r'[^a-z0-9]+','-',norm(title)).strip('-'),'titulo':title,'tipo':typ,'numero':number,'ano':year,'data':dates[0] if dates else '', 'ementa':desc[0] if desc else '', 'assuntos':subjects, 'url_oficial':official or lexml, 'url_lexml':lexml, 'texto_direto':bool(official and not official.lower().endswith('.pdf')), 'documento_externo':bool((official or '').lower().endswith('.pdf')), 'fonte_catalogo':'LexML SRU'}

def fetch_state(session,slug):
    query=f'urn any "br;{slug}:estadual" and (tipoDocumento any "Lei" or tipoDocumento any "Lei Complementar" or tipoDocumento any "Constituição")'
    out=[]; start=1; total=None
    while total is None or start<=total:
        params={'operation':'searchRetrieve','version':'1.1','query':query,'maximumRecords':PAGE,'startRecord':start,'recordSchema':'oai_dc'}
        r=get(session,SRU,params=params)
        root=ET.fromstring(r.content)
        if total is None:
            node=root.find('.//srw:numberOfRecords',NS); total=int(node.text) if node is not None and node.text else 0
            total=min(total,MAX_RECORDS_PER_STATE)
        records=root.findall('.//srw:record',NS)
        if not records: break
        for rec in records:
            item=parse_record(rec)
            if item: out.append(item)
        start += len(records)
        if len(records)<PAGE: break
        time.sleep(.5)
    dedup={x['id']:x for x in out}
    return list(dedup.values())

def main():
    manifest=json.loads(INDEX.read_text(encoding='utf-8'))
    session=requests.Session()
    changed=False
    for state in manifest['states']:
        path=ROOT/'docs'/state['arquivo']
        current=json.loads(path.read_text(encoding='utf-8'))
        try:
            normas=fetch_state(session,current['lexml_slug'])
            if normas:
                # Keep curated seeds and prefer curated official URLs.
                merged={x['id']:x for x in normas}
                for seed in current.get('normas',[]):
                    if seed.get('fonte_catalogo','').startswith(('semente','catálogo interno')):
                        merged[seed['id']]=seed
                current['normas']=sorted(merged.values(), key=lambda x:(x.get('ano',''),x.get('numero','')), reverse=True)
                current['status']='atualizado'
                current['catalog_version']=time.strftime('%Y.%m.%d')
                current['updated_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
                path.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
                state['quantidade_inicial']=len(current['normas'])
                print(current['uf'],len(current['normas']))
                changed=True
            else:
                print(current['uf'],'sem resultados; preservado')
        except Exception as e:
            print(current['uf'],'ERRO',repr(e),'— catálogo anterior preservado')
    if changed:
        manifest['catalog_version']=time.strftime('%Y.%m.%d')
        manifest['updated_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        INDEX.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': main()
