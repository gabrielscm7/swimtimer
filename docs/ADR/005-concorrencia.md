# ADR 005 — Concorrência e implantação suportada

**Data:** 2026-10-21
**Status:** Aceito

## Contexto
Fiscais registram resultados simultaneamente. O backend usa FastAPI assíncrono
com SQLite WAL e, hoje, um único worker uvicorn.

## Decisão
- Manter locks `asyncio` por bateria/prova para serializar transições no
  processo e reduzir erros de escrita no SQLite.
- Não confiar apenas no lock: adicionar restrições únicas no banco
  (`uq_lap_event_lane_number`, `uq_heat_prova_order`, `uq_prova_event_order`)
  e validar estado antes de gravar (`ja_finalizou`, `prova_nao_ativa`).
- Persistir antes de emitir WebSocket; respostas de conflito explícitas (409).
- Não adotar Redis/serviço externo: o ambiente é local/offline e a implantação
  suportada é um worker.

## Limitações
Com múltiplos workers/processos os locks em memória deixam de ser suficientes;
apenas as constraints do SQLite protegeriam contra duplicidade, e a contenção
de escrita seria alta. Para esse cenário, migrar para PostgreSQL (ou outro
banco com escrita concorrente) e reavaliar locks distribuídos. Isso não é
necessário para a operação atual.
