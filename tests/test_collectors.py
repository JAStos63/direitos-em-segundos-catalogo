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

def test_config_has_27_and_elegis():
    cfg=json.loads((ROOT/'config/states.json').read_text(encoding='utf-8'))
    assert cfg['schema_version']==3 and len(cfg['states'])==27
    assert next(s for s in cfg['states'] if s['uf']=='AP')['strategy']=='elegis'
    for s in cfg['states']:
        assert s['strategy'] in {'sapl','generic','elegis'}
        assert s['minimum_collected']>0

from lib.generic import GenericPortalConnector


class DummyResponse:
    def __init__(self, text='', url='https://example.invalid/', content_type='text/html'):
        self.text = text
        self.url = url
        self.content = text.encode('utf-8')
        self.headers = {'content-type': content_type}


class MapClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        key = url
        if kwargs.get('params'):
            params = kwargs['params']
            key = (url, tuple(sorted((str(k), str(v)) for k, v in params.items())))
        value = self.pages[key]
        if isinstance(value, Exception):
            raise value
        return value


def test_generic_index_accepts_opaque_pdf_without_downloading_it():
    index = '''<html><body><ul><li><a href="/storage/a8f19.pdf">Lei Complementar nº 799 de 08.12.2025</a><p>Institui a Lei Orgânica da Administração Tributária.</p></li></ul></body></html>'''
    client = MapClient({'https://www.al.rn.leg.br/legislacao/leis-complementares': DummyResponse(index, 'https://www.al.rn.leg.br/legislacao/leis-complementares')})
    connector = GenericPortalConnector(
        client=client, uf='RN', portal='https://www.al.rn.leg.br/legislacao',
        allowed_hosts=['www.al.rn.leg.br'],
        start_urls=['https://www.al.rn.leg.br/legislacao/leis-complementares'],
        detail_patterns=[r'/storage/'], listing_patterns=[], cc_queries=[], max_workers=1,
    )
    connector._discover_sitemaps = lambda max_urls: set()
    connector._discover_commoncrawl = lambda max_urls: set()
    norms = connector.collect(max_records=20, max_listing_pages=5)
    assert len(norms) == 1
    assert norms[0].numero == '799'
    assert norms[0].documento_externo is True
    assert len(client.calls) == 1  # somente a página de índice


def test_generic_follows_year_index_before_treating_it_as_detail():
    root = '''<html><body><a href="/legislativo/legislacao5/leis2026/LEIS2026.htm">2026</a></body></html>'''
    year = '''<html><body><table><tr><td><a href="lei19855.htm">LEI N.º 19.855, DE 27.07.2026</a></td><td>Denomina equipamento público.</td></tr></table></body></html>'''
    pages = {
        'https://www2.al.ce.gov.br/legislativo/lei_ordinaria.htm': DummyResponse(root, 'https://www2.al.ce.gov.br/legislativo/lei_ordinaria.htm'),
        'https://www2.al.ce.gov.br/legislativo/legislacao5/leis2026/LEIS2026.htm': DummyResponse(year, 'https://www2.al.ce.gov.br/legislativo/legislacao5/leis2026/LEIS2026.htm'),
    }
    client = MapClient(pages)
    connector = GenericPortalConnector(
        client=client, uf='CE', portal='https://www2.al.ce.gov.br/legislativo/lei_ordinaria.htm',
        allowed_hosts=['www2.al.ce.gov.br'],
        start_urls=['https://www2.al.ce.gov.br/legislativo/lei_ordinaria.htm'],
        detail_patterns=[r'/legislativo/legislacao5/leis\d{4}/'],
        listing_patterns=[r'/legislativo/legislacao5/leis\d{4}/LEIS\d{4}\.htm'],
        cc_queries=[], max_workers=1,
    )
    connector._discover_sitemaps = lambda max_urls: set()
    connector._discover_commoncrawl = lambda max_urls: set()
    norms = connector.collect(max_records=20, max_listing_pages=5)
    assert len(norms) == 1
    assert norms[0].numero == '19855'
    assert norms[0].texto_direto is True


def test_sapl_discovers_only_law_type_ids():
    html = '''<select name="tipo"><option value="1">Lei Ordinária</option><option value="2">Decreto</option><option value="3">Lei Complementar</option></select>'''
    client = MapClient({'https://sapl.exemplo.leg.br/norma/pesquisar': DummyResponse(html)})
    connector = SaplConnector(client, 'https://sapl.exemplo.leg.br', 'XX')
    assert connector._discover_target_type_ids() == ['1', '3']


def test_elegis_falls_back_to_year_when_general_listing_fails():
    good = '''<html><body><div>1 item encontrado.</div><table><tr><td>Lei Ordinária nº 3514, de 08/07/2026</td><td>Declara patrimônio cultural.</td><td><a href="/portal/proposicao/8692">Projeto</a></td></tr></table></body></html>'''
    pages = {
        ('https://elegis.al.ap.leg.br/portal/legislacao', (('page', '1'),)): RuntimeError('500'),
        ('https://elegis.al.ap.leg.br/portal/legislacao', (('ano', '2026'), ('page', '1'))): DummyResponse(good, 'https://elegis.al.ap.leg.br/portal/legislacao?ano=2026&page=1'),
        ('https://elegis.al.ap.leg.br/portal/legislacao', (('ano', '2025'), ('page', '1'))): DummyResponse('<html></html>', 'https://elegis.al.ap.leg.br/portal/legislacao?ano=2025&page=1'),
        ('https://elegis.al.ap.leg.br/portal/legislacao', (('ano', '2025'), ('page', '2'))): DummyResponse('<html></html>', 'https://elegis.al.ap.leg.br/portal/legislacao?ano=2025&page=2'),
    }
    client = MapClient(pages)
    connector = ElegisConnector(client, 'https://elegis.al.ap.leg.br')
    # limita o teste a 2026/2025 sem depender do ano corrente dentro do método
    original = connector._collect_query
    calls = {'n': 0}
    def limited(**kwargs):
        calls['n'] += 1
        if calls['n'] > 3:
            return None
        return original(**kwargs)
    connector._collect_query = limited
    norms = connector.collect(max_records=1, max_pages=2)
    assert len(norms) == 1
    assert norms[0].numero == '3514'
