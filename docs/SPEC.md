# SPEC — SwimTimer v1.0
**Versão:** 1.0  
**Data:** 2026-09-30  
**Status:** Rascunho para revisão

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

## 3. Modelos de Dados (v1.0)

### 3.1 Diagrama

```
Event
  id, name, location, date, pool_length_m (25|50)
  status (draft|active|finished), created_at

Team
  id, event_id, name

Heat
  id, event_id, name, order_num, heat_type (maratona|bateria)
  distance_m (bateria), duration_s (maratona)
  status (scheduled|ready_check|active|finished)
  started_at, finished_at

HeatLane
  id, heat_id, lane_number (1–8), participant_name, team_id
  status (assigned|ready|active|finished|dq)
  finish_at, race_time_ms

LapEvent
  id, lane_id, lap_number, recorded_at (servidor), is_undo
```

> Um `Event` é o contêiner (várias `Heat`). Cada `Heat` é uma prova
> individual (bateria cronometrada ou maratona) com até 8 `HeatLane`.

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
    name      TEXT NOT NULL
);

CREATE TABLE heat (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES event(id),
    name         TEXT NOT NULL,
    order_num    INTEGER NOT NULL,
    heat_type    TEXT NOT NULL,      -- maratona|bateria
    distance_m   INTEGER,            -- bateria
    duration_s   INTEGER,            -- maratona
    status       TEXT DEFAULT 'scheduled',
    started_at   REAL,
    finished_at  REAL
);

CREATE TABLE heat_lane (
    id               TEXT PRIMARY KEY,
    heat_id          TEXT NOT NULL REFERENCES heat(id),
    lane_number      INTEGER NOT NULL,  -- 1 a 8
    participant_name TEXT,
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
GET    /api/events                    → lista todos (com heats)
POST   /api/events                    → criar evento
GET    /api/events/{event_id}         → detalhe + heats + teams
PATCH  /api/events/{event_id}         → atualizar
DELETE /api/events/{event_id}         → deletar (só se draft)
```

### Equipes
```
POST   /api/events/{event_id}/teams   → criar equipe
GET    /api/events/{event_id}/teams   → listar
DELETE /api/teams/{team_id}           → deletar
```

### Provas (heats)
```
POST   /api/events/{event_id}/heats            → criar prova
GET    /api/events/{event_id}/heats            → listar em ordem
PATCH  /api/heats/{heat_id}                    → atualizar
DELETE /api/heats/{heat_id}                    → deletar (só se scheduled)
POST   /api/heats/{heat_id}/open-ready-check   → status → ready_check
POST   /api/heats/{heat_id}/start              → status → active (exige todas prontas)
POST   /api/heats/{heat_id}/abort              → volta para scheduled
```

### Raias
```
POST   /api/heats/{heat_id}/lanes     → configurar raias (batch)
PATCH  /api/lanes/{lane_id}           → editar participante/equipe
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

Ao conectar, o servidor envia `server_status` e, em seguida, um `heat_state`
para cada prova em `ready_check` ou `active`.

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
│   │   ├── models.py         ← ORM models (Event, Team, Heat, HeatLane, LapEvent)
│   │   ├── schemas.py        ← Pydantic schemas
│   │   ├── ws_manager.py     ← WebSocket connection manager
│   │   └── config.py         ← Settings (porta, banco, etc)
│   ├── migrations/           ← ambiente Alembic + versões
│   │   ├── env.py
│   │   └── versions/
│   ├── alembic.ini
│   ├── tests/
│   │   ├── test_api.py
│   │   └── test_ws.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── index.html            ← Tela inicial (redireciona por perfil)
│   ├── fiscal.html           ← Interface do fiscal (mobile-first)
│   ├── dashboard.html        ← Telão público
│   ├── admin.html            ← Configuração e controle
│   └── static/
│       ├── app.js            ← Lógica compartilhada + WS client
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

## 7. Segurança e Confiabilidade

- **Timestamp no servidor:** `recorded_at` sempre vem do servidor, nunca do cliente. Elimina drift de relógio de celular.
- **Undo com janela:** desfazer permitido apenas nos 30 segundos após o registro. Após isso, requer senha de árbitro.
- **Reset protegido:** senha configurável em `.env`, nunca hardcoded.
- **Reconexão automática:** cliente WebSocket reconecta com exponential backoff (1s, 2s, 4s, 8s, máx 30s).
- **Persistência imediata:** cada lap_event é escrito no SQLite antes de fazer broadcast.
- **Backup automático:** `start.sh` faz cópia do banco antes de subir o servidor.
