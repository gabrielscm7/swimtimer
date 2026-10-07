#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "⏹ Encerrando SwimTimer..."
docker compose down
echo "✅ Servidor encerrado."
echo "🗃  Dados preservados em backend/data/swimtimer.db"

# Para tornar executável: chmod +x stop.sh
