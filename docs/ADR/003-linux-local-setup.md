# ADR 003 — Ambiente Linux Local vs Windows vs Cloud

**Data:** 2026-09-30  
**Status:** Aceito

---

## Contexto

O sistema precisa rodar de forma autônoma no local do evento, sem dependência de internet, em um notebook i5 16GB com SSD NVMe. Tentativas anteriores com Windows resultaram em:
- Hotspot Móvel exigindo conexão de internet ativa
- `netsh hostednetwork` falhando por limitação de driver
- Antivírus corporativo bloqueando pen drive
- Firewall do Windows bloqueando porta 8080 silenciosamente

## Decisão

Ubuntu 22.04 LTS instalado permanentemente no NVMe como sistema principal de desenvolvimento e operação de eventos.

## Justificativa

| Critério | Ubuntu 22.04 | Windows 11 | Cloud (Railway) |
|---|---|---|---|
| Hotspot sem internet | `nmcli` nativo, IP fixo | Exige internet ou falha | N/A |
| Docker | Nativo, sem VM | Roda em Hyper-V (overhead) | Nativo |
| Firewall | `ufw`, configuração explícita | Regras silenciosas, difícil debug | N/A |
| Custo | Zero | Zero | $0–$7/mês |
| Dependência de internet no evento | Zero | Zero | 100% |
| Reprodutibilidade | Alta (Docker) | Média | Alta |

## Consequências

**Positivas:**
- Hotspot via `nmcli device wifi hotspot` — funciona sem internet, IP sempre `10.42.0.1`
- Docker nativo — sem overhead de virtualização
- Controle total sobre rede e firewall
- Ambiente de desenvolvimento e produção idênticos

**Negativas:**
- Curva de aprendizado para uso cotidiano se Gabriel não usar Linux regularmente
- Compatibilidade de periféricos (impressora, etc) pode exigir configuração extra

## Configuração de referência

```bash
# Criar hotspot sem internet
nmcli device wifi hotspot ssid "SwimTimer" password "swim2025" ifname wlan0

# IP do notebook na rede hotspot: 10.42.0.1
# Fiscais acessam: http://10.42.0.1:8080

# Encerrar hotspot
nmcli connection down "Hotspot"
```
