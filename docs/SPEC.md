# SPEC — SwimTimer v2.6
**Versão:** 2.6
**Data:** 2026-10-23
**Status:** Implementado

---

## 1. Visão Geral da Arquitetura

```
┌─────────────────────────────────────────────────────┐
│                  NOTEBOOK (servidor)                │
│                                                     │
│  ┌──────────────┐     ┌──────────────────────────┐ │
│  │   FastAPI    │     │       SQLite             │ │
│  │   Backend    │────▶│    swimtimer.db          │ │
│  │              │     └──────────────────────────┘ │
│  │  HTTP REST   │                                   │
│  │  WebSocket   │                                   │
│  └──────┬───────┘                                   │
│         │ serve static                              │
│  ┌──────▼───────┐                                   │
│  │ HTML/CSS/JS  │  (frontend estático)              │
│  └──────────────┘                                   │
│                                                     │
│  Hotspot Wi-Fi: 10.42.0.1:8080                     │
└─────────────────────────────────────────────────────┘
         │ WebSocket + HTTP
         ▼
┌─────────────────────────────────────────────────────┐
│              REDE LOCAL (hotspot)                   │
│                                                     │
│  📱 Fiscal 1    📱 Fiscal 2  ...  📱 Fiscal 8      │
│  📺 Dashboard (telão via HDMI)                      │
└─────────────────────────────────────────────────────┘
```

---

## 2. Stack Técnica

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Backend | FastAPI (Python 3.11) | Async nativo, WebSocket built-in, tipagem, docs automáticas |
| Banco | SQLite via SQLAlchemy | Zero configuração, arquivo único, suficiente para escala local |
| Frontend | HTML + Vanilla JS | Sem build step, sem dependências, carrega instantaneamente em celular |
| Comunicação | WebSocket (push) | Elimina polling, latência < 100ms, resiliente a perda de pacote |
| Infra local | Docker Compose | Ambiente reproduzível, `./start.sh` único comando |
| OS | Ubuntu 22.04 LTS | Hotspot sem internet nativo, suporte longo prazo |

> **Decisão:** Frontend em Vanilla JS no v1.0. React entra no v2.0, quando a complexidade de componentes (multi-evento, admin) justificar o build step.

---

## 3. Modelos de Dados (v2.2)

### 3.1 Diagrama

```
Event
  id, name, location, date (ISO YYYY-MM-DD, obrigatório em novos eventos)
  pool_length_m (25|50), default_lane_count (1–8, padrão 3)
  status (draft|active|finished), created_at

Prova (grupo derivado; NÃO é cadastrada)
  id, event_id, name (sempre gerado), order_num (derivado)
  format (bateria|maratona), stroke (crawl|borboleta|peito|costas|livre|medley)
  distance_m, naipe (M|F|MISTO)
  category (pre_mirim|mirim|petiz|infantil|juvenil|junior|adulto|livre)
  classification_criterion (lowest_time)
  status (scheduled|in_progress|finished), created_at

Team
  id, event_id, name, logo_url

Athlete
  id, event_id, team_id (opcional), name, naipe (M|F), category
  created_at, updated_at

Heat (bateria — unidade de cadastro)
  id, event_id, prova_id (grupo automático), name, order_num (único por evento)
  heat_type (maratona|bateria), stroke, naipe, category
  distance_m, duration_s, lane_count (1–8), classify_alone
  status (scheduled|ready_check|active|finished)
  started_at, finished_at

HeatLane
  id, heat_id, lane_number (1–8), participant_name, athlete_id, team_id
  status (assigned|ready|active|finished|dq)
  finish_at (tempo do toque), race_time_ms, received_at, late

LapEvent
  id, lane_id, lap_number, recorded_at (tempo efetivo do toque),
  received_at, late, is_undo

ActionLog
  id, received_at, effective_ts, event_id, heat_id, lane_id, action,
  op_id, source_ip, payload_json

ProcessedOp
  op_id (PK), lane_id, action, result_json, created_at
```

