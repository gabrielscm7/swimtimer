#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATA_DIR="$SCRIPT_DIR/backend/data"
DB_FILE="$DATA_DIR/swimtimer.db"
PORT=8080

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "-> .env não encontrado, criando a partir de .env.example"
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
fi

mkdir -p "$DATA_DIR"
echo "-> Pasta de dados pronta: $DATA_DIR"

if [ -f "$DB_FILE" ]; then
  BACKUP="$DATA_DIR/backup_$(date +%Y%m%d_%H%M).db"
  cp "$DB_FILE" "$BACKUP"
  echo "-> Backup do banco criado: $(basename "$BACKUP")"
else
  echo "-> Banco ainda não existe, primeira execução sem backup"
fi

echo "-> Subindo containers (docker compose up --build -d)"
docker compose up --build -d

echo "-> Aguardando health check em http://localhost:$PORT/api/health"
for attempt in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    echo "-> Servidor respondeu ao health check"
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "!! Servidor não respondeu após 60 tentativas. Verifique: docker compose logs -f"
    exit 1
  fi
  sleep 1
done

echo ""
echo "SwimTimer rodando"
echo "Local:         http://localhost:$PORT"
echo "Rede hotspot:  http://10.42.0.1:$PORT"
echo ""
echo "Dashboard: http://10.42.0.1:$PORT/dashboard.html"
echo "Fiscal:    http://10.42.0.1:$PORT/fiscal.html"
echo "Admin:     http://10.42.0.1:$PORT/admin.html"
