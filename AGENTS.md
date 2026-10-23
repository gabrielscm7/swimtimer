# AGENTS.md — SwimTimer

## Testes

Backend (não há venv no repo; usa Python 3.11 via `uv`):

```bash
cd backend
uv run --no-project --python 3.11 --with-requirements requirements.txt python -m pytest -q
```

Frontend (sem build step):

```bash
node --test frontend/tests/*.test.js
```

## Snapshot da API

```bash
cd backend
uv run --no-project --python 3.11 --with-requirements requirements.txt python -c \
  "import json; from app.main import app; json.dump(app.openapi(), open('/tmp/openapi.json','w'), sort_keys=True, indent=1)"
```

## Regras de arquitetura

- `app/main.py`: somente criação do app, lifespan, CORS, `include_router`, mounts.
- Direção de imports: `routers → services → core/database/models` (sem ciclos).
- `AsyncSessionLocal` deve ser resolvido em tempo de execução via
  `from . import database` + `database.AsyncSessionLocal()` (services/routers).
  Nunca importar o nome diretamente nesses módulos: os testes substituem
  `app.database.AsyncSessionLocal`.
- Routers usam `APIRouter()` sem `prefix`/`tags` e mantêm os nomes das funções
  de endpoint para não alterar o OpenAPI.