> Hierarquia: **Evento → Bateria → Raia/Atleta → Resultado**. A `Prova` é um
> grupo automático de baterias com a mesma chave
> `(heat_type, stroke, distance_m [só bateria de tempo], naipe, category)`.
> `classify_alone=true` cria um grupo exclusivo. A prova é criada, renumerada e
> removida pelo backend; não há CRUD de prova.
>
> `Athlete` é o cadastro único do atleta dentro do evento. `HeatLane.atleta_id`
> é opcional: quando presente, nome e equipe exibidos na raia são derivados do
> atleta (e mantidos em sincronia em `participant_name`/`team_id` para os
> clientes legados). Raias antigas sem atleta continuam válidas via
> `participant_name` livre.
>
> **Ordens:** `heat.order_num` é único no **evento** (`uq_heat_event_order`) e
> representa a ordem livre do programa. `event_seq = order_num`;
> `heat_index_in_prova` é a posição entre as baterias do mesmo grupo nessa
> ordem. `prova.order_num` é derivado (menor `order_num` do grupo) e renumerado
> 1..N. Reordenação usa `PATCH /api/events/{id}/heats/order` (lista completa ou
> `{heat_id, position}`) em uma transação sob o lock do evento. Só baterias
> `scheduled` mudam de posição; as demais ficam ancoradas (`409 bateria_ancorada`).
>
> **Naipe e categoria:** `heat.naipe` (`M`/`F`/`MISTO`) e `heat.category`
> (lista fechada; `livre` = sem restrição etária, exibida como "Cat. Livre").
> Elegibilidade: naipe do atleta = bateria (ou `MISTO`); categoria do atleta =
> bateria (ou bateria `livre`); atleta não pode repetir no mesmo grupo.
> `GET /api/heats/{id}/eligible-athletes?team_id=` filtra a equipe e marca os
> já alocados no grupo.
>
> **Grupo e nome (v2.7):** a prova espelha `heat_type/stroke/distance_m/naipe/
> category` da bateria. O nome é sempre gerado (`25 m Crawl · Masculino ·
> Mirim`); `livre` é omitida e maratonas usam `Maratona 2 h · …`. Prova sem
> baterias e sem snapshots é removida. `MISTO` sempre exibe geral + por naipe.
>
> **Legado:** a migração `0015` copia atributos da prova para cada bateria,
> converte categorias fora da lista para `livre` (inclusive `ABERTA`), renumera
> `order_num` global e ajusta `lane_count` pelas raias existentes. Campos nulos
> antigos são sinalizados como `legacy_incomplete` na gestão.
>
> **Bloqueio pós-resultado:** bateria `finished` não altera estilo, distância,
> naipe nem categoria (`409 bateria_com_resultado`), salvo `force=true` +
> `override_reason` + `X-Operator-Pin`, que registra `override_grupo` e snapshot
> `corrected` (`reason=correcao_grupo`).

### 3.2 Tabelas SQL

