# Relatório de testes — Catálogo Nacional V3

Data: 02/08/2026

## Correções implementadas

- Novo conector `elegis.py` para a listagem pública da Assembleia Legislativa do Amapá.
- Derivação do texto integral pela rota `/portal/proposicao/<id>/texto-integral`.
- Reescrita do conector SAPL para usar a listagem pública de resultados, com API como alternativa.
- Inclusão do parâmetro `iframe=-1`, exigido por algumas instalações SAPL para apresentar os resultados.
- Leitura direta de título, ementa, detalhe e vínculo “Texto Original” na página de resultados do SAPL.
- Separação entre `collected_count` e `seed_count`.
- Normas-semente não contam para o mínimo exigido.
- Workflow renomeado para **Atualizar catálogos nacionais V3**.
- Consolidação bloqueada quando uma UF não atinge o mínimo com normas realmente coletadas.

## Testes locais executados

- Classificação de tipos de norma.
- Extração de número e ano.
- Parsing da listagem eLegis.
- Formação da URL de texto integral do eLegis.
- Parsing da página de resultados SAPL.
- Identificação do PDF “Texto Original”.
- Conversão de item da API SAPL.
- Desduplicação com preferência por HTML pesquisável.
- Configuração das 27 unidades federativas.
- Compilação sintática de todos os módulos Python.

Resultado: **7 testes aprovados**.

## Limitação do ambiente

A execução real contra os portais estaduais não foi feita neste ambiente, pois ele não possui acesso de rede externa. A validação ao vivo deve ser realizada pelo GitHub Actions. O V3 corrige especificamente os dois problemas já demonstrados nos logs: eLegis do Amapá e páginas de resultado SAPL. Os portais estaduais de outras famílias continuarão sendo identificados individualmente pelo workflow caso ainda necessitem de conector próprio.
