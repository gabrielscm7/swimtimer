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
Competition
  id, name, status, duration_seconds, meters_per_lap
  created_at, started_at, finished_at

Team
  id, competition_id, name

Lane
  id, competition_id, number (1–8), team_id
  laps (int), status (waiting|active|finished)

LapEvent
  id, lane_id, lap_number, recorded_at (servidor)
  is_undo (bool)
```

### 3.2 Tabelas SQL

```sql
CREATE TABLE competition (
    id          TEXT PRIMARY KEY,  -- UUID
    name        TEXT NOT NULL,
    status      TEXT DEFAULT 'draft',  -- draft|active|finished
    duration_s  INTEGER NOT NULL,  -- duração em segundos (ex: 10800 = 3h)
    meters_lap  INTEGER NOT NULL,  -- metros por comprimento (25 ou 50)
    started_at  REAL,              -- unix timestamp
    finished_at REAL,
    created_at  REAL NOT NULL
);

CREATE TABLE team (
    id              TEXT PRIMARY KEY,
    competition_id  TEXT NOT NULL REFERENCES competition(id),
    name            TEXT NOT NULL
);

CREATE TABLE lane (
    id              TEXT PRIMARY KEY,
    competition_id  TEXT NOT NULL REFERENCES competition(id),
    number          INTEGER NOT NULL,  -- 1 a 8
    team_id         TEXT REFERENCES team(id),
    laps            INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'waiting'
);

CREATE TABLE lap_event (
    id          TEXT PRIMARY KEY,
    lane_id     TEXT NOT NULL REFERENCES lane(id),
    lap_number  INTEGER NOT NULL,
    recorded_at REAL NOT NULL,  -- unix timestamp do SERVIDOR
    is_undo     BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_lap_event_lane ON lap_event(lane_id);
CREATE INDEX idx_lap_event_recorded ON lap_event(recorded_at);
```

---

## 4. API REST

### Competição
```
GET    /api/competition/current     → estado atual completo
POST   /api/competition             → criar nova competição
PATCH  /api/competition/{id}        → atualizar (nome, duração, etc)
POST   /api/competition/{id}/start  → disparar cronômetro (operador)
POST   /api/competition/{id}/reset  → zerar (senha obrigatória)
```

### Equipes e Raias
```
POST   /api/team                    → cadastrar equipe
GET    /api/team?competition={id}   → listar equipes
POST   /api/lane/{id}/assign        → atribuir equipe a raia
```

### Lançamentos
```
POST   /api/lane/{id}/lap           → registrar chegada/virada (fiscal)
DELETE /api/lane/{id}/lap/last      → desfazer último (fiscal, < 30s)
```

### Admin
```
GET    /api/export/csv              → exportar resultados
GET    /api/health                  → healthcheck
```

---

## 5. WebSocket

### Endpoint
```
ws://10.42.0.1:8080/ws
```

Conexão única para todos os clientes. O servidor faz broadcast para todos quando qualquer estado muda.

### Mensagens Servidor → Cliente

```jsonc
// Estado completo (enviado na conexão e após qualquer mudança)
{
  "type": "state",
  "competition": {
    "id": "uuid",
    "name": "Festival Infantil SESI",
    "status": "active",
    "started_at": 1727700000.0,
    "duration_s": 10800
  },
  "lanes": [
    {
      "id": "uuid",
      "number": 1,
      "team": "Equipe Azul",
      "laps": 12,
      "meters": 600,
      "status": "active",
      "last_lap_at": 1727700123.4
    }
  ]
}

// Confirmação de lap (enviado após registro)
{
  "type": "lap",
  "lane_id": "uuid",
  "lane_number": 3,
  "team": "Equipe Vermelha",
  "laps": 7,
  "meters": 350
}

// Timer (enviado a cada segundo quando ativo)
{
  "type": "tick",
  "elapsed_s": 1842,
  "remaining_s": 8958
}
```

### Mensagens Cliente → Servidor
```jsonc
// Registrar virada/chegada
{ "type": "lap", "lane_id": "uuid" }

// Desfazer último
{ "type": "undo", "lane_id": "uuid" }

// Controle de timer (operador)
{ "type": "timer_start" }
{ "type": "timer_pause" }
{ "type": "timer_reset", "password": "xxxx" }
```

---

## 6. Estrutura de Arquivos do Projeto

```
swimtimer/
├── backend/
│   ├── app/
│   │   ├── main.py           ← FastAPI app + rotas + WS
│   │   ├── database.py       ← SQLAlchemy + SQLite
│   │   ├── models.py         ← ORM models
│   │   ├── schemas.py        ← Pydantic schemas
│   │   ├── ws_manager.py     ← WebSocket connection manager
│   │   ├── timer.py          ← Lógica do cronômetro (asyncio)
│   │   └── config.py         ← Settings (senha, porta, etc)
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