```sql
CREATE TABLE event (
    id             TEXT PRIMARY KEY,  -- UUID
    name           TEXT NOT NULL,
    location       TEXT,
    date           TEXT,              -- ISO date string
    pool_length_m  INTEGER NOT NULL,  -- 25 ou 50
    default_lane_count INTEGER NOT NULL DEFAULT 3,  -- 1..8
    status         TEXT DEFAULT 'draft',  -- draft|active|finished
    created_at     REAL NOT NULL
);

CREATE TABLE team (
    id        TEXT PRIMARY KEY,
    event_id  TEXT NOT NULL REFERENCES event(id),
    name      TEXT NOT NULL,
    logo_url  TEXT
);

CREATE TABLE athlete (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL REFERENCES event(id),
    team_id     TEXT REFERENCES team(id),
    name        TEXT NOT NULL,
    naipe       TEXT NOT NULL,        -- M|F
    category    TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL
);
-- Unicidade por evento + nome (case-insensitive) + equipe (vazio se nula):
CREATE UNIQUE INDEX uq_athlete_event_name_team
    ON athlete (event_id, name COLLATE NOCASE, COALESCE(team_id, ''));

CREATE TABLE prova (
    id                        TEXT PRIMARY KEY,
    event_id                  TEXT NOT NULL REFERENCES event(id),
    name                      TEXT NOT NULL,       -- sempre gerado
    order_num                 INTEGER NOT NULL,    -- derivado, renumerado 1..N
    format                    TEXT NOT NULL DEFAULT 'bateria',
    stroke                    TEXT,                -- espelha o grupo
    distance_m                INTEGER,
    naipe                     TEXT,
    category                  TEXT,
    classification_criterion  TEXT NOT NULL DEFAULT 'lowest_time',
    status                    TEXT NOT NULL DEFAULT 'scheduled',
    created_at                REAL NOT NULL,
    UNIQUE (event_id, order_num)
);

CREATE TABLE heat (
    id             TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL REFERENCES event(id),
    prova_id       TEXT NOT NULL REFERENCES prova(id),
    name           TEXT NOT NULL DEFAULT '',
    order_num      INTEGER NOT NULL,
    heat_type      TEXT NOT NULL,   -- maratona|bateria
    stroke         TEXT,            -- crawl|borboleta|peito|costas|livre|medley
    naipe          TEXT,            -- M|F|MISTO
    category       TEXT,            -- lista fechada; livre = sem restricao
    classify_alone BOOLEAN NOT NULL DEFAULT 0,
    lane_count     INTEGER NOT NULL DEFAULT 3,
    distance_m     INTEGER,         -- bateria
    duration_s     INTEGER,         -- maratona
    status         TEXT DEFAULT 'scheduled',
    started_at     REAL,
    finished_at    REAL,
    UNIQUE (event_id, order_num)
);

CREATE TABLE heat_lane (
    id               TEXT PRIMARY KEY,
    heat_id          TEXT NOT NULL REFERENCES heat(id),
    lane_number      INTEGER NOT NULL,  -- 1 a 8
    participant_name TEXT,
    athlete_id       TEXT REFERENCES athlete(id),
    team_id          TEXT REFERENCES team(id),
    status           TEXT DEFAULT 'assigned',
    finish_at        REAL,             -- tempo efetivo do toque
    race_time_ms     INTEGER,          -- quantizado em 10 ms
    received_at      REAL,             -- instante de recebimento no servidor
    late             BOOLEAN NOT NULL DEFAULT 0,  -- now - effective_ts > 2 s
    UNIQUE (heat_id, lane_number)
);

CREATE TABLE lap_event (
    id          TEXT PRIMARY KEY,
    lane_id     TEXT NOT NULL REFERENCES heat_lane(id),
    lap_number  INTEGER NOT NULL,
    recorded_at REAL NOT NULL,  -- tempo efetivo do toque (clamped)
    is_undo     BOOLEAN DEFAULT FALSE,
    received_at REAL,           -- instante de recebimento no servidor
    late        BOOLEAN NOT NULL DEFAULT 0
);

-- Toda ação que muda estado grava uma linha.
CREATE TABLE action_log (
    id           TEXT PRIMARY KEY,
    received_at  REAL NOT NULL,
    effective_ts REAL NOT NULL,
    event_id     TEXT,
    heat_id      TEXT,
    lane_id      TEXT,
    action       TEXT NOT NULL,  -- start|abort|finish_heat|finish|lap|dq|undo_lap
    op_id        TEXT,
    source_ip    TEXT,
    payload_json TEXT
);

-- Resultado original de um op_id (reenvios idempotentes).
CREATE TABLE processed_op (
    op_id       TEXT PRIMARY KEY,
    lane_id     TEXT,
    action      TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE INDEX ix_heat_event_order ON heat(event_id, order_num);
CREATE INDEX ix_lap_event_lane_recorded ON lap_event(lane_id, recorded_at);
CREATE INDEX ix_action_log_heat_received ON action_log(heat_id, received_at);
```

---

## 4. API REST

