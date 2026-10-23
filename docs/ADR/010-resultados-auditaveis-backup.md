# ADR 010 — Resultados auditáveis, diário e backup contínuo

**Data:** 2026-10-23
**Status:** Aceito

## Contexto

Os resultados de uma bateria podiam ser corrigidos (homologação e, em seguida,
DQ/reversões) sem deixar rastro do estado anterior. Exportações dependiam do
estado atual do banco; um crash ou corrupção poderia exigir restaurar um
backup manual. Também não havia uma forma pública, sem PIN, de acompanhar a
classificação no celular.

## Decisão

### Snapshot append-only e cadeia de hashes

- Cada revisão de uma bateria grava `result_snapshot` com payload canônico
  (`json.dumps(sort_keys=True, separators=(",", ":"))`), contendo bateria,
  raias, nome/equipe/naipe/categoria do atleta **no momento**, tempos, status e
  voltas. Dados desnormalizados: revisões antigas nunca mudam.
- `hash = sha256(prev_hash + payload_json)`; `prev_hash` é o hash da revisão
  anterior **do mesmo evento** (primeira linha usa 64 zeros). A cadeia é
  serializada por um lock asyncio por evento; o deploy é de um único worker
  (ADR 005), então o lock em memória basta.
- A tabela é append-only por triggers `BEFORE UPDATE`/`BEFORE DELETE` com
  `RAISE(ABORT)`. Nem a aplicação pode alterar revisões antigas.
- `GET /api/events/{id}/audit/verify` recalcula a cadeia e devolve o primeiro
  `broken_id` (hash, elo ou payload inconsistente).
- Revisão 1 (provisória) ao finalizar; nova revisão em correções pós-finish e
  na homologação (oficial). Correções do fluxo DQ/undo/reset chamam
  `record_revision` com `status=corrected` (contrato preparado para o fluxo de
  correções).

### Diário NDJSON

Toda linha de `action_log` e `result_snapshot` também é apendada em
`data/journal/<event_id>.ndjson` com `flush` + `fsync`. Falhas de I/O são
registradas e nunca interrompem a prova. O diário serve para auditoria externa
(cópia em papel/pendrive) e vai no pacote de exportação.

### Backup contínuo

- `sqlite3.Connection.backup()` em thread (cópia consistente mesmo com WAL e
  escritas em andamento), sidecar `.sha256`.
- Disparo 10 s após finalizar bateria (debounce por evento) e intervalo
  `BACKUP_INTERVAL_MIN` (padrão 5) para eventos com atividade.
- Retenção: 12 mais recentes + 1 por hora + final.
- Espelho opcional em pendrive (`BACKUP_MIRROR_DIR`) com verificação de
  checksum; `/api/status` expõe `last_backup_at`, `last_error`, `mirror_ok`.
- `scripts/restore.sh` valida o checksum, para o serviço, preserva o banco
  atual, restaura e sobe de novo.

### Resultados públicos e privacidade

- `/api/public/...` são somente leitura, sem PIN, com `Cache-Control:
  max-age=2` e ETag (304). Não expõem `action_log`, IPs, motivos internos nem
  nomes completos quando o modo é `initials` (mascaramento no servidor).
- `public_results_enabled` e `public_name_mode` são opcionais por evento e
  editáveis apenas na gestão (a página pública é somente leitura). Mudanças
  são propagadas por WS (`settings_updated`).
- **TV:** os endpoints públicos mascaram os dados; o telão também aplica
  `displayName()` na renderização, porque ele usa `heat_state` (que carrega o
  nome completo para a operação). Evolução possível: assinatura pública no WS
  com payload mascarado no servidor.

## Consequências

- Cada ação de resultado custa um INSERT extra + escrita fsync do diário
  (ordem de milissegundos), aceitável para o ritmo da prova.
- Revisões antigas não podem ser editadas nem apagadas; correções sempre
  acrescentam uma nova revisão.
- O backup usa thread própria e não bloqueia o event loop; durante escritas
  intensas pode haver retry interno do SQLite (`busy_timeout`).
- O modo `initials` é apenas de exibição: armazenamento, exportações e súmulas
  continuam completos.
