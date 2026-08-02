from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

from lib.common import classify_type, extract_number_year, deduplicate, Norm
from lib.sapl import SaplConnector


class DummyClient:
    pass


def test_classify_types():
    assert classify_type('LEI COMPLEMENTAR nº 12') == 'Lei Complementar'
    assert classify_type('Lei Ordinária nº 999') == 'Lei Ordinária'
    assert classify_type('Constituição do Estado') == 'Constituição Estadual'
    assert classify_type('Emenda Constitucional nº 4') == 'Emenda Constitucional'


def test_extract_number_year():
    assert extract_number_year('Lei nº 5.247/1991') == ('5247','1991')
    number,year=extract_number_year('LEI COMPLEMENTAR nº 266, de 20 de setembro de 2022')
    assert number=='266' and year=='2022'


def test_sapl_api_item():
    connector=SaplConnector(DummyClient(),'https://sapl.exemplo.leg.br','XX')
    item={
        'id': 55,
        'tipo': 1,
        'numero': '5247',
        'ano': 1991,
        'data': '26/07/1991',
        'ementa': 'Institui o regime jurídico único dos servidores públicos.',
        'indexacao': 'SERVIDOR; FÉRIAS',
        'texto_integral': '/media/sapl/public/normajuridica/1991/55/lei.pdf'
    }
    norm=connector._api_item_to_norm(item,{'1':'Lei Ordinária'})
    assert norm is not None
    assert norm.tipo=='Lei Ordinária'
    assert norm.numero=='5247'
    assert norm.ano=='1991'
    assert norm.url_oficial.startswith('https://sapl.exemplo.leg.br/media/')
    assert norm.documento_externo is True
    assert 'FÉRIAS' in norm.assuntos


def test_dedup_prefers_html():
    a=Norm(id='a',titulo='Lei nº 1/2020',tipo='Lei Ordinária',numero='1',ano='2020',url_oficial='https://x/1.pdf',documento_externo=True)
    b=Norm(id='b',titulo='Lei nº 1/2020',tipo='Lei Ordinária',numero='1',ano='2020',url_oficial='https://x/1.html',texto_direto=True,ementa='texto rico')
    result=deduplicate([a,b])
    assert len(result)==1
    assert result[0].url_oficial.endswith('.html')


def test_state_configuration_has_27_ufs():
    import json
    config=json.loads((ROOT/'config/states.json').read_text(encoding='utf-8'))
    assert len(config['states'])==27
    assert len({s['uf'] for s in config['states']})==27
    for state in config['states']:
        assert state['strategy'] in {'sapl','generic'}
        assert state.get('portal')
        assert state.get('minimum_records',0)>0
        if state['strategy']=='sapl':
            assert state.get('base_url')
        else:
            assert state.get('allowed_hosts')
            assert state.get('detail_patterns')
            assert state.get('cc_queries')
