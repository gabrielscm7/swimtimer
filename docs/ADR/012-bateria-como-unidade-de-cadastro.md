# ADR 012 — Bateria como unidade de cadastro e prova como grupo automático

**Data:** 2026-10-23
**Status:** Aceito
**Revoga parcialmente:** ADR-004 (cadastro explícito de prova), ADR-007
(reordenação por prova e naipe/categoria na prova) e ADR-011 (definição
obrigatória da prova, `name_override`, `mixed_ranking`, `legacy_incomplete` e
herança prova → bateria).

## Contexto

A hierarquia `Evento → Prova → Bateria` exigia cadastrar a prova antes da
bateria. Na operação real a unidade que o organizador cria é a **bateria**; a
prova é apenas o grupo de baterias que compartilham modalidade, naipe e
categoria. Cadastrar a prova separadamente gerava duplicidade, baterias
incoerentes com a prova e uma ordem de programa engessada por prova.

Também era necessário permitir **ordem livre no evento**: o programa pode
intercalar grupos (A1, B1, A2, B2) sem que a classificação da prova se perca.

## Decisão

### 1. Unidade de cadastro

- Só existem CRUD de **bateria**. A prova deixa de ser cadastrada e passa a ser
  um **grupo derivado**, criado/removido automaticamente pelo backend.
- `heat` (bateria) passa a carregar `stroke`, `naipe`, `category`, `lane_count`
  e `classify_alone`, além de `heat_type`, `distance_m` e `duration_s`.
- `prova` mantém apenas a identidade do grupo: `name` (sempre gerado),
  `order_num` (derivado), `format`, `stroke`, `distance_m`, `naipe`,
  `category`, `classification_criterion`, `status` e `created_at`.

### 2. Estilos, naipes e categorias (listas fechadas)

- **Estilo:** `crawl`, `borboleta`, `peito`, `costas`, `livre`, `medley`.
  Crawl e Livre são estilos **distintos**.
- **Naipe:** `M`, `F`, `MISTO` (atletas continuam apenas `M`/`F`).
- **Categoria:** `pre_mirim`, `mirim`, `petiz`, `infantil`, `juvenil`,
  `junior`, `adulto`, `livre` — constante única compartilhada entre backend
  (`app/domain.py`) e frontend (`labels.js`), verificada por teste.
- Na interface, `livre` é exibida como **"Cat. Livre"**.
- A migration `0015` converte valores legados fora da lista (inclusive
  `ABERTA`) para `livre`, em provas e atletas. Datos nulos de legado permanecem
  nulos e são sinalizados na gestão (mesmo padrão de aviso).

### 3. Grupo (prova)

Chave do grupo: `(heat_type, stroke, distance_m [só heat_type="bateria"],
naipe, category)`.

- Baterias do mesmo grupo somam automaticamente na classificação da prova.
- O checkbox **"Classificar isolada"** (`heat.classify_alone=true`) coloca a
  bateria em um grupo próprio (prova exclusiva daquela bateria), sem mudar o
  nome gerado; a UI mostra o selo "Isolada".
- Nome da prova é **sempre gerado**: `"25 m Crawl · Masculino · Mirim"`.
  - Categoria `livre` é omitida do nome.
  - Maratonas: `"Maratona 2 h · Misto · Mirim"`.
- Invariante: uma prova **nunca** contém baterias de grupos diferentes.
- Prova sem baterias e sem `result_snapshot` é removida automaticamente.
- Editar atributos de uma bateria pode movê-la de grupo: recalcula a
  classificação dos dois grupos e transmite `prova_state` de ambos.

### 4. Ordem livre no evento

- `heat.order_num` passa a ser **único por evento** (`uq_heat_event_order`),
  substituindo `uq_heat_prova_order`.
- `event_seq = order_num` (ordem global canônica).
- `heat_index_in_prova` = posição da bateria entre as do mesmo grupo na ordem
  do evento.
- `PATCH /api/events/{id}/heats/order` recebe a lista **completa** de ids ou
  `{heat_id, position}` ("numerar"), executado atomicamente sob o lock do
  evento.
- Só baterias `scheduled` podem mudar de posição; as demais ficam **ancoradas**
  (`409 bateria_ancorada`).
- A ordem das provas exibida ("PROVA N") é derivada da menor `order_num` entre
  as baterias do grupo e renumerada 1..N.

### 5. Elegibilidade

- Naipe do atleta = naipe da bateria, ou bateria `MISTO`.
- Categoria do atleta = categoria da bateria, ou bateria `livre`.
- Atleta não pode estar em outra bateria do **mesmo grupo**.
- `GET /api/heats/{id}/eligible-athletes?team_id=` devolve apenas atletas
  elegíveis da equipe, marcando os já alocados no grupo.
- As demais validações de inscrição do ADR-009 são mantidas, agora derivadas
  da bateria; a exceção continua usando `force` + `X-Operator-Pin` + motivo.

### 6. Bloqueio pós-resultado

- Bateria `finished` não altera `stroke`, `distance_m`, `naipe` nem `category`
  sem exceção do supervisor: `409 bateria_com_resultado`, salvo com
  `force + override_reason + X-Operator-Pin`.
- A exceção registra `action_log` e snapshot com status `corrected`.
- Ordem de bateria com resultado é imutável (ancorada); o nome continua
  editável.

### 7. Raias

- `heat.lane_count` (1–8) limita `lane_number <= lane_count`.
- `Event.default_lane_count` (1–8, padrão 3) define o valor herdado na criação
  de baterias e é editável nas configurações do evento.
- A migration ajusta `lane_count` pela maior raia existente (clamp 1–8,
  fallback 3).

### 8. Resultados em dois níveis

- Mantém-se "RESULTADO DA PROVA" (consolidado, violeta) e "RESULTADO DA
  BATERIA" (ciano), com as cores de nível `lvl_prova`/`lvl_bateria`.
- Prova `MISTO` **sempre** exibe classificação geral + por naipe; a
  configuração `mixed_ranking` é removida.

## Consequências

- O programa do evento é uma lista única de baterias, ordenável livremente.
- A prova deixa de ter CRUD; endpoints de cadastro/reordenação de prova são
  removidos. Permanecem apenas leituras derivadas (`GET` de prova, summary,
  classification e heats da prova).
- `POST /api/provas/{id}/heats`, `PUT /api/provas/{id}/heats/order` e
  `PUT /api/events/{id}/provas/order` são substituídos por
  `POST /api/events/{id}/heats` e `PATCH /api/events/{id}/heats/order`.
- Testes de migration cobrem a conversão com dados legados e o downgrade
  (conversão de categoria é lossy: valores antigos viram `livre`, e o
  downgrade os representa como `ABERTA`).
- Frontend passa a ter uma única tela "Baterias"; `gestao/provas.js` é
  removido.
