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
# backups/       ← backups automáticos por evento
# journal/       ← diário NDJSON por evento
```

---

## Resultados públicos e QR

- A TV (`publico.html`) mostra um QR code apontando para
  `resultados.html?event=<id>`; aponte o celular para ele.
- A página `resultados.html?event=<id>` é mobile-first: provas → classificação
  (geral e por naipe) + baterias, com os selos **Oficial**, **Provisório** e
  **Retificado**, e busca por atleta ou equipe.
- Atualiza sozinha via WebSocket (e recarrega a cada 10 s como reserva).
- Nada de `action_log`, IPs ou motivos internos aparece nesses endpoints.

### Privacidade (opcional, por evento)

Na **Gestão → Resultados públicos**:

- **Publicar resultados**: liga/desliga a página e os endpoints
  `/api/public/...` (padrão: ligado). A TV continua funcionando.
- **Modo de nome**: `Nome completo` (padrão) ou `Iniciais` ("Maria S.").
  Vale ao vivo (mensagem WS `settings_updated`).
  Afeta **apenas** a TV e a página pública: súmulas, exportações, diário,
  snapshots e a gestão mantêm o nome completo.
- As configurações são somente leitura na página de resultados; a edição é
  feita na gestão.

### CRM/CSV e pacote do evento

- `GET /api/events/<id>/export/results.csv` — CSV (`;`, UTF-8 com BOM) com
  prova, bateria, raia, atleta, equipe, tempo, status, revisão e oficial.
- `POST /api/events/<id>/export/bundle` — ZIP com backup do banco, CSV,
  súmulas (HTML), diário NDJSON e `manifest.sha256`.
- `sumula.html?heat=<id>` — súmula imprimível de uma bateria (`Ctrl+P`).

---

## Backup contínuo

- O servidor faz backup do SQLite a cada `BACKUP_INTERVAL_MIN` (padrão 5 min)
  para eventos com atividade e **10 s após cada bateria finalizar** (debounce).
- Destino: `backend/data/backups/<event_id>/swimtimer_<data>.db` + sidecar
  `.sha256`.
- Retenção: 12 mais recentes + 1 por hora + o backup final (quando o evento é
  encerrado).
- `GET /api/status` expõe `last_backup_at`, `last_error` e `mirror_ok`; o
  supervisor mostra um aviso vermelho se o último backup tem mais de 15 min ou
  se o espelho falhou.
- **Pendrive (espelho):** monte o pendrive e configure
  `BACKUP_MIRROR_DIR=/app/mirror` no `.env`, descomentando o volume em
  `docker-compose.yml`. Cada backup é copiado e verificado por checksum; se o
  espelho falhar, o aviso vermelho aparece no supervisor.

### Restaurar um backup

```bash
./scripts/restore.sh backend/data/backups/<event_id>/swimtimer_XXXX.db
```

O script valida o `.sha256`, para o serviço, preserva o banco atual em
`swimtimer_pre_restore_<data>.db`, restaura com `sqlite3 .backup` e sobe o
serviço novamente. Se o checksum não conferir, nada é alterado.

### Verificar a auditoria

```bash
curl http://10.42.0.1:8080/api/events/<event_id>/audit/verify
# {"ok": true, "count": N}  ou  {"ok": false, "broken_id": "..."}
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
