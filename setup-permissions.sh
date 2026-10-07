#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x start.sh stop.sh hotspot.sh setup-permissions.sh scripts/ensure_env.sh
echo "✅ Permissões configuradas."
