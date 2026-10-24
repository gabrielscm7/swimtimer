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

Ops (scripts shell, sem framework):

```bash
bash tests/ops/test_ensure_env.sh
bash tests/ops/test_restore.sh
```

## Telão (seed + verificação visual)

Dependência só de dev (`backend/requirements-dev.txt`), instalada à parte:

```bash
uv run --no-project --python 3.11 --with-requirements backend/requirements-dev.txt \
  playwright install chromium
```

Seed de demonstração (8 equipes, prova masculina com 5 baterias × 7 raias,
prova MISTO com 2 baterias, tudo determinístico):

```bash
uv run --no-project --python 3.11 --with-requirements backend/requirements.txt \
  python scripts/seed_demo.py --db /tmp/swimtimer_demo.db
```

Verificação visual do telão (Playwright; sobe backend efêmero, percorre os
estados 1–8 em 1920×1080, 1366×768 e 1280×720 e salva capturas em
`docs/screenshots/`):

```bash
uv run --no-project --python 3.11 \
  --with-requirements backend/requirements.txt \
  --with-requirements backend/requirements-dev.txt \
  python scripts/tv_check.py
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
