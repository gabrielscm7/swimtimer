#!/usr/bin/env bash
echo "⏹ Encerrando SwimTimer..."
docker compose down
echo "✅ Servidor encerrado."
echo "🗃  Dados preservados em backend/data/swimtimer.db"

# Para tornar executável: chmod +x stop.sh
