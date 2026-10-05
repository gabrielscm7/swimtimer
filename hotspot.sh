#!/usr/bin/env bash
set -euo pipefail

# ── Configurações (editáveis) ─────────────────────────────────────
SSID="SwimTimer"
PASSWORD="swim2025"
INTERFACE=""

HOTSPOT_IP="10.42.0.1"

# ── Detecção automática da interface Wi-Fi ────────────────────────
if [ -z "$INTERFACE" ]; then
  INTERFACE=$(nmcli device 2>/dev/null | grep wifi | grep -v p2p | awk '{print $1}' | head -1 || true)
fi

usage() {
  echo "Uso: $0 {start|stop|status}"
  exit 1
}

CMD="${1:-}"
if [ -z "$CMD" ]; then
  usage
fi

case "$CMD" in
  start)
    if [ -z "$INTERFACE" ]; then
      echo "❌ Adaptador Wi-Fi não encontrado."
      exit 1
    fi

    echo "📡 Criando hotspot \"$SSID\" na interface $INTERFACE..."
    nmcli device wifi hotspot \
      ssid "$SSID" \
      password "$PASSWORD" \
      ifname "$INTERFACE"

    sleep 2

    if ip addr show 2>/dev/null | grep -q "10.42.0.1"; then
      echo ""
      echo "✅ Hotspot ativo"
      echo "📡 Rede: $SSID"
      echo "🔑 Senha: $PASSWORD"
      echo "🌐 IP do servidor: http://$HOTSPOT_IP:8080"
    else
      echo "❌ Hotspot não subiu corretamente."
      echo "   Verifique o adaptador Wi-Fi ($INTERFACE) e tente novamente."
      exit 1
    fi
    ;;

  stop)
    nmcli connection down "Hotspot" 2>/dev/null || \
    nmcli connection down "$SSID" 2>/dev/null || true
    echo "⏹ Hotspot encerrado"
    ;;

  status)
    if ip addr show 2>/dev/null | grep -q "10.42.0.1"; then
      CLIENTS=$(nmcli connection show --active 2>/dev/null | grep -i -c "$SSID" || true)
      echo "📡 Hotspot ATIVO — IP: $HOTSPOT_IP"
    else
      echo "⚪ Hotspot inativo"
    fi
    ;;

  *)
    usage
    ;;
esac

# Para tornar executável: chmod +x hotspot.sh
