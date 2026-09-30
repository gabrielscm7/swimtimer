# CHANGELOG — SwimTimer

Formato: [Semantic Versioning](https://semver.org/lang/pt-BR/)

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
