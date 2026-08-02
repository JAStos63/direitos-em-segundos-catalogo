from pathlib import Path
import sys, json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lib.common import classify_type, extract_number_year, deduplicate, Norm
from lib.sapl import SaplConnector
from lib.elegis import ElegisConnector

class DummyClient: pass

def test_classify_types():
    assert classify_type('LEI COMPLEMENTAR nº 12')=='Lei Complementar'
    assert classify_type('Lei Ordinária nº 999')=='Lei Ordinária'
    assert classify_type('Constituição do Estado')=='Constituição Estadual'

def test_extract_number_year():
    assert extract_number_year('Lei nº 5.247/1991')==('5247','1991')

def test_elegis_listing_derives_text_integral():
    html='''<html><body><div>6244 itens encontrados.</div><table><tr><th>Tipo</th><th>Ementa</th><th>Prop</th></tr><tr><td>Lei Ordinária nº 0066, de 03/05/1993</td><td>Dispõe sobre o Regime Jurídico dos Servidores Públicos.</td><td><a href="/portal/proposicao/542">Projeto de Lei nº 7</a></td></tr></table></body></html>'''
    c=ElegisConnector(DummyClient(),'https://elegis.al.ap.leg.br')
    norms,total=c.parse_listing(html)
    assert total==6244 and len(norms)==1
    assert norms[0].url_oficial.endswith('/portal/proposicao/542/texto-integral')
    assert norms[0].texto_direto is True

def test_sapl_result_page_parses_law_and_pdf():
    html='''<html><body><h3>Pesquisa concluída com sucesso! Foram encontradas 3903 normas.</h3><div class="list-group-item"><a href="/norma/34?display=">LEI COMPLEMENTAR nº 12, de 20 de julho de 1992</a><div>Ementa: DISCIPLINA A DISPONIBILIDADE REMUNERADA DE SERVIDORES.</div><a href="/media/sapl/public/normajuridica/1992/34/34_texto_integral.pdf">Texto Original</a></div></body></html>'''
    c=SaplConnector(DummyClient(),'https://sapl.al.al.leg.br','AL')
    norms,total=c.parse_results(html,'https://sapl.al.al.leg.br/norma/pesquisar?page=1')
    assert total==3903 and len(norms)==1
    assert norms[0].numero=='12' and norms[0].ano=='1992'
    assert norms[0].documento_externo is True
    assert 'DISPONIBILIDADE' in norms[0].ementa

def test_sapl_api_item():
    c=SaplConnector(DummyClient(),'https://sapl.exemplo.leg.br','XX')
    item={'id':55,'tipo':1,'numero':'5247','ano':1991,'data':'26/07/1991','ementa':'Regime jurídico.','indexacao':'SERVIDOR; FÉRIAS','texto_integral':'/media/lei.pdf'}
    n=c._api_item_to_norm(item,{'1':'Lei Ordinária'})
    assert n and n.numero=='5247' and n.documento_externo

def test_dedup_prefers_html():
    a=Norm(id='a',titulo='Lei nº 1/2020',tipo='Lei Ordinária',numero='1',ano='2020',url_oficial='https://x/1.pdf',documento_externo=True)
    b=Norm(id='b',titulo='Lei nº 1/2020',tipo='Lei Ordinária',numero='1',ano='2020',url_oficial='https://x/1.html',texto_direto=True,ementa='rico')
    r=deduplicate([a,b]); assert len(r)==1 and r[0].texto_direto

def test_config_v3_has_27_and_elegis():
    cfg=json.loads((ROOT/'config/states.json').read_text(encoding='utf-8'))
    assert cfg['schema_version']==3 and len(cfg['states'])==27
    assert next(s for s in cfg['states'] if s['uf']=='AP')['strategy']=='elegis'
    for s in cfg['states']:
        assert s['strategy'] in {'sapl','generic','elegis'}
        assert s['minimum_collected']>0
