# SwimTimer

Sistema de cronometragem para eventos de natação.  
Operação local em Linux, sem dependência de internet.

---

## Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** HTML + Vanilla JS
- **Comunicação:** WebSocket
- **Infra:** Docker Compose + Ubuntu 22.04 LTS

## Início rápido

```bash
cp .env.example .env
./start.sh
```

Acesse `http://localhost:8080`

## Documentação

| Documento | Descrição |
|---|---|
| [PRD](docs/PRD.md) | O quê e por quê |
| [SPEC](docs/SPEC.md) | Arquitetura e contratos técnicos |
| [ROADMAP](docs/ROADMAP.md) | Fases e milestones |
| [CHANGELOG](docs/CHANGELOG.md) | Histórico de versões |
| [SETUP](docs/ops/SETUP.md) | Configuração do ambiente |
| [RUNBOOK](docs/ops/RUNBOOK.md) | Operação no dia do evento |
| [ADR](docs/ADR/) | Decisões de arquitetura |

## Versão atual

`v2.2.0` — Gestão de equipes e atletas com importação de planilhas (CSV/XLSX)

Hierarquia: **Evento → Prova → Bateria → Raia/Atleta → Resultado**.
Atletas são cadastrados por evento (nome, equipe, naipe e categoria) e podem ser
selecionados nas raias; a importação de planilhas preenche toda a equipe de uma vez.
