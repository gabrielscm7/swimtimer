# SPEC — SwimTimer v2.1
**Versão:** 2.1  
**Data:** 2026-10-21  
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
  id, name, location, date, pool_length_m (25|50)
  status (draft|active|finished), created_at

Prova
  id, event_id, name, order_num, stroke, distance_m, category
  consolidate_results (padrão true), classification_criterion (lowest_time)
  status (scheduled|in_progress|finished), created_at

Team
  id, event_id, name, logo_url

Athlete
  id, event_id, team_id (opcional), name, naipe (M|F), category
  created_at, updated_at

Heat (bateria)
  id, event_id, prova_id, name, order_num (único por prova)
  heat_type (maratona|bateria), distance_m, duration_s
  status (scheduled|ready_check|active|finished)
  started_at, finished_at

HeatLane
  id, heat_id, lane_number (1–8), participant_name, athlete_id, team_id
  status (assigned|ready|active|finished|dq)
  finish_at, race_time_ms

LapEvent
  id, lane_id, lap_number, recorded_at (servidor), is_undo
```

> Hierarquia: **Evento → Prova → Bateria → Raia/Atleta → Resultado**.
> Cada `Heat` (bateria) pertence a uma `Prova`; cada prova pertence a um
> `Evento`. A referência redundante `heat.event_id` é mantida por
> compatibilidade e eficiência, mas a autoridade é `heat.prova_id`.
>
> `Athlete` é o cadastro único do atleta dentro do evento. `HeatLane.atleta_id`
> é opcional: quando presente, nome e equipe exibidos na raia são derivados do
> atleta (e mantidos em sincronia em `participant_name`/`team_id` para os
> clientes legados). Raias antigas sem atleta continuam válidas via
> `participant_name` livre.

### 3.2 Tabelas SQL

```sql
CREATE TABLE event (
    id             TEXT PRIMARY KEY,  -- UUID
    name           TEXT NOT NULL,
    location       TEXT,
    date           TEXT,              -- ISO date string
    pool_length_m  INTEGER NOT NULL,  -- 25 ou 50
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
    name                      TEXT NOT NULL,
    order_num                 INTEGER NOT NULL,
    stroke                    TEXT,
    distance_m                INTEGER,
    category                  TEXT,
    consolidate_results       BOOLEAN NOT NULL DEFAULT 1,
    classification_criterion  TEXT NOT NULL DEFAULT 'lowest_time',
    status                    TEXT NOT NULL DEFAULT 'scheduled',
    created_at                REAL NOT NULL,
    UNIQUE (event_id, order_num)
);

CREATE TABLE heat (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES event(id),
    prova_id     TEXT NOT NULL REFERENCES prova(id),
    name         TEXT NOT NULL,
    order_num    INTEGER NOT NULL,
    heat_type    TEXT NOT NULL,      -- maratona|bateria
    distance_m   INTEGER,            -- bateria
    duration_s   INTEGER,            -- maratona
    status       TEXT DEFAULT 'scheduled',
    started_at   REAL,
    finished_at  REAL,
    UNIQUE (prova_id, order_num)
);

CREATE TABLE heat_lane (
    id               TEXT PRIMARY KEY,
    heat_id          TEXT NOT NULL REFERENCES heat(id),
    lane_number      INTEGER NOT NULL,  -- 1 a 8
    participant_name TEXT,
    athlete_id       TEXT REFERENCES athlete(id),
    team_id          TEXT REFERENCES team(id),
    status           TEXT DEFAULT 'assigned',
    finish_at        REAL,
    race_time_ms     INTEGER,
    UNIQUE (heat_id, lane_number)
);

CREATE TABLE lap_event (
    id          TEXT PRIMARY KEY,
    lane_id     TEXT NOT NULL REFERENCES heat_lane(id),
    lap_number  INTEGER NOT NULL,
    recorded_at REAL NOT NULL,  -- unix timestamp do SERVIDOR
    is_undo     BOOLEAN DEFAULT FALSE
);

CREATE INDEX ix_heat_event_order ON heat(event_id, order_num);
CREATE INDEX ix_lap_event_lane_recorded ON lap_event(lane_id, recorded_at);
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

