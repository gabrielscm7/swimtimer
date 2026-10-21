# ADR 004 — Nova entidade Prova entre Evento e Bateria

**Data:** 2026-10-21
**Status:** Aceito

## Contexto
O modelo anterior usava `Heat` para representar tanto a prova quanto a
bateria. Não era possível consolidar atletas de várias baterias da mesma prova
nem configurar classificação por prova.

## Decisão
Criar a entidade persistente `Prova` (`prova`) abaixo de `Event` e acima de
`Heat` (bateria). `Heat` mantém `event_id` para compatibilidade/consultas, mas
ganha `prova_id` obrigatório. Nomes em português (`Prova`) foram escolhidos por
aderência ao domínio do produto.

Migração: uma prova por bateria legada, preservando ordem e dados; não agrupar
automaticamente por nome/distância. Defaults: `consolidate_results=true` e
`classification_criterion=lowest_time`.

## Consequências
- Classificação consolidada possível por prova, com configuração persistente.
- Endpoints antigos de bateria continuam funcionando; o endpoint legado de
  criação cria uma prova 1:1 ("wrapper").
- `admin.html` ficou redundante e foi descontinuado em favor de `gestao.html`.
