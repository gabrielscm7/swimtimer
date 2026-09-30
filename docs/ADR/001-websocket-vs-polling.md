# ADR 001 — WebSocket vs Polling HTTP

**Data:** 2026-09-30  
**Status:** Aceito

---

## Contexto

O sistema v0.x usa polling HTTP: cada cliente faz uma requisição GET a cada 2 segundos para verificar se houve mudança de estado. Com 7 fiscais + dashboard + notebook = ~9 dispositivos, isso gera ~270 requisições/minuto. Em ambiente de piscina coberta (estrutura metálica, umidade alta, sinal Wi-Fi degradado), requisições frequentes aumentam a probabilidade de timeout e causam a "tela travada" relatada em produção.

## Decisão

Adotar WebSocket como protocolo de comunicação principal.

## Consequências

**Positivas:**
- Servidor empurra dados apenas quando o estado muda — elimina 95% do tráfego de rede
- Latência cai de ~2000ms (intervalo de polling) para < 100ms (push imediato)
- Conexões persistentes são mais resilientes a perda de pacote que requisições HTTP repetidas
- Um único canal WebSocket por cliente substitui múltiplas requisições

**Negativas / trade-offs:**
- Maior complexidade no servidor (gerenciamento de conexões ativas)
- Requer lógica de reconexão no cliente
- Não funciona em proxies HTTP que não suportam upgrade (irrelevante no cenário local)

## Alternativas consideradas

- **Server-Sent Events (SSE):** unidirecional (servidor → cliente), não permite que o fiscal envie o tap pelo mesmo canal. Descartado.
- **Polling com intervalo reduzido (500ms):** piora o problema, não resolve. Descartado.
- **Long polling:** complexo de implementar corretamente, latência imprevisível. Descartado.
