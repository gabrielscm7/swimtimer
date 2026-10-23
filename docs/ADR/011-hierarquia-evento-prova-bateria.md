# ADR 011 — Hierarquia Evento → Prova → Bateria e resultado em dois níveis

**Data:** 2026-10-23
**Status:** Parcialmente revogado por ADR-012

> **Revogado por ADR-012 (2026-10-23):** a definição da prova não é mais
> cadastrada (é derivada da bateria); `name_override`, `mixed_ranking`,
> `legacy_incomplete` e `consolidate_results` foram removidos; a herança
> prova → bateria foi invertida (bateria → grupo); a ordem do programa é única
> por evento. Permanecem válidos o resultado em dois níveis, as cores por
> nível e o evento de um único dia.

## Contexto

A entidade `Prova` já existia entre `Event` e `Heat`, mas a definição da prova
era opcional e ambígua: `stroke`, `distance_m`, `naipe` e `category` podiam ser
nulos; a distância e o tipo ficavam na bateria; e o nome era um texto livre.
Isso permitia provas duplicadas, baterias incoerentes com a prova e resultados
sem distinção clara entre o consolidado da prova e o resultado de cada bateria.

O produto passou a exigir a seguinte leitura (fonte da verdade):

- **EVENTO**: provas do mesmo dia, com várias equipes (ex.: Festival de Natação).
- **PROVA**: baterias do mesmo estilo, categoria e naipe (ex.: 25 m Livre
  Masculino).
- **BATERIA**: cada disputa; pode ser única ou compor a classificação da prova.

## Decisão

### 1. Definição obrigatória da prova

- `stroke` enum: `livre`, `costas`, `peito`, `borboleta`, `medley`.
- `distance_m` obrigatório quando `format=bateria`.
- `naipe` obrigatório: `M`, `F` ou `MISTO`.
- `category` obrigatória; `ABERTA` representa ausência de restrição etária.
- Unicidade por evento em `(stroke, distance_m, naipe, category)`, sem caixa →
  `409 prova_duplicada`. A checagem ocorre dentro do lock do evento.

### 2. Nome gerado com sobrescrita

- Sem sobrescrita (`name_override=false`), o nome é gerado:
  `25 m Livre · Masculino · Sub-12`.
- Um `name` explícito grava `name_override=true` e é preservado quando a
  definição muda.
- `name=null` limpa a sobrescrita e regenera o rótulo.

### 3. Formato e herança da bateria

- Nova coluna `prova.format` (`bateria`|`maratona`), com backfill pelas
  baterias existentes (qualquer bateria de bateria ⇒ `bateria`; apenas
  maratonas ⇒ `maratona`; sem baterias ⇒ `bateria`).
- A bateria herda `heat_type` e `distance_m` da prova.
- Criar/editar bateria com tipo ou distância divergente →
  `409 bateria_incompativel_com_prova`.
- Alterações de `format`/`distance_m` na prova sincronizam as baterias
  agendadas e são bloqueadas após o início da prova.

### 4. Provas legadas

- A migration `0014` adiciona `legacy_incomplete` e marca provas com campos
  nulos (ou distância ausente em formato bateria), sem alterar os dados.
- A gestão exibe aviso e exige a conclusão ao editar a definição.
- Ajustes operacionais (ordem, consolidação) continuam permitidos em provas
  legadas.

### 5. Resultado em dois níveis

- `build_classification` agrega somente baterias da mesma prova e usa a
  distância da prova.
- Bateria legada com distância divergente não entra no consolidado; é
  sinalizada em `warnings` e permanece visível em `battery_results`.
- A interface separa “Resultado da PROVA” (violeta) de “Resultados por
  BATERIA” (ciano), com chips, ícone e borda lateral — nunca apenas cor.
- Súmula e CSV identificam o nível em coluna própria.

### 6. Evento de um único dia

- `date` obrigatória em `YYYY-MM-DD` na criação e não pode ser anulada.
- Evento com mesmo nome e data gera aviso não bloqueante
  (`evento_mesmo_nome_data`).

## Consequências

- Dados novos ficam consistentes por construção; dados antigos continuam
  legíveis e são corrigidos de forma guiada.
- O frontend passa a depender de `frontend/static/common/labels.js` para um
  único padrão de rótulos em fiscal, supervisor, gestão, resultados, súmula e
  telão.
- O CSV muda de contrato: ganha a coluna `nivel` e linhas consolidadas de
  `PROVA`, além das linhas `BATERIA`.
- Tema do evento ganha `lvl_prova`/`lvl_bateria`, integrados à guarda de
  contraste existente.
- Testes de migrations cobrem backfill de formato, `legacy_incomplete` e
  downgrade.

## Evidências visuais

- `docs/examples/resultados-niveis.html` / `.png`
- `docs/examples/telao-niveis.html` / `.png`

Os exemplos mostram o card consolidado “Resultado da PROVA” em violeta e a
seção “Resultados por BATERIA” em ciano, além do selo da prova no topo e do
título “RESULTADO FINAL DA PROVA” no telão.