### Eventos
```
GET    /api/events[?limit=&offset=]   → lista (paginável, com heats)
POST   /api/events                    → criar evento
GET    /api/events/{event_id}         → detalhe + heats + teams
PATCH  /api/events/{event_id}         → atualizar
DELETE /api/events/{event_id}         → deletar (só se draft)
```

### Atletas
```
POST   /api/events/{event_id}/athletes                  → criar atleta
GET    /api/events/{event_id}/athletes                  → listar/paginar
         ?q=&team_id=&naipe=&category=&limit=&offset=
GET    /api/athletes/{athlete_id}                       → detalhe
PATCH  /api/athletes/{athlete_id}                       → editar
DELETE /api/athletes/{athlete_id}                       → deletar (409 se em raia)
POST   /api/events/{event_id}/athletes/import           → importar CSV/XLSX
GET    /api/events/{event_id}/athletes/import-template  → modelo (?format=csv|xlsx)
GET    /api/events/{event_id}/athletes/export           → exportar CSV
```

Regras de importação:
- Colunas obrigatórias: `NOME, EQUIPE, NAIPE, CATEGORIA` (cabeçalho detectado
  nas 20 primeiras linhas; vírgula, ponto e vírgula ou tab).
- `NAIPE` aceita `M`/`F` e aliases (`Masculino`, `Feminino`, `masc`, `fem`).
- Equipes inexistentes são criadas automaticamente (comparação case-insensitive).
- Política **parcial**: linhas válidas são gravadas em uma transação; linhas
  inválidas retornam `{line, field, message}` e não são gravadas.
- Limites: 2 MB por arquivo e 1000 linhas; validação de extensão + magic bytes
  (XLSX) e decodificação UTF-8/UTF-8-BOM/Latin-1 (CSV).

### Provas (grupo derivado, somente leitura)
```
GET    /api/events/{event_id}/provas         → listar grupos (com baterias)
GET    /api/provas/{prova_id}                → detalhe derivado
GET    /api/provas/{prova_id}/heats          → baterias do grupo
GET    /api/provas/{prova_id}/classification → classificação consolidada
GET    /api/provas/{prova_id}/summary        → cabeçalho + progresso + ranking
```

Não existem mais `POST/PATCH/DELETE /api/provas*` nem reordenação de prova: a
prova é criada, renumerada e removida automaticamente pelo serviço de baterias.
Editar atributos de uma bateria pode movê-la de grupo e recalcular a
classificação dos dois grupos.

### Baterias (unidade de cadastro)
```
POST   /api/events/{event_id}/heats            → criar bateria (grupo automático)
GET    /api/events/{event_id}/heats            → listar em ordem global (order_num)
PATCH  /api/events/{event_id}/heats/order      → reordenar/mover posição
PATCH  /api/heats/{heat_id}                    → atualizar atributos (move grupo)
DELETE /api/heats/{heat_id}                    → deletar (só se scheduled)
GET    /api/heats/{heat_id}                    → detalhe + snapshot
GET    /api/heats/{heat_id}/eligible-athletes  → ?team_id= (marca alocados no grupo)
POST   /api/heats/{heat_id}/open-ready-check   → status → ready_check
POST   /api/heats/{heat_id}/start              → status → active (exige todas prontas)
POST   /api/heats/{heat_id}/abort              → volta para scheduled
```

`PATCH .../heats/order` aceita **lista completa** `{ids:[...]}` (conjunto exato
de IDs do evento) ou movimentação `{heat_id, position}`. Só baterias
`scheduled` mudam de posição; qualquer tentativa de mover item iniciado/finalizado
retorna `409 bateria_ancorada`. O conjunto inválido retorna
`400 ordem_ids_invalidos`. A operação é atômica sob o lock do evento e
renumera as provas automaticamente.

