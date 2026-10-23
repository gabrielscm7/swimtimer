# ADR 009 — Validação de inscrição em baterias

**Data:** 2026-10-22
**Status:** Aceito
**Revoga:** cláusula de naipe do [ADR-007](007-reorder-e-naipe.md) ("aviso
visual, sem bloqueio")

## Contexto

O ADR-007 introduziu `prova.naipe` e decidiu que atletas com naipe divergente
gerariam apenas **aviso visual** ao serem alocados em uma raia. No uso real
isso permitiu inscrições inválidas: atleta no naipe errado, atleta duplicado na
mesma prova (inclusive na mesma bateria) e atleta competindo em duas baterias
ativas ao mesmo tempo. A prova mista (naipe `MISTO`) também precisa de uma
regra explícita, já que M e F podem competir juntos.

## Decisão

### Bloqueio por padrão

As operações que inscrevem atletas passam a **bloquear** (não apenas avisar):

- `POST /api/heats/{heat_id}/lanes` (`configure_lanes`);
- `PATCH /api/lanes/{lane_id}` (`update_lane`);
- `PATCH /api/athletes/{athlete_id}` (alteração de naipe/categoria que
  invalide raias já ocupadas).

Regras e códigos:

| Regra | Status | Código |
| --- | --- | --- |
| Naipe do atleta ≠ naipe da prova | 422 | `naipe_incompativel` |
| Categoria do atleta ≠ categoria da prova (quando definida) | 422 | `categoria_incompativel` |
| Atleta já inscrito em outra bateria da mesma prova | 409 | `atleta_duplicado_na_prova: <bateria>` |
| Atleta duas vezes na mesma bateria | 409 | `atleta_duplicado_na_bateria` |
| Atleta em bateria `ready_check`/`active` de outra prova | 409 | `atleta_em_outra_bateria_ativa` |

Detalhes:

- Prova com `naipe = MISTO` aceita M e F na mesma bateria; as demais regras
  (categoria e duplicidade) continuam valendo.
- Prova com `naipe` nulo ("não definido") não valida naipe.
- Prova que define categoria exige categoria compatível — **atleta sem
  categoria também é bloqueado**.
- A validação considera o **estado final** da bateria após aplicar o payload,
  de modo que mover um atleta de raia dentro da mesma bateria continua
  permitido.
- Atleta em baterias agendadas de provas diferentes continua permitido; o
  bloqueio de "outra bateria ativa" protege a operação ao vivo.

### Override exclusivo do supervisor

As três operações aceitam `force=true` **e** `override_reason` (obrigatório),
desde que o header `X-Operator-Pin` corresponda a `OPERATOR_PIN`:

- `force=true` sem motivo → `422 override_reason_obrigatorio`;
- `force=true` sem `OPERATOR_PIN` configurado → `403
  override_requer_pin_do_supervisor` (nunca fica aberto a todos);
- PIN ausente/incorreto → `403 pin_do_supervisor_invalido`;
- override aceito → registra `action_log.action = "override_inscricao"` com
  motivo, códigos violados e atletas envolvidos.

Endpoints operados pelo fiscal (`ready`, `finish`, `lap`, `dq`) **não**
aceitam `force`; não fazem inscrição de atletas.

### Interface

A gestão exibe o erro e o botão **"Autorizar exceção (supervisor)"**, que pede
PIN e motivo e reenvia a operação com o override. O aviso visual do ADR-007 é
substituído por esse fluxo.

## Consequências

- Erros de inscrição deixam de ser silenciosos; a operação só prossegue com
  correção dos dados ou autorização explícita e auditável do supervisor.
- Provas mistas passam a ter regra clara e ranking configurável
  (`prova.mixed_ranking`: `overall` | `by_naipe` | `both`).
- O fluxo de importação de atletas não é afetado (o vínculo com provas ocorre
  na alocação de raias).
