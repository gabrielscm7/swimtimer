#!/usr/bin/env bash
# Testa scripts/ensure_env.sh em cenários de clone limpo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENSURE="$REPO_ROOT/scripts/ensure_env.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "❌ FALHOU: $1"
  exit 1
}

# 1) Cria .env a partir de .env.example
mkdir -p "$TMP/a/scripts"
cp "$ENSURE" "$TMP/a/scripts/"
cp "$REPO_ROOT/.env.example" "$TMP/a/.env.example"
bash "$TMP/a/scripts/ensure_env.sh" >/dev/null
[ -f "$TMP/a/.env" ] || fail "não criou .env"
grep -q "^DATABASE_URL=" "$TMP/a/.env" || fail ".env sem DATABASE_URL"

# 2) Não sobrescreve .env existente
echo "CUSTOM=1" >> "$TMP/a/.env"
bash "$TMP/a/scripts/ensure_env.sh" >/dev/null
grep -q "^CUSTOM=1$" "$TMP/a/.env" || fail "sobrescreveu .env existente"

# 3) Gera defaults quando .env.example não existe
mkdir -p "$TMP/b/scripts"
cp "$ENSURE" "$TMP/b/scripts/"
bash "$TMP/b/scripts/ensure_env.sh" >/dev/null
grep -q "^DATABASE_URL=" "$TMP/b/.env" || fail "não gerou defaults"

echo "✅ test_ensure_env.sh OK"
