# Relatório da atualização V6

## Objetivo

Ampliar a atualização automática dos catálogos estaduais sem apagar o último
catálogo válido quando um portal oficial estiver indisponível.

## Alterações principais

- Fluxo renomeado para **Atualizar catálogos nacionais V6**.
- Estados sem catálogo novo geram aviso, não derrubam o fluxo inteiro.
- Coleta limitada a 30 minutos por UF, com preservação do catálogo anterior.
- SAPL passa a tentar primeiro a listagem HTML pública e usa a API como apoio.
- SAPL identifica os tipos de norma antes de percorrer as páginas.
- eLegis/AP ganhou fallback por ano quando a listagem geral responder com erro 500.
- O coletor genérico agora entende índices oficiais com links para PDFs de nomes
  opacos e aproveita o título e a ementa apresentados na própria lista.
- O coletor genérico percorre índices anuais e páginas de categorias antes de
  classificá-los como documentos individuais.
- Fontes e rotas atualizadas para CE, MA, MT, PA, PE, RN, RR e demais portais
  que mudaram de estrutura.
- A concorrência por portal foi reduzida para evitar bloqueios e sobrecarga.

## Testes realizados

- Validação sintática de todos os arquivos Python.
- Validação do JSON de configuração.
- Validação do YAML do GitHub Actions.
- 11 testes automatizados aprovados.

## Observação importante

Os testes locais confirmam o funcionamento dos parsers e das rotinas de
segurança. A quantidade real coletada por cada UF depende da resposta atual de
cada portal oficial durante a execução do GitHub Actions. O resumo final da V6
indicará quais estados atualizaram e quais preservaram o catálogo anterior.
