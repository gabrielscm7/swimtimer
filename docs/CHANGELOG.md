# CHANGELOG — SwimTimer

Formato: [Semantic Versioning](https://semver.org/lang/pt-BR/)

---

## [Unreleased] — v2.0.1

### Fixed
- Concorrência de raias: `finish` duplo agora retorna 409 (lock por prova); `lap_number` único por raia (constraint `uq_lap_event_lane_number` + migração `0002` que renumera dados legados)
- `order_num` de provas não colide mais em criação simultânea
- Batch de raias com `lane_number` repetido retorna 400 em vez de 500
- `PATCH /api/lanes/{id}` com corpo vazio não derruba mais o estado `ready`
- WebSocket não derruba mais a conexão em erro interno (responde `erro_interno`)
- `.env` ausente: `start.sh` cria a partir de `.env.example` via `scripts/ensure_env.sh` e não aborta mais em silêncio
- `start.sh` reconstrói a imagem quando o código-fonte muda (hash em `.build_hash`), evitando rodar imagem velha
- Backup do SQLite usa `sqlite3 .backup` (snapshot consistente) com fallback para `cp`
- Fiscal: erros definitivos (4xx) são descartados da fila offline; fallback REST atualiza o estado local
- Reconexão do WebSocket não empilha mais sockets/timers
- XSS: escape de `heat.name`/`participant_name`/`team`/`date` em admin, dashboard e gestão

### Changed
- SQLite com `journal_mode=WAL`, `busy_timeout=5000` e `foreign_keys=ON`
- `docker-compose.yml` sem `version` obsoleto e com `env_file` opcional
- Scripts `stop.sh`/`setup-permissions.sh` com `set -euo pipefail` e `cd` para o diretório do script
- `hotspot.sh` lê `HOTSPOT_SSID`/`HOTSPOT_PASSWORD`/`HOTSPOT_INTERFACE` do `.env`

---

## [Unreleased] — v2.0.0

### Changed
- Refatoração arquitetural: `Competition`/`Lane` substituídos por `Event` (contêiner) + `Heat` (prova) + `HeatLane` (raia)
- Migração Alembic aplicada automaticamente no start, migrando dados de `competition`/`lane` sem perda
- API REST reorganizada em Eventos, Equipes, Provas e Raias
- WebSocket com mensagens escopadas: `heat_state` (scope `heat`), `ready_update` (scope `heat`) e `server_status` (scope `home`)
- Cronômetro calculado no cliente a partir de `started_at`; removido o timer global do servidor

### Added
- `GET /api/status` com uptime, clientes conectados e provas ativas
- Fluxo de prontidão (`open-ready-check` + `ready` por raia) antes de iniciar uma prova
- DQ por raia contabilizado para encerrar a prova

### Removed
- Endpoints `/api/competition/*`, `/api/team` e `/api/lane/*/assign`
- `app/timer.py` e as migrações SQL manuais (`migrations/001_add_bateria.sql`)

---

## [Unreleased] — v1.0.0

### Added
- FastAPI backend com WebSocket (substitui http.server + polling)
- SQLite via SQLAlchemy (substitui JSON em disco)
- Frontend modular: fiscal.html, dashboard.html, admin.html
- Reconexão automática WebSocket com exponential backoff
- Cronômetro gerenciado pelo servidor (asyncio)
- Timestamp de lap_event registrado no servidor (não no cliente)
- `start.sh` com backup automático do banco
- Hotspot via nmcli (IP fixo 10.42.0.1)
- Docker Compose para ambiente reproduzível
- Documentação: PRD, SPEC, ROADMAP, ADR, SETUP, RUNBOOK

---

## [0.3.0] — 2026-04-13 (sistema atual — maratona_aquatica)

### Added
- Servidor multi-thread (ThreadingMixIn)
- Função desfazer último lançamento (30s, protegida por raia)
- Modal de reset com senha de administrador
- Backup automático antes do reset
- Log de chegadas em CSV com campo de ação (CHEGADA/DESFAZER)
- Painel de último lançamento por raia na tela do fiscal
- Nome "SESI em Movimento — Maratona Aquática" no dashboard
- Cronômetro de 3 horas

### Fixed
- SyntaxError: global estado declarado após uso (linha 211)
- Erros 400 de dispositivos da rede suprimidos no log
- Conexão HTTPS em celulares: orientação para uso de http:// explícito

---

## [0.2.0] — 2026-04-10

### Added
- Servidor Python centralizado (substitui localStorage)
- API REST: /api/chegada, /api/timer, /api/reset
- Sincronização real entre dispositivos via polling (2s)
- Indicador online/offline no frontend
- Banner de aviso quando sem conexão
- INICIAR_SERVIDOR.bat para Windows

---

## [0.1.0] — 2026-04-10

### Added
- Aplicação HTML inicial com localStorage
- Tela de fiscal: seleção de raia e equipe, botão de chegada
- Dashboard com ranking em tempo real e cronômetro
- 7 raias, 7 equipes, 50m por chegada
