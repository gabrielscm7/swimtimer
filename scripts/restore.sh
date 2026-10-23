#!/usr/bin/env bash
# Restaura um backup do SQLite com seguranca:
#   1) valida o checksum do sidecar .sha256
#   2) para o servico
#   3) preserva o banco atual (swimtimer_pre_restore_<data>.db)
#   4) restaura via sqlite3 .backup (copia consistente)
#   5) sobe o servico de novo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${DATA_DIR:-$REPO_ROOT/backend/data}"
DB_FILE="$DATA_DIR/swimtimer.db"

fail() {
  echo "❌ ERRO: $1" >&2
  exit 1
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Uso: $0 <arquivo-de-backup.db>"
  echo "O sidecar <arquivo>.sha256 precisa existir e conferir."
  exit 0
fi

BACKUP="${1:-}"
[ -n "$BACKUP" ] || fail "informe o arquivo de backup (uso: $0 <arquivo.db>)"
[ -f "$BACKUP" ] || fail "backup nao encontrado: $BACKUP"
SIDECAR="$BACKUP.sha256"
[ -f "$SIDECAR" ] || fail "checksum ausente: $SIDECAR"

echo "1/5 Validando checksum..."
(
  cd "$(dirname "$BACKUP")"
  sha256sum -c "$(basename "$SIDECAR")"
) || fail "checksum invalido — backup corrompido ou incompleto"

echo "2/5 Parando o servico..."
cd "$REPO_ROOT"
if command -v docker >/dev/null 2>&1; then
  docker compose down || fail "falha ao parar o servico"
else
  echo "   docker indisponivel — parando manualmente antes de continuar"
fi

echo "3/5 Preservando o banco atual..."
mkdir -p "$DATA_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
if [ -f "$DB_FILE" ]; then
  cp -p "$DB_FILE" "$DATA_DIR/swimtimer_pre_restore_$STAMP.db" \
    || fail "nao foi possivel preservar o banco atual"
fi

echo "4/5 Restaurando..."
rm -f "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$BACKUP" ".backup '$DB_FILE'" || fail "falha ao restaurar o banco"
else
  cp "$BACKUP" "$DB_FILE" || fail "falha ao copiar o backup"
fi

echo "5/5 Subindo o servico..."
if [ -x "$REPO_ROOT/start.sh" ]; then
  "$REPO_ROOT/start.sh" || fail "servico nao subiu"
else
  echo "   start.sh nao encontrado — inicie o servico manualmente"
fi

echo "✅ Restauracao concluida."
