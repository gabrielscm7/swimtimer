#!/usr/bin/env bash
# Garante a existência do arquivo .env antes de invocar o docker compose.
# Idempotente: nunca sobrescreve um .env já existente.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
EXAMPLE_FILE="$PROJECT_ROOT/.env.example"

if [ -f "$ENV_FILE" ]; then
  echo "✅ .env já existe."
  exit 0
fi

if [ -f "$EXAMPLE_FILE" ]; then
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  echo "📝 .env criado a partir de .env.example."
else
  cat > "$ENV_FILE" <<'EOF'
DATABASE_URL=sqlite+aiosqlite:///./data/swimtimer.db
RESET_PASSWORD=maratona2025
EOF
  echo "📝 .env gerado com valores padrão (.env.example ausente)."
fi