`PATCH /api/heats/{heat_id}` não aceita `order_num` (use o endpoint de ordem).
Bateria `finished` com mudança de estilo/distância/naipe/categoria retorna
`409 bateria_com_resultado`; a exceção exige `force=true`,
`override_reason` e header `X-Operator-Pin`, registrando snapshot `corrected`
(`reason=correcao_grupo`) e `action_log` (`override_grupo`).

### Equipes / logos
```
POST   /api/events/{event_id}/teams   → criar equipe
GET    /api/events/{event_id}/teams   → listar (inclui athlete_count)
PATCH  /api/teams/{team_id}           → renomear
DELETE /api/teams/{team_id}           → deletar (bloqueado se em uso)
POST   /api/teams/{team_id}/logo      → upload (PNG/JPEG/WebP, <= 1 MB)
DELETE /api/teams/{team_id}/logo      → remover
GET    /logos/{arquivo}               → arquivo estático local
```

### Raias
```
POST   /api/heats/{heat_id}/lanes     → configurar raias (batch; aceita athlete_id)
PATCH  /api/lanes/{lane_id}           → editar participante/equipe/atleta
POST   /api/lanes/{lane_id}/ready     → fiscal confirma pronto
POST   /api/lanes/{lane_id}/finish    → registrar chegada (bateria)
POST   /api/lanes/{lane_id}/lap       → registrar volta (maratona)
POST   /api/lanes/{lane_id}/dq        → desclassificar
DELETE /api/lanes/{lane_id}/lap/last  → desfazer última volta (maratona, < 30s)
```

`finish` e `lap` aceitam corpo **opcional** `{"op_id", "client_ts"}`:
- `op_id`: idempotência. Um `op_id` já processado devolve o resultado original
  com 200, sem efeito colateral.
- `client_ts`: instante do toque em base de tempo do servidor. O servidor usa
  `effective_ts = clamp(client_ts, heat.started_at, now)`; sem `client_ts` usa
  o recebimento (ou a âncora monotônica da bateria). `late=true` quando
  `now - effective_ts > 2 s`.
- Volta repetida na mesma raia a menos de `MIN_LAP_INTERVAL_S` (padrão 5 s)
  retorna `409 volta_duplicada`.

### Regras de validação da bateria (v2.7)

- `422`: ausência/invalidez de `stroke`, `naipe`, `category`, `distance_m`
  (bateria), `duration_s` (maratona), `lane_count` (1–8) ou data do evento.
- Estilos: `crawl`, `borboleta`, `peito`, `costas`, `livre`, `medley`.
- Categorias: `pre_mirim`, `mirim`, `petiz`, `infantil`, `juvenil`, `junior`,
  `adulto`, `livre` (interface: “Cat. Livre”).
- `422 grupo_incompleto`: edição de bateria legada sem completar
  estilo/naipe/categoria; `422 distance_m_obrigatorio` / `duration_s_obrigatorio`
  conforme o tipo; `422 campo_incompativel_bateria` / `lane_count_menor_que_raias`.
- `422 raia_acima_de_lane_count`: raia > `heat.lane_count`.
- `409 bateria_com_resultado`: grupo alterado após resultado sem override.
- `409 bateria_ancorada`: mover bateria não `scheduled`.
- `422`/`409` de inscrição: `naipe_incompativel`, `categoria_incompativel`,
  `atleta_duplicado_na_prova` (mesmo grupo), `atleta_duplicado_na_bateria`,
  `atleta_em_outra_bateria_ativa`, `atleta_com_resultado`.
- `warnings=["evento_mesmo_nome_data"]`: aviso não bloqueante ao criar/editar
  evento com mesmo nome e data.
- Importação: categorias fora da lista são convertidas para `livre`.

### Resultados internos e apresentação
```
GET    /api/events/{event_id}/results        → árvore prova → bateria (leve)
GET    /api/events/{event_id}/presentation   → curadoria normalizada/hidratada
PUT    /api/events/{event_id}/presentation   → salvar curadoria
GET    /api/heats/{heat_id}/snapshots        → histórico de revisões
```

