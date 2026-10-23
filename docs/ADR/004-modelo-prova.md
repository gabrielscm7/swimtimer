# ADR 004 — Nova entidade Prova entre Evento e Bateria

**Data:** 2026-10-21
**Status:** Parcialmente revogado por ADR-012

> **Revogado por ADR-012 (2026-10-23):** a prova deixa de ser cadastrada
> explicitamente e passa a ser um grupo automático de baterias. O endpoint
> legado de criação de prova 1:1 e o CRUD de prova foram removidos. A entidade
> `Prova` permanece apenas como agrupamento derivado.

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
