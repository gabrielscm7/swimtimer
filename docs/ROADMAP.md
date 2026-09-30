# ROADMAP — SwimTimer
**Atualizado:** 2026-09-30

---

## Versão 1.0 — Fundação Estável

**Objetivo:** mesmo produto do v0.x, infraestrutura confiável.  
**Critério de conclusão:** 3 horas de teste contínuo com 7 fiscais sem queda ou atraso perceptível.

### M1.1 — Ambiente de desenvolvimento
- [ ] Ubuntu 22.04 instalado no NVMe
- [ ] Docker + Docker Compose instalados
- [ ] Repositório Git inicializado
- [ ] Estrutura de pastas criada conforme SPEC
- [ ] `.env.example` documentado
- [ ] `docker-compose.yml` com serviço único (backend + static files)

**Saída:** `docker compose up` sobe o servidor. `curl http://localhost:8080/api/health` retorna 200.

---

### M1.2 — Backend FastAPI + SQLite
- [ ] FastAPI com rota `/api/health`
- [ ] SQLAlchemy + SQLite com todos os modelos (Competition, Team, Lane, LapEvent)
- [ ] Migration inicial (Alembic ou script SQL direto)
- [ ] CRUD de Competition via REST
- [ ] CRUD de Team e Lane via REST
- [ ] Rota `POST /api/lane/{id}/lap` registrando com timestamp do servidor
- [ ] Rota `DELETE /api/lane/{id}/lap/last` com validação de 30s

**Saída:** testes `pytest tests/test_api.py` passando com cobertura dos endpoints principais.

---

### M1.3 — WebSocket e tempo real
- [ ] `ws_manager.py` com broadcast para todos os clientes conectados
- [ ] Endpoint `ws://host/ws` funcional
- [ ] Mensagem `state` enviada na conexão e após qualquer mutação
- [ ] Mensagem `lap` enviada após cada registro
- [ ] Mensagem `tick` enviada a cada segundo quando cronômetro ativo
- [ ] Cronômetro gerenciado por `asyncio.create_task` no servidor
- [ ] Teste de WebSocket com `pytest-asyncio`

**Saída:** abrir dois navegadores, registrar lap em um, confirmar que o outro atualiza em < 1s.

---

### M1.4 — Frontend (fiscal + dashboard + admin)
- [ ] `fiscal.html`: seleção de raia, botão de chegada, botão desfazer, indicador online/offline, reconexão automática
- [ ] `dashboard.html`: ranking em tempo real, cronômetro, status de cada raia
- [ ] `admin.html`: criar competição, cadastrar equipes, atribuir raias, iniciar/pausar/zerar
- [ ] Reconexão WebSocket com exponential backoff nos três frontends
- [ ] Badge visual de status de conexão (verde/vermelho)

**Saída:** fluxo completo operando — admin cria competição, fiscal registra chegada, dashboard atualiza.

---

### M1.5 — Infraestrutura Linux e hotspot
- [ ] `start.sh` com: backup do banco, `docker compose up`, exibição do IP e URL
- [ ] Configuração do hotspot via `nmcli` documentada no `ops/SETUP.md`
- [ ] IP fixo do hotspot configurado (`10.42.0.1`)
- [ ] Teste com 3+ celulares reais conectados via hotspot
- [ ] `ops/RUNBOOK.md` com passo a passo do dia do evento
- [ ] `ops/INCIDENT.md` com procedimentos de recuperação

**Saída:** boot do notebook, `./start.sh`, 3 celulares conectados ao hotspot acessando o sistema — tudo funcional em menos de 5 minutos.

---

### M1.6 — Validação final v1.0
- [ ] Teste de carga: 7 fiscais registrando simultaneamente (script simulado)
- [ ] Teste de resiliência: desconectar e reconectar um fiscal — dados não perdidos
- [ ] Teste de duração: 3 horas rodando sem intervenção
- [ ] Revisão do `CHANGELOG.md`
- [ ] Tag `v1.0.0` no Git

---

## Versão 2.0 — Multi-Evento (backlog)

Itens a detalhar após conclusão do v1.0:

- Estrutura de múltiplos eventos independentes
- Upload de balizamento (CSV)
- Cadastro de equipes e atletas
- Configuração visual por evento (logo, cores, banner)
- Gestão de baterias com cálculo de voltas automático
- Parciais e viradas para provas longas
- Tela de programa (próximas baterias)

---

## Versão 3.0+ — Backlog avançado

- DNS / DNF / DQ com confirmação dupla
- Correção manual de tempo (árbitro com auditoria)
- Comparação com recordes em tempo real
- Exportação de súmula em PDF
- QR Code por raia
- PWA offline-first para fiscais
- Deploy Railway para eventos com internet
- API pública de resultados
