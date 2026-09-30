# PRD — SwimTimer
**Versão:** 1.0  
**Data:** 2026-09-30  
**Autor:** Gabriel Menezes  
**Status:** Aprovado

---

## 1. Problema

Eventos de natação em contexto escolar, SESI e federações estaduais dependem de sistemas de cronometragem proprietários (Omega, FinishLynx) de alto custo, ou de controle manual em planilhas — com risco de erro, sem visibilidade em tempo real para o público e sem integração entre fiscal e painel de resultados.

O sistema atual (v0.x) resolve o caso de uso da Maratona Aquática com uma solução funcional, mas apresenta instabilidades de sincronização causadas por polling HTTP em rede Wi-Fi instável. Não suporta múltiplos eventos, cadastro de atletas ou gestão de baterias.

---

## 2. Usuários

| Perfil | Papel no sistema | Volume esperado |
|---|---|---|
| Operador-geral | Supervisor da prova: configura evento, dispara cronômetro, exporta resultados | 1 por evento |
| Fiscal | Registra chegada/virada por raia no celular | 1 por raia (até 8) |
| Público / Atletas | Visualiza ranking e parciais em tempo real no telão | Ilimitado (read-only) |
| Administrador | Cadastra eventos, equipes, atletas, balizamento | 1–3 por organização |

---

## 3. Objetivos do Produto

### Fase 1 (v1.0) — Estabilidade
- Substituir polling por WebSocket: atualizações em < 500ms
- Rodar de forma confiável em Linux local via hotspot do notebook
- Manter toda a funcionalidade do v0.x (Maratona Aquática / prova de metragem)
- Zero quedas durante um evento de 3 horas

### Fase 2 (v2.0) — Multi-Evento
- Suportar múltiplos eventos independentes
- Gestão de baterias com upload de balizamento
- Cadastro de equipes e atletas
- Cronômetro por bateria disparado pelo operador-geral
- Check de chegada por fiscal por raia

### Fase 3+ (backlog)
- Parciais e viradas para provas longas
- DNS / DNF / DQ
- Exportação de súmula em PDF
- Comparação com recordes
- QR Code por raia para acesso direto do fiscal
- Deploy Railway para eventos com internet

---

## 4. Fora do Escopo (v1.0 e v2.0)

- Cronometragem automática por sensor/touchpad eletrônico
- Integração com sistemas de federação nacionais
- App mobile nativo (iOS/Android)
- Transmissão ao vivo (streaming)
- Pagamento / inscrição online de atletas

---

## 5. Restrições

- **Hardware do evento:** notebook i5, 16GB RAM, NVMe, Ubuntu 22.04 LTS
- **Rede:** hotspot criado pelo próprio notebook via `nmcli` — sem dependência de roteador externo ou internet
- **Fiscais:** celulares pessoais dos fiscais, qualquer navegador mobile
- **Custo:** zero custo de infraestrutura para operação local
- **Offline-first:** o sistema deve funcionar sem internet em 100% das funcionalidades de operação de prova

---

## 6. Métricas de Sucesso

| Métrica | Meta v1.0 | Meta v2.0 |
|---|---|---|
| Latência fiscal → dashboard | < 500ms | < 300ms |
| Uptime durante evento | 100% | 100% |
| Tempo de setup no local | < 5 min | < 5 min |
| Fiscais simultâneos sem degradação | 8 | 8 |
| Recuperação após queda de rede | < 10s automático | < 5s automático |
