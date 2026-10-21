# ADR 007 — Reordenação transacional e naipe na prova

**Data:** 2026-10-21
**Status:** Aceito

## Contexto

Duas questões apareceram no uso real:

1. Reordenar provas/baterias por arrastar-e-soltar falhava ao mover um item
   para baixo. O frontend enviava `PATCH` de `order_num` item a item; ao
   reatribuir a posição 1, o item movido ainda ocupava essa ordem, violando o
   índice único (`uq_prova_event_order` / `uq_heat_prova_order`) e retornando
   `400 order_num_duplicado`.
2. Gênero e categoria etária ficavam no mesmo texto livre (`prova.category`,
   ex.: "masculino, sub-12"), impedindo filtrar ou exibir naipe de forma
   estruturada.

## Decisão

### Reordenação

- Endpoints dedicados recebem a lista **completa** de IDs na nova ordem:
  - `PUT /api/events/{event_id}/provas/order`
  - `PUT /api/provas/{prova_id}/heats/order`
- A reatribuição `1..N` ocorre em **uma transação**, usando deslocamento
  temporário (`order_num + 100000`) antes de gravar a ordem final. O índice
  único nunca é violado no meio da operação.
- Validações: conjunto exato de IDs do escopo (sem duplicatas/externos) e itens
  não iniciados. Erros: `400 ordem_ids_invalidos` / `409 prova_ja_iniciada`.
- O frontend faz **uma** chamada por reordenação.

### Naipe da prova

- Nova coluna `prova.naipe` (`M`/`F`, nullable), separada de `prova.category`
  (idade, ex.: `SUB-12`).
- Migração `0006_prova_naipe` adiciona a coluna e faz backfill a partir do texto
  legado: extrai aliases (`masculino`, `masc`, `M`, `feminino`, `fem`, `F`,
  `feminina`) e remove o termo do `category`, preservando o restante em
  maiúsculas (ex.: "masculino, sub-12" → naipe `M`, categoria `SUB-12`).
- Apenas provas com termo de naipe reconhecido são reescritas; as demais
  permanecem intactas (naipe nulo).
- Na alocação de raias, atletas com naipe divergente do naipe da prova geram
  **aviso visual**, sem bloqueio, preservando casos excepcionais.

## Consequências

- Reordenação deixa de ser uma sequência de operações não atômicas; qualquer
  falha reverte tudo.
- `prova.naipe` pode ser exibido/filtrado sem parsing de texto e é compatível
  com provas antigas (nulo = "Não definido").
- A ordem de bateria continua reiniciando por prova (1..N), agora com campo
  explícito no formulário e mensagem de erro em PT-BR.
- Novas telas devem consumir `naipe` diretamente, não inferir a partir de
  `category`.
