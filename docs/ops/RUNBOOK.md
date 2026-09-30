# RUNBOOK — Dia do Evento
**SwimTimer v1.0**

Siga esta sequência. Tempo estimado do passo 1 ao sistema pronto: **5 minutos**.

---

## 30 minutos antes

### 1. Ligar o notebook e iniciar o hotspot

```bash
nmcli device wifi hotspot ssid "SwimTimer" password "swim2025" ifname wlan0
```

Confirma: `ip addr show | grep "10.42"` deve mostrar `10.42.0.1`

### 2. Iniciar o servidor

```bash
cd ~/swimtimer
./start.sh
```

O terminal mostra:
```
✅ Backup do banco criado: backup_2026-10-15_09-30.db
✅ SwimTimer rodando em http://10.42.0.1:8080
📺 Dashboard: http://10.42.0.1:8080/dashboard.html
📱 Fiscal:    http://10.42.0.1:8080/fiscal.html
⚙️  Admin:     http://10.42.0.1:8080/admin.html
```

### 3. Configurar a competição (admin)

- Abra `http://10.42.0.1:8080/admin.html` no notebook
- Crie ou selecione a competição do dia
- Confirme que equipes e raias estão configuradas

### 4. Abrir o dashboard no telão

- Conecte o HDMI na TV
- Abra `http://10.42.0.1:8080/dashboard.html` no Chrome
- Pressione F11 (tela cheia)
- Pressione F11 novamente para sair quando necessário

### 5. Orientar os fiscais

Cada fiscal:
1. Conecta o celular no Wi-Fi **SwimTimer** (senha: `swim2025`)
2. Abre o Chrome e digita: `http://10.42.0.1:8080/fiscal.html`
3. Seleciona o número da sua raia
4. Aguarda o sinal de início

---

## Durante o evento

### Iniciar a prova

- No admin: clique em **Iniciar** → cronômetro começa → fiscais habilitados

### Registrar chegada (fiscal)

1. Atleta chega → fiscal toca **REGISTRAR**
2. Flash verde = registrado com sucesso
3. Dashboard atualiza em < 1 segundo

### Desfazer erro (fiscal)

- Botão **DESFAZER** disponível por 30 segundos após o toque
- Após 30s: solicitar ao operador-geral via admin

### Monitorar conexões

- Badge **verde** no celular = online
- Badge **vermelho** = sem conexão → verificar Wi-Fi SwimTimer

---

## Encerrar o evento

```bash
# No terminal onde o servidor está rodando:
Ctrl+C

# Confirma que os dados estão salvos:
ls -la ~/swimtimer/data/
# swimtimer.db   ← banco com todos os dados
# backup_*.db    ← backups automáticos
```

---

## INCIDENT — Problemas e soluções

| Problema | Causa provável | Solução |
|---|---|---|
| Celular não acessa a URL | Não está na rede SwimTimer | Verificar Wi-Fi do celular |
| Badge vermelho em todos os fiscais | Servidor caiu | `./start.sh` no terminal |
| Servidor não sobe (`porta em uso`) | Processo anterior não encerrou | `docker compose down && ./start.sh` |
| Dashboard não atualiza | Navegador com WS bloqueado | Recarregar página (F5) |
| Hotspot sumiu | NetworkManager reiniciou | Repetir comando `nmcli device wifi hotspot...` |
| Dados perdidos após crash | Nunca — SQLite persiste em disco | Reiniciar servidor; dados já estão lá |
