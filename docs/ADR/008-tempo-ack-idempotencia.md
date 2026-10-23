# ADR 008 — Tempo do toque, ack e idempotência

**Data:** 2026-10-22
**Status:** Aceito

## Contexto
O registro de chegadas/voltas usava o instante de recebimento no servidor como
tempo do resultado. Em rede Wi-Fi local isso introduz atraso (fila do socket,
reenvio, outbox offline) e faz o tempo depender do caminho, não do toque do
fiscal. Além disso:

- Ações via WebSocket não tinham confirmação (ack). Um toque podia ser perdido
  em silêncio quando a mensagem ou o ack se perdia.
- Reenvios (fallback REST após timeout, flush da outbox, retry de rede) podiam
  duplicar voltas/chegadas.
- Não havia trilha de auditoria de ações nem debounce contra toques repetidos.
- Tempos com frações de milissegundo diferentes exibiam o mesmo `MM:SS.cc`, mas
  ordenavam de forma distinta (ranking incoerente com o display).

## Decisão

### Tempo do toque
- `finish` e `lap` (REST e WebSocket) aceitam `client_ts` opcional, em base de
  tempo do servidor (sincronizada pelo cliente via `GET /api/time`).
- `effective_ts = clamp(client_ts, heat.started_at, now)`; sem `client_ts` usa
  o instante de recebimento. Persistimos `received_at` em `heat_lane` e
  `lap_event`, e `late=true` quando `now - effective_ts > 2 s`.
- Em `lap_event`, `recorded_at` passa a ser o tempo efetivo do toque (não o de
  recebimento); `received_at` guarda o recebimento.
- Sem `client_ts`, a duração usa uma âncora `time.monotonic()` por bateria,
  guardada em memória (`_mono_anchors`), imune a ajustes do relógio de parede.
  Após restart a âncora some e o cálculo cai para wall-clock (fallback
  explícito).
- `race_time_ms` é quantizado para centésimos: piso para múltiplo de 10 ms, de
  modo que dois tempos exibidos iguais empatam no ranking (1, 2, 2, 4).

### Idempotência
- `finish` e `lap` aceitam `op_id` opcional. O resultado bem-sucedido é gravado
  em `processed_op` (`op_id` PK) na mesma transação da ação. Um `op_id`
  repetido devolve o resultado original com 200/ack, sem efeito colateral.
- A checagem e a gravação acontecem dentro do lock da bateria, serializando
  reenvios concorrentes.

### Auditoria e debounce
- `action_log` registra toda ação que muda estado: `start`, `abort`,
  `finish_heat`, `finish`, `lap`, `dq`, `undo_lap` (recebimento, tempo efetivo,
  evento/bateria/raia, `op_id`, IP de origem, payload resumido).
- Debounce: a volta anterior mais recente (não desfeita) na mesma raia a menos
  de `MIN_LAP_INTERVAL_S` (padrão 5 s) do toque atual retorna
  `409 volta_duplicada`.

### WebSocket
- `finish`/`lap` respondem `{"type":"ack","op_id":...,"ok":true,"result":...}`
  ou `{"type":"error","op_id":...,"message":...}`.
- `{"type":"ping"}` → `{"type":"pong"}` para heartbeat.
- No cliente, toda ação de registro gera `op_id` e `client_ts` no instante do
  toque, entra na outbox antes do envio e só sai com ack/2xx. Sem ack em 3 s,
  reenvia por REST com o mesmo `op_id`. Erros 4xx viram lista visível de
  "registros rejeitados" (nunca descarte silencioso); rede/5xx permanecem na
  outbox.

## Limitações
- Implantação continua sendo **um worker uvicorn**: locks em memória e âncora
  monotônica não são compartilhados entre processos. Com múltiplos workers
  seria necessário banco com escrita concorrente e/ou persistir a âncora.
- `client_ts` depende do relógio do cliente sincronizado com o servidor; o
  clamp limita o dano de relógios adiantados/atrasados.
- A quantização de 10 ms é intencional e coerente com o display; não é
  cronometragem oficial de precisão.
