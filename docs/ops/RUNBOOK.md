# RUNBOOK — Dia do Evento
**SwimTimer v1.0**

Siga esta sequência. Tempo estimado do passo 1 ao sistema pronto: **5 minutos**.

---

# Sequência de início (dia do evento)

## 1. Ativar hotspot (se necessário)
./hotspot.sh start

## 2. Iniciar o servidor
./start.sh
→ Escolher "s" para ver logs, ou "N" para liberar o terminal

## 3. Verificar acesso
Abrir http://10.42.0.1:8080 no notebook → deve carregar a Home

## 4. Compartilhar acesso com fiscais
Mostrar o QR Code exibido no terminal
OU passar a URL: http://10.42.0.1:8080/fiscal.html

## 5. Encerrar ao fim do evento
./stop.sh
./hotspot.sh stop

---

## Preparar a competição

### Configurar a competição (gestão)

- Abra `http://10.42.0.1:8080/gestao.html` no notebook
- Crie ou selecione a competição do dia
- Confirme que equipes e raias estão configuradas

### Abrir o painel público no telão

- Conecte o HDMI na TV
- Abra `http://10.42.0.1:8080/publico.html` no Chrome
- Pressione F11 (tela cheia)
- Pressione F11 novamente para sair quando necessário

---

## Durante o evento

### Iniciar a prova

- Na gestão: clique em **Iniciar** → cronômetro começa → fiscais habilitados

### Registrar chegada (fiscal)

1. Atleta chega → fiscal toca **REGISTRAR**
2. Flash verde = registrado com sucesso
3. Painel público atualiza em < 1 segundo

### Desfazer erro (fiscal)

- Botão **DESFAZER** disponível por 30 segundos após o toque
- Após 30s: solicitar ao operador-geral via gestão

### Monitorar conexões

- Badge **verde** no celular = online
- Badge **vermelho** = sem conexão → verificar Wi-Fi SwimTimer

---

## Encerrar o evento

```bash
./stop.sh
./hotspot.sh stop
```

Confirma que os dados estão salvos:

```bash
ls -la backend/data/
# swimtimer.db   ← banco com todos os dados
# backups/       ← backups automáticos (10 mais recentes)
```

---

## INCIDENT — Problemas e soluções

| Problema | Causa provável | Solução |
|---|---|---|
| Celular não acessa a URL | Não está na rede SwimTimer | Verificar Wi-Fi do celular |
| Badge vermelho em todos os fiscais | Servidor caiu | `./start.sh` no terminal |
| Servidor não sobe (`porta em uso`) | Processo anterior não encerrou | `docker compose down && ./start.sh` |
| Painel público não atualiza | Navegador com WS bloqueado | Recarregar página (F5) |
| Hotspot sumiu | NetworkManager reiniciou | `./hotspot.sh start` |
| Dados perdidos após crash | Nunca — SQLite persiste em disco | Reiniciar servidor; dados já estão lá |
