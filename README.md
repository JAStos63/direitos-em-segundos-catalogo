# Direitos em Segundos — Catálogo Nacional V3

Versão V3 do coletor nacional de legislação estadual.

## Mudanças principais

- conector próprio para o eLegis do Amapá;
- coletor SAPL baseado na página pública de resultados, com API como alternativa;
- `iframe=-1` e consultas compatíveis com diferentes instalações SAPL;
- normas-semente não contam para atingir o mínimo;
- relatório separa `collected_count` e `seed_count`;
- o GitHub Pages só é publicado se as 27 unidades federativas forem validadas.

## Instalação

Envie o conteúdo desta pasta para a raiz do repositório `JAStos63/direitos-em-segundos-catalogo`, substituindo os arquivos existentes. Mantenha o GitHub Pages em `main /docs`. Depois execute **Atualizar catálogos nacionais V3**.

## Interpretação do resultado

- verde: a UF coletou normas reais acima do mínimo;
- vermelho: o portal daquela UF exige um conector adicional ou mudou sua estrutura;
- a etapa `consolidar` não publica uma base parcial.

Esta versão corrige especificamente as duas famílias já diagnosticadas: **eLegis** e **SAPL**. Os conectores genéricos dos demais portais continuam sendo validados pelo próprio workflow; falhas remanescentes aparecerão por UF, sem falso sucesso.

## Atualização V6

A V6 amplia a coleta nacional com: índices oficiais estáticos (CE, RN e PE),
portais atuais de MA e MT, fallback anual para o eLegis/AP, descoberta por
HTML antes da API nos SAPL e preservação automática do catálogo anterior
quando um portal estiver temporariamente indisponível.
