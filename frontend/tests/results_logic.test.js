const test = require("node:test");
const assert = require("node:assert/strict");

const {
  displayName,
  badgeLabel,
  normalize,
  laneStatusLabel,
  filterProvas,
} = require("../static/results_logic.js");

test("displayName mantem o nome completo no modo full", () => {
  assert.equal(displayName("Maria da Silva", "full"), "Maria da Silva");
  assert.equal(displayName("Maria da Silva"), "Maria da Silva");
});

test("displayName abrevia no modo initials", () => {
  assert.equal(displayName("Maria da Silva", "initials"), "Maria S.");
  assert.equal(displayName("Maria da Silva Souza", "initials"), "Maria S.");
  assert.equal(displayName("Ana", "initials"), "Ana");
  assert.equal(displayName("  João   dos   Santos  ", "initials"), "João S.");
  assert.equal(displayName(null, "initials"), null);
});

test("badgeLabel traduz os selos", () => {
  assert.equal(badgeLabel("official"), "Oficial");
  assert.equal(badgeLabel("provisional"), "Provisório");
  assert.equal(badgeLabel("corrected"), "Retificado");
  assert.equal(badgeLabel(null), "Provisório");
});

test("normalize remove acentos e caixa", () => {
  assert.equal(normalize("João D'Ávila"), "joao d'avila");
});

test("laneStatusLabel prioriza DQ/sem tempo", () => {
  assert.equal(laneStatusLabel({ classification_status: "dq" }), "DQ");
  assert.equal(
    laneStatusLabel({ classification_status: "no_time" }),
    "sem tempo"
  );
  assert.equal(
    laneStatusLabel({ classification_status: "valid", race_time_display: "01:02.30" }),
    "01:02.30"
  );
});

function _sampleProvas() {
  return [
    {
      id: "p1",
      name: "100 Livres",
      standings: [
        { participant_name: "Maria da Silva", team_name: "Equipe Azul" },
        { participant_name: "Ana Souza", team_name: "Equipe Verde" },
      ],
      excluded: [],
      standings_by_naipe: {
        F: [{ participant_name: "Maria da Silva", team_name: "Equipe Azul" }],
        M: [],
      },
      heats: [
        {
          id: "h1",
          name: "Bateria 1",
          lanes: [
            { participant_name: "Maria da Silva", team_name: "Equipe Azul" },
            { participant_name: "Ana Souza", team_name: "Equipe Verde" },
          ],
        },
      ],
    },
    {
      id: "p2",
      name: "50 Costas",
      standings: [{ participant_name: "Caio Lima", team_name: "Equipe Azul" }],
      excluded: [],
      standings_by_naipe: { F: [], M: [] },
      heats: [
        {
          id: "h2",
          name: "Bateria 1",
          lanes: [{ participant_name: "Caio Lima", team_name: "Equipe Azul" }],
        },
      ],
    },
  ];
}

test("filterProvas busca por atleta sem acento e caixa", () => {
  const result = filterProvas(_sampleProvas(), "joao");
  assert.equal(result.length, 0);
  const maria = filterProvas(_sampleProvas(), "MARIA");
  assert.equal(maria.length, 1);
  assert.equal(maria[0].id, "p1");
  assert.equal(maria[0].standings.length, 1);
  assert.equal(maria[0].heats[0].lanes.length, 1);
});

test("filterProvas busca por equipe e remove provas sem resultado", () => {
  const result = filterProvas(_sampleProvas(), "equipe azul");
  assert.deepEqual(
    result.map((prova) => prova.id),
    ["p1", "p2"]
  );
  assert.equal(result[0].standings.length, 1);
});

test("filterProvas sem busca devolve tudo", () => {
  assert.equal(filterProvas(_sampleProvas(), "").length, 2);
});
