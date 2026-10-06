#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8080
DATA_DIR="$SCRIPT_DIR/backend/data"
DB_FILE="$DATA_DIR/swimtimer.db"
BACKUP_DIR="$DATA_DIR/backups"
HOTSPOT_IP="10.42.0.1"

# ─── ETAPA 1: Verificações iniciais ───────────────────────────────
echo "🔎 Verificando ambiente..."

if ! docker info > /dev/null 2>&1; then
  echo "❌ Docker não está instalado ou não está em execução."
  echo "   Inicie o Docker e tente novamente."
  exit 1
fi

if [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then
  echo "❌ docker-compose.yml não encontrado no diretório atual."
  exit 1
fi

# ─── ETAPA 2: Backup do banco ─────────────────────────────────────
if [ -f "$DB_FILE" ]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP_NAME="swimtimer_$(date +%Y%m%d_%H%M%S).db"
  if cp "$DB_FILE" "$BACKUP_DIR/$BACKUP_NAME"; then
    echo "💾 Backup criado: backups/$BACKUP_NAME"
  fi
  # Manter apenas os 10 backups mais recentes
  ls -t "$BACKUP_DIR"/swimtimer_*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
else
  echo "ℹ️  Banco ainda não existe — primeira execução sem backup."
fi

# ─── ETAPA 3: Subir o servidor ────────────────────────────────────
# Verifica se a imagem já existe em cache local
IMAGE_NAME=$(docker compose config --images 2>/dev/null | head -1)
IMAGE_EXISTS=$(docker images -q "$IMAGE_NAME" 2>/dev/null)

if [ -n "$IMAGE_EXISTS" ]; then
  echo "✅ Imagem local encontrada — iniciando sem download..."
  docker compose up -d || { echo "❌ Falha ao subir containers."; exit 1; }
else
  echo "📦 Imagem não encontrada — construindo (requer internet)..."
  echo "   Isso acontece apenas na primeira execução."
  docker compose up --build -d || { echo "❌ Falha ao subir containers."; exit 1; }
  echo "✅ Imagem construída e salva em cache local."
  echo "   Próximas execuções não precisarão de internet."
fi

# ─── ETAPA 4: Health check em loop ────────────────────────────────
echo -n "⏳ Aguardando o servidor"
HEALTH_OK=false
for attempt in $(seq 1 30); do
  if curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    HEALTH_OK=true
    break
  fi
  echo -n "."
  sleep 1
done

if [ "$HEALTH_OK" != true ]; then
  echo ""
  echo "❌ Servidor não respondeu após 30 segundos."
  docker compose logs app || true
  exit 1
fi

echo ""
echo "✅ Servidor respondendo"

# ─── ETAPA 5: Descobrir IPs ───────────────────────────────────────
LOCAL_IP=$(ip route get 1 2>/dev/null | grep -oP 'src \K\S+' | head -1 || true)
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP="localhost"
fi

if ip addr show 2>/dev/null | grep -q "10.42.0.1"; then
  HOTSPOT_ATIVO=true
else
  HOTSPOT_ATIVO=false
fi

# IP principal exibido nas URLs e no QR Code
if [ "$HOTSPOT_ATIVO" = true ]; then
  DISPLAY_IP="$HOTSPOT_IP"
else
  DISPLAY_IP="$LOCAL_IP"
fi

# ─── ETAPA 6: Exibir informações ──────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  🏊  SwimTimer — Servidor de Produção"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  ✅  Servidor rodando na porta $PORT"
echo ""
echo "  ── Acesso pela rede local ──────────────────────"
echo "  🌐  http://$LOCAL_IP:$PORT"
echo ""
echo "  ── Acesso via Hotspot ──────────────────────────"
if [ "$HOTSPOT_ATIVO" = true ]; then
  echo "  📡  Hotspot ATIVO — http://$HOTSPOT_IP:$PORT"
else
  echo "  ⚪  Hotspot inativo  (veja: ./hotspot.sh start)"
fi
echo ""
echo "  ── URLs por perfil ─────────────────────────────"
echo "  🏠  Home:       http://$DISPLAY_IP:$PORT"
echo "  ⚙️   Gestão:     http://$DISPLAY_IP:$PORT/gestao.html"
echo "  👁️   Supervisor: http://$DISPLAY_IP:$PORT/supervisor.html"
echo "  📺  Público:    http://$DISPLAY_IP:$PORT/publico.html"
echo "  📱  Fiscal:     http://$DISPLAY_IP:$PORT/fiscal.html"
echo ""
echo "  ── Dados ───────────────────────────────────────"
echo "  🗃️   Banco:    backend/data/swimtimer.db"
echo "  📋  Logs:     docker compose logs -f app"
echo "  ⏹️   Encerrar: docker compose down"
echo ""
echo "═══════════════════════════════════════════════════"

# ─── ETAPA 7: QR Code do endereço principal ───────────────────────
if python3 -c "import qrcode" >/dev/null 2>&1; then
  QR_IP="$DISPLAY_IP" python3 - <<'PYEOF' || true
import os
import qrcode
import qrcode.constants

url = "http://%s:8080/fiscal.html" % os.environ["QR_IP"]
qr = qrcode.QRCode(
    error_correction=qrcode.constants.ERROR_CORRECT_L,
    box_size=1, border=1
)
qr.add_data(url)
qr.make(fit=True)
print("\n  QR Code para os fiscais (/fiscal.html):\n")
qr.print_ascii(invert=True)
print("\n  %s\n" % url)
PYEOF
else
  echo "  (instale qrcode para exibir QR: pip install qrcode)"
fi

# ─── ETAPA 8: Acompanhar logs ─────────────────────────────────────
echo ""
read -r -p "Acompanhar logs em tempo real? [s/N]: " resposta
case "$resposta" in
  s|S)
    docker compose logs -f app
    ;;
  *)
    echo "ℹ️  Servidor continua rodando em background. Encerre com ./stop.sh"
    ;;
esac

# Para tornar executável: chmod +x start.sh