A curadoria é persistida em `event.presentation_json`:
`enabled`, `rotation`, `slide_duration_s`, `show_next_prova`, `pinned_ref` e
`slides` (`prova|bateria` + `target_id`). O telão prioriza a prova ao vivo e,
sem prova ao vivo, exibe os slides elegíveis; o rodapé de “próxima prova” é
opcional. A página interna (`resultados.html`) usa a árvore, o summary da prova
e o histórico de snapshots.

### Identidade visual por nível (v2.6)

- Tokens: `--lvl-evento` (neutro), `--lvl-prova` (`#a78bfa`) e
  `--lvl-bateria` (`#22d3ee`), configuráveis no tema do evento
  (`lvl_prova`, `lvl_bateria`) e incluídos na guarda de contraste.
- Os níveis nunca são diferenciados apenas por cor: usam chip com texto
  “PROVA”/“BATERIA”, ícone e borda lateral (grossa para prova, fina para
  bateria).
- `resultados.html` separa “Resultado da PROVA” (violeta, consolidado) de
  “Resultados por BATERIA” (ciano).
- O telão usa “RESULTADO DA BATERIA” em ciano e “RESULTADO FINAL DA PROVA” em
  violeta, com selo da prova no topo.
- Súmula e CSV exportam o nível em coluna própria. O CSV contém linhas
  `nivel=BATERIA` e, quando consolidado, linhas `nivel=PROVA`.

### Rótulos compartilhados (v2.6)

`frontend/static/common/labels.js` centraliza:
- prova: `PROVA 3 · 25 m Crawl · Masculino · Mirim` (categoria `livre` omitida;
  maratonas: `Maratona 2 h · Misto · Mirim`);
- bateria: `BATERIA 2 de 5`; fora do contexto da prova:
  `BATERIA 2 de 5 · Prova 3`;
- nome de bateria redundante (`Bateria 2`) não é repetido;
- categorias: `Cat. Livre`, `Pré Mirim`, `Júnior`, etc.

### Admin
```
GET    /api/time                      → {now: <epoch do servidor>}
GET    /api/status                    → {uptime, connected_clients, active_heats}
GET    /api/health                    → healthcheck
```

---

## 5. WebSocket

### Endpoint
```
ws://10.42.0.1:8080/ws
```

Conexão única para todos os clientes. O servidor faz broadcast global. Toda
mensagem de estado carrega um campo `scope` para o cliente filtrar. Registro de
chegadas/voltas pode ser feito pelo WebSocket (com ack explícito) ou por REST;
prontidão e controle da prova usam REST.

### Mensagens Servidor → Cliente

```jsonc
// Estado completo de uma prova: configuração, baterias e status
{
  "type": "prova_state",
  "scope": "prova",
  "prova_id": "uuid",
  "payload": { "id": "uuid", "name": "25 m Livre · Misto", "status": "in_progress",
               "mixed_ranking": "both", "heats": [ /* ... */ ] }
}

// Status do servidor (conexão e mudanças de contagem)
{
  "type": "server_status",
  "scope": "home",
  "payload": { "connected": 4, "active_heats": 1 }
}

// Estado completo de uma prova (após qualquer mudança)
{
  "type": "heat_state",
  "scope": "heat",
  "heat_id": "uuid",
  "payload": { "id": "uuid", "name": "Bateria 1", "status": "active",
               "heat_lanes": [ /* ... */ ] }
}

// Atletas do evento alterados (cadastro/importação/edição/exclusão)
{
  "type": "athletes_changed",
  "scope": "event",
  "event_id": "uuid",
  "payload": { "event_id": "uuid" }
}

// Curadoria do telão alterada
{
  "type": "presentation_updated",
  "scope": "event",
  "event_id": "uuid",
  "payload": { "enabled": true, "slides": [/* ... */] }
}

// Situação de prontidão das raias
{
  "type": "ready_update",
  "scope": "heat",
  "heat_id": "uuid",
  "payload": {
    "lanes_ready": [1, 3, 4],
    "lanes_pending": [2, 5],
    "all_ready": false
  }
}

// Confirmação de finish/lap (resposta direta a quem enviou a ação)
{
  "type": "ack",
  "op_id": "uuid-op",
  "ok": true,
  "result": { /* mesmo resultado do endpoint REST */ }
}

// Erro de ação; conexão permanece aberta
{
  "type": "error",
  "op_id": "uuid-op",
  "message": "volta_duplicada"
}

// Heartbeat
{ "type": "pong" }
```

