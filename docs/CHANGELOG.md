# CHANGELOG — SwimTimer

Formato: [Semantic Versioning](https://semver.org/lang/pt-BR/)

---

## [2.8.0] — 2026-10-24

### Added
- Telão 16:9 sem rolagem: palco em grid (cabeçalho EVENTO, corpo, rodapé),
  tipografia em `vh` com piso de 22 px, nome do atleta em uma linha e tabelas
  usando toda a largura útil.
- Paginação automática por altura útil (rotação a cada 8 s com indicador
  `1/N`), classificação em duas colunas (1–10 | 11–20) e baterias lado a lado
  em 2–3 colunas.
- Identidade por nível no telão (faixa do evento + chips PROVA/BATERIA),
  reutilizando os tokens `--lvl-prova`/`--lvl-bateria`.
- `static/common/result_views.js`: fonte única de renderização de resultado de
  prova e de bateria para telão, resultados e súmula.
- Prévia do telão em `resultados.html` (iframe 16:9 escalado, modo preview sem
  efeitos no servidor) e botão “Enviar ao telão agora”.
- `scripts/seed_demo.py` (evento de demonstração determinístico) e
  `scripts/tv_check.py` (Playwright em 1920×1080, 1366×768 e 1280×720,
  capturas em `docs/screenshots/`).
- `backend/requirements-dev.txt` com Playwright (apenas desenvolvimento).
- Hook `?preview=1&fast=1` para acelerar os tempos de resultado na verificação.

### Changed
- Somente provas MISTO exibem classificação geral + por naipe; provas M/F
  exibem uma única tabela e nenhuma tabela vazia é renderizada.
- Resultado da bateria não repete mais a classificação consolidada da prova.
- `heat_state`, `prova_state`, `presentation_updated`, `settings_updated` e
  `theme_updated` redesenham o estado atual (inclusive 7 e 8) preservando a
  página; números mágicos substituídos por `STATE.*`.

---

## [2.7.0] — 2026-10-23

### Added
- Bateria como **unidade de cadastro**; a Prova passa a ser um grupo automático
  por `(heat_type, stroke, distance_m [só bateria de tempo], naipe, category)`
  (ADR-012, revoga parcialmente ADR-004/007/011).
- `heat.stroke/naipe/category/lane_count/classify_alone`; `event.default_lane_count`.
- `POST /api/events/{id}/heats`, `PATCH /api/events/{id}/heats/order`
  (lista completa ou `{heat_id, position}`) e
  `GET /api/heats/{id}/eligible-athletes?team_id=`.
- “Classificar isolada” cria um grupo próprio (badge “Isolada”).
- Bloqueio pós-resultado de atributos de grupo, com exceção do supervisor
  (`X-Operator-Pin` + motivo + snapshot `corrected`).
- Migração `0015_bateria_unidade_cadastro`, reversível e testada com dados
  legados: copia atributos da prova, converte categorias fora da lista para
  `livre`, renumera `order_num` global e ajusta `lane_count`.
- Tela única “Baterias” na gestão, com ordem livre (arrastar e campo numérico),
  chips de estilo/distância/naipe/categoria, selo da prova, duplicar e criar N
  baterias do mesmo grupo; editor de raias por equipe com atletas elegíveis.

### Changed
- `heat.order_num` passa a ser único por **evento** (`uq_heat_event_order`);
  `event_seq = order_num`. Só baterias `scheduled` podem mudar de posição.
- Nome da prova é sempre gerado; categorias `livre` são omitidas.
- Prova `MISTO` sempre exibe classificação geral + por naipe; `mixed_ranking`
  deixa de ser configurável.
- Importação de atletas converte categorias fora da lista para `livre`.

### Removed
- CRUD e reordenação de prova (`POST/PATCH/DELETE /api/provas*`,
  `PUT /api/events/{id}/provas/order`, `POST/PUT /api/provas/{id}/heats*`).
- `prova.name_override`, `mixed_ranking`, `legacy_incomplete` e
  `consolidate_results`; `gestao/provas.js` e o formulário de prova.

---

## [2.6.0] — 2026-10-23

### Added
- Página interna de resultados (`resultados.html`) com navegação evento →
  prova → bateria, classificação agregada, detalhe das baterias, histórico de
  snapshots, súmula e exportação.
- Curadoria do telão: playlist de provas/baterias, rotação, duração do slide,
  “fixar agora”, exibição opcional da próxima prova no rodapé e persistência em
  `event.presentation_json` (migração `0013_event_presentation`).
- Endpoints `GET/PUT /api/events/{id}/presentation`,
  `GET /api/events/{id}/results` e `GET /api/heats/{id}/snapshots`.
- Evento WebSocket `presentation_updated`.
- O telão mantém a prova ao vivo como prioridade e, sem prova ao vivo, exibe a
  curadoria definida pelo supervisor.
- Hierarquia explícita EVENTO → PROVA → BATERIA: formato da prova, herança de
  tipo/distância pelas baterias, nome gerado com sobrescrita opcional e
  validação de unicidade por estilo/distância/naipe/categoria.
- Migração `0014_prova_format_definition` com backfill de `format` e marcação
  `legacy_incomplete` sem quebrar dados antigos.
- Resultado da PROVA (consolidado) separado do resultado da BATERIA em
  `resultados.html`, telão, súmula e CSV; classificação ignora baterias legadas
  com distância divergente e expõe `warnings`.
- Rótulos compartilhados em `frontend/static/common/labels.js` para fiscal,
  supervisor, gestão, resultados, súmula e telão.
- Tokens de identidade visual por nível (`--lvl-evento`, `--lvl-prova`,
  `--lvl-bateria`), configuráveis no tema do evento e com guarda de contraste.
- Data ISO obrigatória no evento e aviso não bloqueante para mesmo nome/data.

### Changed
- CSV de resultados ganhou a coluna `nivel` e linhas consolidadas `PROVA`
  além das linhas por `BATERIA`.
- O formulário de bateria não edita mais distância/tipo; ambos são herdados da
  prova.

### Removed
- QR Code e página pública mobile de resultados.
- Endpoints `/api/public/...` e serviço `public_results`.
- Toggle de “publicar resultados públicos” na gestão; `public_name_mode`
  continua controlando a exibição de nomes no telão.

### Fixed
- Gestão: módulos que usavam `eventId` sem importar de `state.js`, salvamento de
  raia individual (`Number(uuid)` → `NaN`) e chamadas sem namespace de
  `gestaoErrorMessage`
- TV pública: `ReferenceError` (`perBattery`) em provas com
  `consolidate_results=false`
- `PATCH` com `null` em campos `NOT NULL` agora retorna 422 (antes 500)
- `abort` invalida tempos/DQ/voltas parciais e permite novo disparo
- `undo_lap` após finish gera snapshot `corrected` (`undo_finish`)
- Cadeia de snapshots é comitada sob o lock do evento (corrige fork sob
  concorrência entre baterias do mesmo evento)
- Metadados de snapshot (`status`, `revision`, autor, IP) entram no payload
  canônico e são verificados por `/audit/verify`
- `op_id` reutilizado em outra raia/ação retorna 409 `op_id_conflitante`
- `finish` rejeita raia DQ/vazia; `update_lane` não dessincroniza equipe de
  atleta
- Ciclo de vida do evento (`draft`/`active`/`finished`) automático; exclusão de
  evento com bateria iniciada bloqueada
- Maratona finaliza pelo relógio do servidor, independente do navegador
- WebSocket: `athletes_changed` com `event_id` no topo, assinatura por evento e
  mascaramento de nomes para assinantes públicos
- Journal só grava após commit; importação XLSX limita linhas antes de
  materializar; CSV escapa fórmulas; logos são limpos e serializados
- Limpeza de locks com `WeakValueDictionary` e broadcast WS sem bloqueio de
  cabeça de fila

---

## [2.5.0] — 2026-10-23

### Added
- `result_snapshot` append-only: revisão imutável do resultado de cada bateria
  com payload canônico (atleta/equipe/naipe/categoria no momento), hash
  encadeado por evento e triggers SQLite que abortam UPDATE/DELETE
- Revisão 1 (provisória) ao finalizar a bateria e revisão oficial na
  homologação; o undo de volta após o finish gera revisão `corrected`. Os
  reasons de DQ/reset permanecem como contrato para fluxos futuros.
- `POST /api/heats/{id}/homologate` (supervisor) e
  `GET /api/events/{id}/audit/verify` (recalcula a cadeia de hashes)
- Diário NDJSON por evento em `data/journal/<event_id>.ndjson` (append com
  flush + fsync), espelhando `action_log` e `result_snapshot`
- `BackupService` no lifespan: intervalo `BACKUP_INTERVAL_MIN` (padrão 5),
  backup 10 s após finalizar bateria, sidecar `.sha256`, retenção de 12
  recentes + 1 por hora + final, espelho opcional `BACKUP_MIRROR_DIR` com
  verificação; `/api/status` expõe `last_backup_at`, `last_error` e
  `mirror_ok`
- `scripts/restore.sh` com validação de checksum e `tests/ops/test_restore.sh`
- Exportações: `results.csv` (`;` + BOM), `sumula.html?heat=` imprimível e
  `POST /api/events/{id}/export/bundle` (banco + CSV + súmulas + diário +
  `manifest.sha256`)
- Endpoints públicos somente leitura `/api/public/events/{id}/results` e
  `/api/public/provas/{id}` com `Cache-Control: max-age=2` e ETag/304
- Página mobile-first `resultados.html` (provas, classificação, baterias,
  selos Oficial/Provisório/Retificado, busca) e QR code vendorizado na TV
- Privacidade por evento: `public_results_enabled` e `public_name_mode`
  (`full`/`initials`), editáveis na gestão e aplicados ao vivo via WS
  `settings_updated`; mascaramento nunca afeta súmulas, exportações, diário,
  snapshots ou gestão
- Migrações `0010_result_snapshot` e `0011_event_public_settings`

---

## [2.4.0] — 2026-10-22

### Added
- Tempo do toque: `finish`/`lap` (REST e WS) aceitam `client_ts` opcional;
  `effective_ts = clamp(client_ts, started_at, now)`, com `received_at` e
  `late` persistidos em `heat_lane`/`lap_event`
- Idempotência: `finish`/`lap` aceitam `op_id` opcional; resultado original é
  cacheado em `processed_op` e um `op_id` repetido retorna 200/ack sem efeito
  colateral
- Tabela `action_log` para toda ação que muda estado (`start`, `abort`,
  `finish_heat`, `finish`, `lap`, `dq`, `undo_lap`) com recebimento, tempo
  efetivo, evento/bateria/raia, `op_id`, IP e payload
- `GET /api/time` para sincronização de relógio do cliente
- WebSocket: ack explícito para `finish`/`lap` (`ack`/`error` com `op_id`) e
  heartbeat `ping`/`pong`
- Debounce de volta: `MIN_LAP_INTERVAL_S` (padrão 5 s) retorna
  `409 volta_duplicada` para toques repetidos na mesma raia
- Duração sem `client_ts` usa âncora `time.monotonic()` por bateria (fallback
  wall-clock após restart); `race_time_ms` quantizado para múltiplos de 10 ms
- Frontend: sincronização de relógio (3 amostras, menor RTT, a cada 30 s e na
  reconexão) com `serverNow()`; outbox gravada antes do envio, reenvio REST com
  o mesmo `op_id` após 3 s sem ack; lista visível de "registros rejeitados";
  heartbeat 5 s com reconexão em backoff `[500,1000,2000,3000,5000]`
- Migração `0007_time_ack_idempotencia`

### Changed
- `lap_event.recorded_at` passa a representar o tempo efetivo do toque; o
  instante de recebimento fica em `received_at`
- Cronômetros, janela de undo e countdowns usam `serverNow()` (fiscal,
  supervisor, público e home)
- `volta_duplicada` tratado como erro terminal no fiscal
- Versão da API em `2.4.0`

### Fixed
- Toques perdidos em silêncio: toda ação WebSocket de registro tem ack e a
  outbox só é limpa com ack/2xx; 4xx ficam visíveis como rejeitados
- Reenvios não duplicam mais voltas/chegadas (`op_id` + `processed_op`)
- Ranking coerente com o display `MM:SS.cc` (tempos exibidos iguais empatam)

---

## [2.3.0] — 2026-10-21

### Added
- Campo estruturado `prova.naipe` (`M`/`F`, opcional), separado de
  `prova.category` (categoria de idade); select **Naipe** (Feminino/Masculino/
  Não definido) no formulário de prova
- Migração `0006_prova_naipe` com backfill: extrai o naipe de categorias legadas
  ("masculino, sub-12" → naipe `M`, categoria `SUB-12`)
- Campo **"Ordem na prova"** no formulário de bateria, sugerindo a próxima ordem
  e rejeitando duplicatas dentro da mesma prova
- Endpoints batch transacionais `PUT /api/events/{id}/provas/order` e
  `PUT /api/provas/{id}/heats/order` (body `{ids:[...]}`)
- Aviso visual quando o naipe do atleta difere do naipe da prova (sem bloqueio)
- Testes de reordenação, naipe de prova, migração 0006 e lógica frontend

### Changed
- Drag-and-drop de provas/baterias reordena em **uma única chamada** (antes:
  sequência de PATCHes que falhava ao mover um item para baixo)
- Rótulos com contexto: accordion "Bateria N · nome" e visão geral "B1";
  formulário de prova com "Ordem no programa do evento"
- Mensagens de erro da gestão traduzidas para PT-BR e contextualizadas
- `prova.category` é normalizada (trim + maiúsculas), como a categoria de atleta

### Fixed
- Reordenação não colide mais com o índice único durante a operação
  (erro `order_num_duplicado` ao mover itens para baixo)
- Ordem de bateria pode se repetir entre provas diferentes (única por prova),
  coberta por teste de regressão

## [2.2.0] — 2026-10-21

### Added
- Entidade `Athlete` por evento (`athlete`): `name`, `team_id` opcional,
  `naipe` (M/F validado e normalizado) e `category` (normalizada em maiúsculas),
  com `created_at`/`updated_at` e unicidade por evento+nome+equipe
  (case-insensitive, `COALESCE` para atletas sem equipe)
- Migração `0005_athlete`: cria `athlete`, adiciona `heat_lane.athlete_id`
  (FK opcional, compatível com `participant_name` legado) e índices de busca
- API de atletas: CRUD + listagem paginada com filtros (`q`, `team_id`,
  `naipe`, `category`) e isolamento por evento
- Importação de planilhas CSV/XLSX (`NOME, EQUIPE, NAIPE, CATEGORIA`) com
  detecção de delimitador, suporte a BOM/Latin-1, aliases de naipe, criação
  automática de equipes, política parcial com relatório `{line, field, message}`
  e limites de 2 MB/1000 linhas
- Download de modelo (CSV/XLSX) e exportação CSV dos atletas do evento
- Aba **Atletas** na gestão: busca, filtros, paginação, edição/exclusão,
  importação por upload ou arrastar-e-soltar e relatório de importação
- Autocomplete de atletas cadastrados nas raias; ao selecionar, equipe é
  preenchida automaticamente (entrada manual continua suportada)
- `athlete_count` agregado em `GET /api/events/{id}/teams` e no payload do evento
- Evento WebSocket `athletes_changed` (scope `event`)
- Testes de atletas, importação (CSV/XLSX, 200 atletas, relatório parcial),
  migração 0005 com dados legados e lógica frontend (`gestao_logic`)

### Changed
- `configure_lanes`/`update_lane` aceitam `athlete_id`; nome e equipe da raia
  passam a ser derivados do atleta (fonte única de verdade) e sincronizados em
  `participant_name`/`team_id` para fiscal/supervisor/público
- Exclusão de equipe também é bloqueada quando há atletas vinculados (`409 equipe_em_uso`)
- Exclusão de evento remove atletas antes de equipes (integridade referencial)
- `GET /api/events/{id}/teams` e `EventDetail` agora incluem `athlete_count`
- Frontend: contagem por equipe usa agregação do backend; visão geral mostra
  atletas inscritos e atletas em raias separadamente

### Removed
- `POST /api/events/{id}/heats` (rota legada prova+bateria 1:1); use
  `POST /api/provas/{id}/heats`
- `POST /api/heats/{id}/finish-marathon` (alias duplicado; use `/finish`)
- `admin.html` e `dashboard.html` (descontinuados; gestão e `publico.html` cobrem)
- `RESET_PASSWORD` (configuração órfã sem endpoint)
- Schemas de resposta agora são vinculados às rotas de equipes/atletas

### Fixed
- Sincronização de nome/equipe da raia ao editar um atleta já alocado

## [2.1.0] — 2026-10-21

### Added
- Entidade persistente `Prova` (`prova`): pertence a um evento, agrupa baterias e
  guarda ordem, modalidade/estilo, distância, categoria, `consolidate_results`
  (padrão `true`) e `classification_criterion` (padrão `lowest_time`)
- `Heat.prova_id` obrigatório (FK + triggers no SQLite) e `Team.logo_url`
- API: `POST/GET /api/events/{id}/provas`, `GET/PATCH/DELETE /api/provas/{id}`,
  `POST/GET /api/provas/{id}/heats`, `GET /api/provas/{id}/classification`,
  `PATCH /api/teams/{id}` e upload/remoção de logo da equipe
- Classificação consolidada por menor tempo com posições de empate (1,2,2,4),
  desempate visual determinístico e distinção entre válidos, DQ, sem tempo e
  em andamento; classificação provisória até todas as baterias finalizarem
- Evento WebSocket `prova_state` (scope `prova`) e recuperação de estado na
  reconexão; `heat_state` e `ready_update` preservados
- Logos de equipe (PNG/JPEG/WebP, validação por magic bytes, limite 1 MB,
  armazenamento local em `backend/data/logos`, exibição 320×100 com
  `object-fit: contain`) em gestão, público e dashboard
- Testes de provas, classificação, migração 0003/0004, logos e concorrência
  entre raias/provas; script `backend/tests/load_test.py` com números medidos
  em `docs/audit/load_results.md`

### Changed
- `POST /api/events/{id}/heats` (compatibilidade) cria uma prova 1:1 por bateria;
  o fluxo novo é `POST /api/provas/{id}/heats`
- `order_num` de baterias é único por prova; `order_num` de provas é único por evento
- `GET /api/events` e listagens de provas carregam raias/voltas/equipes em lote
  (reduziu ~57 ms para ~23 ms em 160 raias no teste in-process)
- `admin.html` foi descontinuado e redireciona para `gestao.html`/`index.html`
- Equipe renomeada via `PATCH /api/teams/{id}` (removeu create+copiar+delete frágil)
- `fiscal` e `supervisor` exibem a prova no seletor/lista hierárquica

### Fixed
- Exclusão de equipe em uso retorna `409 equipe_em_uso` (preserva resultados)
- `PATCH /api/heats/{id}` agora usa lock e valida colisão de `order_num`
- `POST /api/lanes/{id}/ready` retorna o nome da equipe corretamente
- Dashboard ordena maratona por voltas e metros (antes só metros)
- `formatTenths` não mostra mais décimos sempre zerados

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
