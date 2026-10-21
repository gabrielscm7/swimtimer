const test = require("node:test");
const assert = require("node:assert/strict");

const {
  athleteOptionLabel,
  athleteLabelIndex,
  naipeLabel,
  paginationInfo,
  buildAthleteQuery,
  importResultSummary,
  distinctCategories,
  nextHeatOrder,
  bateriaLabel,
  gestaoErrorMessage,
} = require("../static/gestao_logic.js");

test("athleteOptionLabel inclui equipe ou marca sem equipe", () => {
  assert.equal(
    athleteOptionLabel({ name: "Ana", team_name: "Leões" }),
    "Ana — Leões"
  );
  assert.equal(athleteOptionLabel({ name: "Bia" }), "Bia — Sem equipe");
});

test("athleteLabelIndex mapeia rotulo para atleta", () => {
  const athletes = [
    { id: "1", name: "Ana", team_name: "Leões" },
    { id: "2", name: "Ana", team_name: "Tubarões" },
  ];
  const index = athleteLabelIndex(athletes);
  assert.equal(index.get("Ana — Leões").id, "1");
  assert.equal(index.get("Ana — Tubarões").id, "2");
  assert.equal(index.get("Inexistente"), undefined);
});

test("naipeLabel traduz M e F", () => {
  assert.equal(naipeLabel("M"), "Masculino");
  assert.equal(naipeLabel("F"), "Feminino");
  assert.equal(naipeLabel(null), "—");
});

test("paginationInfo calcula paginas e limites", () => {
  assert.deepEqual(paginationInfo(200, 50, 0), {
    page: 1,
    pages: 4,
    hasPrev: false,
    hasNext: true,
  });
  assert.deepEqual(paginationInfo(200, 50, 150), {
    page: 4,
    pages: 4,
    hasPrev: true,
    hasNext: false,
  });
  assert.deepEqual(paginationInfo(0, 50, 0), {
    page: 1,
    pages: 1,
    hasPrev: false,
    hasNext: false,
  });
});

test("buildAthleteQuery omite filtros vazios", () => {
  const query = buildAthleteQuery({
    limit: 50,
    offset: 100,
    q: "",
    teamId: "t1",
    naipe: "F",
    category: "",
  });
  const params = new URLSearchParams(query);
  assert.equal(params.get("limit"), "50");
  assert.equal(params.get("offset"), "100");
  assert.equal(params.get("team_id"), "t1");
  assert.equal(params.get("naipe"), "F");
  assert.equal(params.has("q"), false);
  assert.equal(params.has("category"), false);
});

test("importResultSummary resume criados, equipes e erros", () => {
  const summary = importResultSummary({
    created_athletes: 12,
    created_teams: 2,
    skipped: 1,
    errors: [{ line: 3 }, { line: 5 }],
  });
  assert.match(summary, /12 atleta/);
  assert.match(summary, /2 equipe/);
  assert.match(summary, /1 linha/);
  assert.match(summary, /2 erro/);
  assert.equal(importResultSummary(null), "");
});

test("distinctCategories ordena e remove vazios", () => {
  const categories = distinctCategories([
    { category: "SUB-14" },
    { category: "SUB-12" },
    { category: null },
    { category: "SUB-12" },
  ]);
  assert.deepEqual(categories, ["SUB-12", "SUB-14"]);
});

test("nextHeatOrder sugere a proxima ordem dentro da prova", () => {
  assert.equal(nextHeatOrder([]), 1);
  assert.equal(nextHeatOrder([{ order_num: 1 }, { order_num: 3 }]), 4);
  assert.equal(nextHeatOrder([{ order_num: 5 }]), 6);
});

test("bateriaLabel inclui ordem e nome", () => {
  assert.equal(
    bateriaLabel({ order_num: 2, name: "Bateria 2" }),
    "Bateria 2 · Bateria 2"
  );
  assert.equal(bateriaLabel({ order_num: 1 }), "Bateria 1");
  assert.equal(bateriaLabel(null), "Bateria");
});

test("gestaoErrorMessage traduz codigos conhecidos", () => {
  assert.match(
    gestaoErrorMessage({ message: "order_num_duplicado" }),
    /ordem já está em uso/
  );
  assert.match(
    gestaoErrorMessage({ message: "ordem_ids_invalidos" }),
    /não corresponde/
  );
  assert.equal(
    gestaoErrorMessage({ message: "colunas_obrigatorias:EQUIPE,NAIPE" }),
    "Colunas obrigatórias ausentes: EQUIPE, NAIPE."
  );
  assert.equal(gestaoErrorMessage({ message: "algo_novo" }), "algo_novo");
  assert.equal(gestaoErrorMessage(null), "Erro inesperado.");
});