Ao conectar, o servidor envia `server_status`, um `heat_state` para cada
bateria em `ready_check`/`active` e um `prova_state` para cada prova com
bateria ativa. Clientes também reconciliam via REST após reconexão.

### Classificação consolidada

- Padrão: `classification_criterion=lowest_time`; todo grupo consolida suas
  baterias (a opção “Classificar isolada” cria um grupo de uma bateria).
- Reúne resultados válidos (`status=finished` e `race_time_ms` não nulo) somente
  de baterias do mesmo grupo, usando `prova.distance_m` para velocidade e
  classificação.
- Bateria legada com distância divergente da prova é ignorada do consolidado e
  sinalizada em `warnings` (`bateria_distancia_divergente`), mas continua
  visível em `battery_results`.
- Ordena pelo inteiro `race_time_ms` (nunca pela string).
- Empate: mesma posição esportiva, próxima salta (1,2,2,4); a ordem visual
  desempata por raia, nome e id, sem atribuir posição diferente.
- DQ, sem tempo e baterias em andamento ficam fora do ranking de válidos,
  em `excluded`, preservando o status.
- `is_provisional=true` enquanto qualquer bateria da prova não estiver
  `finished`; somente então a classificação é definitiva.
- `mixed_ranking` é derivado: `both` para prova `MISTO` (geral + por naipe) e
  `overall` para os demais. A interface sempre informa “Classificação
  consolidada de N baterias (menor tempo)” e mantém `battery_results` com o
  resultado de cada bateria.

### Mensagens Cliente → Servidor

```jsonc
// Registro de chegada/volta com op_id e tempo do toque
{ "type": "finish", "lane_id": "uuid", "op_id": "uuid-op", "client_ts": 1790000000.0 }
{ "type": "lap",    "lane_id": "uuid", "op_id": "uuid-op", "client_ts": 1790000000.0 }

// Heartbeat (a cada 5 s no cliente; sem pong em 3 s reconecta)
{ "type": "ping" }
```

`op_id` e `client_ts` são opcionais (compatibilidade), mas o cliente atual
sempre os envia. Toda ação de registro é gravada na outbox local antes do
envio e só é removida com `ack`/2xx; sem ack em 3 s o cliente reenvia por REST
com o mesmo `op_id`.

---

## 6. Estrutura de Arquivos do Projeto

```
swimtimer/
├── backend/
│   ├── app/
│   │   ├── main.py           ← FastAPI app + rotas + WS
│   │   ├── database.py       ← SQLAlchemy + SQLite + start das migrations
│   │   ├── models.py         ← ORM (Event, Prova, Team, Athlete, Heat, HeatLane, LapEvent)
│   │   ├── schemas.py        ← Pydantic schemas
│   │   ├── classification.py ← classificação consolidada
│   │   ├── ws_manager.py     ← WebSocket connection manager
│   │   └── config.py         ← Settings (porta, banco, limites de upload)
│   ├── migrations/           ← ambiente Alembic + versões (0001–0007)
│   │   ├── env.py
│   │   └── versions/
│   ├── alembic.ini
│   ├── tests/                ← pytest (API, atletas, importação, provas, carga)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── index.html            ← Tela inicial (redireciona por perfil)
│   ├── gestao.html           ← Gestão do evento (equipes, atletas, provas)
│   ├── fiscal.html           ← Interface do fiscal (mobile-first)
│   ├── supervisor.html       ← Controle operacional
│   ├── publico.html          ← Telão público
│   ├── tests/                ← testes de lógica pura (node --test)
│   └── static/
│       ├── app.js            ← Lógica compartilhada + WS client
│       ├── gestao.js         ← Gestão (equipes, atletas, importação)
│       ├── gestao_logic.js   ← Funções puras testáveis da gestão
│       ├── style.css         ← Estilos globais
│       └── fiscal.js         ← Lógica específica do fiscal
├── docs/
│   ├── PRD.md
│   ├── SPEC.md
│   ├── ROADMAP.md
│   ├── CHANGELOG.md
│   └── ADR/
├── docker-compose.yml
├── .env.example
├── start.sh                  ← Um comando para subir tudo
└── README.md
```