### Provas
```
POST   /api/events/{event_id}/provas             → criar prova
GET    /api/events/{event_id}/provas             → listar (com baterias)
GET    /api/provas/{prova_id}                    → detalhe
PATCH  /api/provas/{prova_id}                    → editar
DELETE /api/provas/{prova_id}                    → deletar (só se todas as baterias scheduled)
GET    /api/provas/{prova_id}/classification     → classificação consolidada
POST   /api/provas/{prova_id}/heats              → criar bateria na prova
GET    /api/provas/{prova_id}/heats              → listar baterias
```

### Baterias
```
GET    /api/events/{event_id}/heats            → listar em ordem (prova → bateria)
PATCH  /api/heats/{heat_id}                    → atualizar (order_num único por prova)
DELETE /api/heats/{heat_id}                    → deletar (só se scheduled)
POST   /api/heats/{heat_id}/open-ready-check   → status → ready_check
POST   /api/heats/{heat_id}/start              → status → active (exige todas prontas)
POST   /api/heats/{heat_id}/abort              → volta para scheduled
```

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

### Admin
```
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
mensagem carrega um campo `scope` para o cliente filtrar. As ações de escrita
são feitas via REST; o WebSocket é usado somente para receber atualizações.

### Mensagens Servidor → Cliente

```jsonc
// Estado completo de uma prova: configuração, baterias e status
{
  "type": "prova_state",
  "scope": "prova",
  "prova_id": "uuid",
  "payload": { "id": "uuid", "name": "100m livres", "status": "in_progress",
               "consolidate_results": true, "heats": [ /* ... */ ] }
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
  "payload": { "event_id": "uuid" }
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
```

Ao conectar, o servidor envia `server_status`, um `heat_state` para cada
bateria em `ready_check`/`active` e um `prova_state` para cada prova com
bateria ativa. Clientes também reconciliam via REST após reconexão.

### Classificação consolidada

- Padrão por prova: `consolidate_results=true`, `classification_criterion=lowest_time`.
- Reúne resultados válidos (`status=finished` e `race_time_ms` não nulo) de
  todas as baterias e ordena pelo inteiro `race_time_ms` (nunca pela string).
- Empate: mesma posição esportiva, próxima salta (1,2,2,4); a ordem visual
  desempata por raia, nome e id, sem atribuir posição diferente.
- DQ, sem tempo e baterias em andamento ficam fora do ranking de válidos,
  em `excluded`, preservando o status.
- `is_provisional=true` enquanto qualquer bateria da prova não estiver
  `finished`; somente então a classificação é definitiva.
- Com `consolidate_results=false`, a resposta traz `battery_results` por
  bateria e `standings` vazio.

### Mensagens Cliente → Servidor
Nenhuma. Registro de voltas/chegadas, prontidão e controle da prova são feitos
pelos endpoints REST (`/api/lanes/...`, `/api/heats/...`).

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
│   ├── migrations/           ← ambiente Alembic + versões (0001–0005)
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

- Locks `asyncio` por bateria/prova no processo + índices únicos no SQLite
  (`uq_heat_prova_order`, `uq_lap_event_lane_number`) como rede de segurança.
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
- `race_time_ms` é medido no servidor (instante de recebimento). Não é
  cronometragem oficial de precisão; o sistema não faz essa alegação.

## 7. Segurança e Confiabilidade

- **Timestamp no servidor:** `recorded_at` sempre vem do servidor, nunca do cliente. Elimina drift de relógio de celular.
- **Undo com janela:** desfazer permitido apenas nos 30 segundos após o registro.
- **Isolamento por evento:** equipes e atletas são validados contra o `event_id` da raia/importação; um atleta do evento A nunca é aceito no evento B.
- **Upload de planilha:** extensão + magic bytes (XLSX), limite de 2 MB/1000 linhas e parsing sem execução; conteúdo é escapado na renderização.
- **Índices únicos:** nomes de atletas são únicos por evento+equipe (case-insensitive), evitando duplicatas por importações repetidas.
- **Reconexão automática:** cliente WebSocket reconecta com exponential backoff (1s, 2s, 4s, 8s, máx 30s).
- **Persistência imediata:** cada lap_event é escrito no SQLite antes de fazer broadcast.
- **Backup automático:** `start.sh` faz cópia do banco antes de subir o servidor.
