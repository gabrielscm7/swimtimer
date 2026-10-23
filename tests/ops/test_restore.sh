#!/usr/bin/env bash
# Testa scripts/restore.sh em sandbox (docker/start.sh simulados).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESTORE="$REPO_ROOT/scripts/restore.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "❌ FALHOU: $1"
  exit 1
}

setup_sandbox() {
  local root="$1"
  mkdir -p "$root/scripts" "$root/backend/data" "$root/bin"
  cp "$RESTORE" "$root/scripts/"
  cat > "$root/start.sh" <<'EOF'
#!/usr/bin/env bash
echo "start.sh" >> "${CALLS:?}"
EOF
  cat > "$root/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "${CALLS:?}"
EOF
  chmod +x "$root/start.sh" "$root/bin/docker"
}

make_backup() {
  local dir="$1"
  mkdir -p "$dir"
  sqlite3 "$dir/backup.db" \
    "CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO sample (name) VALUES ('ok');"
  (
    cd "$dir"
    sha256sum backup.db > backup.db.sha256
  )
}

# 1) Restauracao valida: para, preserva, restaura e sobe.
ROOT="$TMP/a"
setup_sandbox "$ROOT"
make_backup "$ROOT/bkp"
echo "banco antigo" > "$ROOT/backend/data/swimtimer.db"
export CALLS="$ROOT/calls"
: > "$CALLS"
PATH="$ROOT/bin:$PATH" bash "$ROOT/scripts/restore.sh" "$ROOT/bkp/backup.db" >/dev/null
grep -q "docker compose down" "$CALLS" || fail "nao parou o servico"
grep -q "start.sh" "$CALLS" || fail "nao subiu o servico"
sqlite3 "$ROOT/backend/data/swimtimer.db" "SELECT name FROM sample;" \
  | grep -q "^ok$" || fail "banco restaurado invalido"
ls "$ROOT/backend/data/"swimtimer_pre_restore_*.db >/dev/null 2>&1 \
  || fail "nao preservou o banco atual"

# 2) Checksum invalido: aborta antes de parar o servico.
ROOT="$TMP/b"
setup_sandbox "$ROOT"
make_backup "$ROOT/bkp"
printf 'lixo' >> "$ROOT/bkp/backup.db"
export CALLS="$ROOT/calls"
: > "$CALLS"
if PATH="$ROOT/bin:$PATH" bash "$ROOT/scripts/restore.sh" \
  "$ROOT/bkp/backup.db" >/dev/null 2>&1; then
  fail "restaurou backup com checksum invalido"
fi
[ ! -s "$CALLS" ] || fail "parou o servico antes de validar o checksum"

# 3) Sidecar ausente: aborta.
ROOT="$TMP/c"
setup_sandbox "$ROOT"
make_backup "$ROOT/bkp"
rm "$ROOT/bkp/backup.db.sha256"
export CALLS="$ROOT/calls"
: > "$CALLS"
if PATH="$ROOT/bin:$PATH" bash "$ROOT/scripts/restore.sh" \
  "$ROOT/bkp/backup.db" >/dev/null 2>&1; then
  fail "restaurou backup sem checksum"
fi
[ ! -s "$CALLS" ] || fail "parou o servico sem checksum"

echo "✅ test_restore.sh OK"
