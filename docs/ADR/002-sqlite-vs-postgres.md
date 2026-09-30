# ADR 002 — SQLite vs PostgreSQL

**Data:** 2026-09-30  
**Status:** Aceito (revisão prevista no v2.0)

---

## Contexto

O sistema v1.0 opera localmente com até 8 fiscais simultâneos. O volume de dados é baixo: um evento de 3 horas com 8 raias gera no máximo ~2000 lap_events. A operação é local, sem acesso externo ao banco.

## Decisão

Usar SQLite para o v1.0.

## Justificativa

| Critério | SQLite | PostgreSQL |
|---|---|---|
| Configuração | Zero | Serviço separado, usuário, senha, porta |
| Backup | `cp swimtimer.db backup.db` | `pg_dump` + restore |
| Performance para escala local | Suficiente | Excessivo |
| Portabilidade | Arquivo único, copia junto com o projeto | Requer migração de dados |
| Complexidade operacional | Mínima | Adiciona um container e ponto de falha |

## Consequências

**Positivas:**
- `start.sh` sobe um único container
- Backup é trivial
- Sem risco de "banco não iniciou antes do app"

**Negativas:**
- Escritas concorrentes limitadas (WAL mode mitiga para o nosso caso)
- Migração necessária para PostgreSQL quando o sistema for multi-tenant/cloud (v2.0+)

## Ação futura

No v2.0, avaliar migração para PostgreSQL quando o deploy Railway for implementado e persistência cross-restart for necessária. A camada SQLAlchemy permite trocar o banco sem mudar o código da aplicação.