---

## 6.1. Concorrência e limites

- Locks `asyncio` por bateria e por evento no processo + índices únicos no
  SQLite (`uq_heat_event_order`, `uq_lap_event_lane_number`) como rede de
  segurança.
- Finalização dupla retorna `409 ja_finalizou`; persistência ocorre antes do
  broadcast. WS reflete somente o que foi gravado.
- Importação de atletas grava o subconjunto válido em uma única transação. O
  índice único `uq_athlete_event_name_team` é a rede de segurança contra
  duplicatas concorrentes (conflito retorna `409 importacao_conflito`).
- Listagens de atletas são paginadas no servidor (`limit` até 200, padrão 50),
  com filtros por nome, equipe, naipe e categoria; contagens por equipe são
  agregadas em SQL (`athlete_count`), sem varredura no frontend.
- Implantação suportada: **um worker uvicorn** com SQLite WAL. Para múltiplos
  workers seria necessário banco com escrita concorrente (PostgreSQL) ou
  outro particionamento — ver `docs/ADR/005-concorrencia.md`.
- `op_id` é checado e gravado em `processed_op` dentro do lock da bateria:
  reenvios concorrentes devolvem o resultado original sem duplicar.
- `action_log` registra toda ação que muda estado (start, abort, finish de
  bateria, finish/lap/dq/undo de raia) para auditoria.
- Debounce de volta: `MIN_LAP_INTERVAL_S` (padrão 5 s) na mesma raia retorna
  `409 volta_duplicada`.
- Tempo do toque: `client_ts` (base do servidor) é clampado a
  `[started_at, now]`; sem `client_ts` a duração usa âncora `time.monotonic()`
  por bateria, com fallback wall-clock após restart. `race_time_ms` é
  quantizado em múltiplos de 10 ms (piso), coerente com o display `MM:SS.cc` —
  tempos exibidos iguais empatam no ranking. Não é cronometragem oficial de
  precisão.

## 7. Segurança e Confiabilidade

- **Tempo do toque em base do servidor:** o cliente sincroniza `client_ts` via `GET /api/time`; o servidor clampa a `[started_at, now]`, registra `received_at` e marca `late`. O relógio cru do celular nunca é usado.
- **Idempotência e auditoria:** `op_id` repetido devolve o resultado original (`processed_op`); toda ação de estado fica em `action_log`. A outbox do fiscal só é limpa com ack/2xx; 4xx ficam visíveis como rejeitados.
- **Undo com janela:** desfazer permitido apenas nos 30 segundos após o registro (relógio do servidor via `serverNow()` no cliente).
- **Isolamento por evento:** equipes e atletas são validados contra o `event_id` da raia/importação; um atleta do evento A nunca é aceito no evento B.
- **Upload de planilha:** extensão + magic bytes (XLSX), limite de 2 MB/1000 linhas e parsing sem execução; conteúdo é escapado na renderização.
- **Índices únicos:** nomes de atletas são únicos por evento+equipe (case-insensitive), evitando duplicatas por importações repetidas.
- **Reconexão automática:** cliente WebSocket reconecta com backoff `[500, 1000, 2000, 3000, 5000]` ms; heartbeat `ping` a cada 5 s e reconexão se não houver `pong` em 3 s.
- **Persistência imediata:** cada lap_event é escrito no SQLite antes de fazer broadcast.
- **Backup automático:** `start.sh` faz cópia do banco antes de subir o servidor.
