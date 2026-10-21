# ADR 006 — Atletas como entidade por evento e importação parcial

**Data:** 2026-10-21
**Status:** Aceito

## Contexto

Até a v2.1, "atleta" não existia como entidade: cada raia guardava apenas
`participant_name` (texto livre) e `team_id`. O mesmo nome era redigitado em
cada bateria, sem naipe, categoria, histórico ou vínculo consistente com a
equipe. O ROADMAP previa cadastro individual de atletas, e o evento precisa
receber pelo menos 200 inscritos com estabilidade.

## Decisão

1. **Atleta pertence ao evento** (`athlete.event_id`), como `Team`. Eventos
   permanecem isolados; não há cadastro global multi-evento nesta versão.
2. **Separação de dados**: `athlete` é a fonte única de verdade para nome,
   equipe, naipe e categoria. `heat_lane.athlete_id` é opcional e, quando
   presente, a raia deriva nome/equipe do atleta. Para não quebrar os clientes
   que leem `participant_name` diretamente (fiscal/supervisor/público), a raia
   mantém uma cópia sincronizada em `participant_name`/`team_id` — atualizada a
   cada edição do atleta.
3. **Compatibilidade**: raias legadas sem atleta continuam funcionando via
   `participant_name` livre; nenhum backfill automático é feito (nomes livres
   não têm informação suficiente para virar atletas com segurança).
4. **Unicidade**: índice único em
   `(event_id, name COLLATE NOCASE, COALESCE(team_id, ''))` impede duplicatas
   por evento, inclusive para atletas sem equipe.
5. **Importação parcial**: planilhas CSV/XLSX são validadas linha a linha. As
   linhas válidas são gravadas em uma transação; as inválidas retornam
   `{line, field, message}` sem impedir o restante. Duplicatas são reportadas,
   não silenciosamente mescladas. Equipes ausentes são criadas
   automaticamente (comparação case-insensitive).

## Consequências

- Consultas de atletas são paginadas e filtradas no servidor; a UI não carrega
  200+ linhas de uma vez. Contagens por equipe são agregadas em SQL.
- O índice único é a rede de segurança contra importações concorrentes; o
  conflito retorna `409 importacao_conflito`.
- A cópia desnormalizada na raia exige sincronização explícita ao editar o
  atleta — coberta por teste (`test_lane_uses_athlete_and_stays_in_sync`).
- Excluir equipe com atletas passa a ser bloqueado (`409 equipe_em_uso`), assim
  como excluir atleta alocado em raia (`409 atleta_em_uso`).
- Um futuro cadastro multi-evento pode introduzir `athlete` global +
  `enrollment`, reaproveitando o mesmo contrato de importação.
