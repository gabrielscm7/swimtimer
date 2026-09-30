# SETUP — Preparação do Ambiente
**Sistema:** Ubuntu 22.04 LTS | i5 16GB RAM | NVMe

Execute estes comandos uma única vez após instalar o Ubuntu.

---

## 1. Sistema base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget build-essential python3-pip
```

---

## 2. Docker

```bash
# Repositório oficial Docker
curl -fsSL https://get.docker.com | sh

# Adiciona seu usuário ao grupo docker (sem precisar de sudo)
sudo usermod -aG docker $USER

# Aplica a mudança de grupo sem precisar fazer logout
newgrp docker

# Confirma instalação
docker --version
docker compose version
```

---

## 3. Node.js (para OpenCode)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # deve ser 20+
```

---

## 4. OpenCode

```bash
npm install -g opencode-ai
opencode --version
```

---

## 5. Configuração do hotspot (testar antes do evento)

```bash
# Verifica se Wi-Fi está disponível
nmcli radio wifi

# Cria o hotspot (substitua wlan0 pelo seu adaptador se necessário)
nmcli device wifi hotspot ssid "SwimTimer" password "swim2025" ifname wlan0

# Confirma IP do notebook na rede hotspot
ip addr show | grep "10.42"
# Deve mostrar 10.42.0.1

# Testar: conecte um celular na rede SwimTimer
# e acesse http://10.42.0.1:8080 no browser
```

> **Nota:** O IP `10.42.0.1` é atribuído pelo NetworkManager automaticamente
> quando o hotspot é criado via nmcli. É sempre o mesmo — use este IP fixo
> nos materiais do evento.

---

## 6. Clonar o projeto

```bash
cd ~
git clone https://github.com/seu-usuario/swimtimer.git
cd swimtimer
cp .env.example .env
# Edite o .env com suas configurações
```

---

## 7. Primeira execução

```bash
chmod +x start.sh
./start.sh
```

Acesse `http://localhost:8080` para confirmar que o sistema está rodando.

---

## 8. Verificação final

```bash
# Tudo deve retornar OK
docker ps                          # container rodando
curl http://localhost:8080/api/health  # {"status": "ok"}
nmcli radio wifi                   # enabled
```
