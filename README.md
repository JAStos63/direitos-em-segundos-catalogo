# Direitos em Segundos — Catálogo Nacional V2

Este repositório publica, em GitHub Pages, os catálogos estaduais usados pelo aplicativo Android **Direitos em Segundos**.

## Mudança principal da V2

A versão anterior dependia quase exclusivamente do Webservice SRU do LexML e considerava a execução concluída mesmo quando vários Estados permaneciam vazios.

A V2 utiliza três camadas de coleta:

1. **OpenAPI/HTML do SAPL**, para Assembleias que usam o Sistema de Apoio ao Processo Legislativo;
2. **sitemaps e páginas de listagem dos portais oficiais**;
3. **índice público do Common Crawl apenas para descobrir endereços já publicados nos domínios oficiais**. O conteúdo jurídico sempre é baixado e validado no próprio portal governamental ou legislativo.

O fluxo é executado em paralelo para as 27 unidades federativas. A publicação só é gravada no repositório quando **todos os catálogos atingem o mínimo configurado**.

## Arquivos que devem ficar na raiz do repositório

```text
.github/
config/
docs/
scripts/
tests/
README.md
requirements.txt
```

## Como atualizar no GitHub

1. Extraia o pacote.
2. No repositório `JAStos63/direitos-em-segundos-catalogo`, envie o conteúdo extraído para a raiz.
3. Aceite a substituição dos arquivos existentes.
4. Na aba **Actions**, abra **Atualizar catálogos nacionais V2**.
5. Clique em **Run workflow**.

A coleta é dividida por Estado. Se uma unidade federativa ficar vazia ou abaixo do mínimo, a execução ficará vermelha e o catálogo anterior não será publicado como se estivesse completo.

## Relatórios

Depois da execução, cada UF gera:

```text
docs/relatorios/AL.json
docs/relatorios/SP.json
...
```

A página inicial do GitHub Pages mostra a quantidade de normas, documentos HTML pesquisáveis e documentos externos de cada Estado.

## Testes locais

```bash
pip install -r requirements.txt
pytest -q
```

## Observação jurídica

O catálogo é uma ferramenta de localização. A conferência final deve ser feita no texto disponibilizado pelo órgão oficial e no Diário Oficial correspondente.
