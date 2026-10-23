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

`v2.6.0` — Resultados internos e apresentação curada no telão

Hierarquia: **Evento → Prova → Bateria → Raia/Atleta → Resultado**.
Provas têm ordem única no programa do evento; baterias têm ordem única dentro da
própria prova (reinicia em 1). O naipe da prova (Masculino/Feminino) é separado
da categoria de idade.
