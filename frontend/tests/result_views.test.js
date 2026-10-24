const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const modulePromise = import(
  pathToFileURL(
    path.join(__dirname, "..", "static", "common", "result_views.js")
  ).href
);

function entry(name, position, timeMs, naipe, extra = {}) {
  return {
    participant_name: name,
    position,
    race_time_ms: timeMs,
    race_time_display: timeMs == null ? "—" : `00:${timeMs / 1000}.00`,
    team_name: extra.team || null,
    team_logo_url: null,
    classification_status: extra.status || "valid",
    status: extra.laneStatus || "finished",
    tied: false,
    naipe,
  };
}

function classification(overrides = {}) {
  return {
    mixed_ranking: "overall",
    standings: [],
    standings_by_naipe: null,
    excluded: [],
    is_provisional: false,
    ...overrides,
  };
}

function heat(lanes, overrides = {}) {
  return {
    heat_type: "bateria",
    distance_m: 50,
    heat_lanes: lanes,
    result_snapshot: null,
    ...overrides,
  };
}

function lane(number, name, timeMs, extra = {}) {
  return {
    lane_number: number,
    participant_name: name,
    team: extra.team || null,
    team_logo_url: null,
    status: extra.status || "finished",
    finish_at: extra.finish === false ? null : 1,
    race_time_ms: timeMs,
    race_time_display: timeMs == null ? "—" : `00:${timeMs / 1000}.00`,
    speed_ms: extra.speed == null ? null : extra.speed,
    laps: extra.laps || 0,
    meters: extra.meters || 0,
  };
}

function count(html, pattern) {
  return (html.match(pattern) || []).length;
}

test("prova masculina renderiza uma unica tabela", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "M" },
    classification({
      standings: [entry("Ana", 1, 30000, "M")],
      standings_by_naipe: null,
    }),
    { variant: "table" }
  );
  assert.equal(count(html, /<table/g), 1);
  assert.doesNotMatch(html, /Feminino/);
  assert.doesNotMatch(html, /Masculino/);
});

test("prova misto com masculino e feminino renderiza tres tabelas", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "MISTO" },
    classification({
      mixed_ranking: "both",
      standings: [entry("Ana", 1, 30000, "F"), entry("Bia", 2, 31000, "M")],
      standings_by_naipe: {
        M: [entry("Bia", 1, 31000, "M")],
        F: [entry("Ana", 1, 30000, "F")],
      },
    }),
    { variant: "table" }
  );
  assert.equal(count(html, /<table/g), 3);
  assert.match(html, /Classificação geral/);
  assert.match(html, /Masculino/);
  assert.match(html, /Feminino/);
});

test("misto com apenas masculino nao renderiza tabela feminina vazia", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "MISTO" },
    classification({
      mixed_ranking: "both",
      standings: [entry("Bia", 1, 31000, "M")],
      standings_by_naipe: { M: [entry("Bia", 1, 31000, "M")], F: [] },
    }),
    { variant: "table" }
  );
  assert.equal(count(html, /<table/g), 2);
  assert.doesNotMatch(html, /Feminino/);
});

test("payload sem mixed_ranking nao multiplica tabelas", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "M" },
    {
      standings: [entry("Ana", 1, 30000, "M")],
      standings_by_naipe: { M: [], F: [] },
      excluded: [],
    },
    { variant: "table" }
  );
  assert.equal(count(html, /<table/g), 1);
  assert.doesNotMatch(html, /Feminino/);
});

test("prova M/F ignora payload inconsistente com ranking por naipe", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "F" },
    classification({
      mixed_ranking: "both",
      standings: [entry("Ana", 1, 30000, "F")],
      standings_by_naipe: {
        M: [entry("Bia", 1, 31000, "M")],
        F: [entry("Ana", 1, 30000, "F")],
      },
    }),
    { variant: "table" }
  );
  assert.equal(count(html, /<table/g), 1);
  assert.doesNotMatch(html, /Feminino/);
  assert.doesNotMatch(html, /Masculino/);
});

test("tabela vazia nunca e renderizada", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult({ naipe: "M" }, classification(), {
    variant: "table",
  });
  assert.equal(html, "");
});

test("tv fatia linhas entre secoes respeitando a janela", async () => {
  const { renderProvaResult } = await modulePromise;
  const rows = Array.from({ length: 6 }, (_, index) =>
    entry(`Atleta ${index + 1}`, index + 1, 30000 + index * 100, "M")
  );
  const html = renderProvaResult(
    { naipe: "M" },
    classification({ standings: rows }),
    { variant: "tv", window: { offset: 2, limit: 3 } }
  );
  const names = [...html.matchAll(/Atleta (\d+)/g)].map((m) => Number(m[1]));
  assert.deepEqual(names, [3, 4, 5]);
  assert.equal(count(html, /pub-trow/g), 3);
});

test("tv usa duas colunas 1-10 | 11-20 quando ha muitos atletas", async () => {
  const { renderProvaResult } = await modulePromise;
  const rows = Array.from({ length: 22 }, (_, index) =>
    entry(`Atleta ${index + 1}`, index + 1, 30000 + index * 100, "M")
  );
  const html = renderProvaResult(
    { naipe: "M" },
    classification({ standings: rows }),
    { variant: "tv", window: { offset: 0, limit: 20 } }
  );
  assert.equal(count(html, /class="pub-col"/g), 2);
  const names = [...html.matchAll(/Atleta (\d+)/g)].map((m) => Number(m[1]));
  assert.deepEqual(names.slice(0, 10), [
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
  ]);
  assert.deepEqual(names.slice(10), [
    11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
  ]);
  assert.equal(count(html, /pub-trow/g), 20);
});

test("tv nao repete secao de naipe vazio", async () => {
  const { renderProvaResult } = await modulePromise;
  const html = renderProvaResult(
    { naipe: "MISTO" },
    classification({
      mixed_ranking: "both",
      standings: [entry("Bia", 1, 31000, "M")],
      standings_by_naipe: { M: [entry("Bia", 1, 31000, "M")], F: [] },
    }),
    { variant: "tv" }
  );
  assert.match(html, /Masculino/);
  assert.doesNotMatch(html, /Feminino/);
});

test("resultado da bateria ordena por tempo e inclui em andamento e DQ", async () => {
  const { renderHeatResult } = await modulePromise;
  const html = renderHeatResult(
    heat([
      lane(1, "Lento", 32000),
      lane(2, "Rapido", 30000),
      lane(3, "Correndo", null, { finish: false, status: "active" }),
      lane(4, "Desclassificado", 29000, { status: "dq" }),
    ]),
    { variant: "tv" }
  );
  const names = [...html.matchAll(/pub-name">([^<]+)/g)].map((m) => m[1]);
  assert.deepEqual(names, ["Rapido", "Lento", "Correndo", "Desclassificado"]);
  assert.match(html, /DQ/);
});

test("resultado da bateria sem participantes nao renderiza tabela", async () => {
  const { renderHeatResult } = await modulePromise;
  assert.equal(renderHeatResult(heat([]), { variant: "tv" }), "");
  assert.equal(renderHeatResult(heat([]), { variant: "table" }), "");
});

test("tabela documental da bateria mostra raia, atleta, equipe, tempo e status", async () => {
  const { renderHeatResult } = await modulePromise;
  const html = renderHeatResult(
    heat([lane(2, "Bia", 31000, { team: "Leões" }), lane(1, "Ana", 30000)]),
    { variant: "table" }
  );
  assert.match(html, /<table class="res-table">/);
  assert.match(html, /Raia/);
  assert.match(html, /Leões/);
  assert.ok(html.indexOf("Ana") < html.indexOf("Bia"));
});

test("podio so aparece quando ha resultado", async () => {
  const { renderPodium } = await modulePromise;
  assert.equal(renderPodium(heat([])), "");
  const html = renderPodium(
    heat([
      lane(1, "Ana", 30000, { team: "Leões" }),
      lane(2, "Bia", 31000),
      lane(3, "Caio", 32000),
    ]),
    {}
  );
  assert.match(html, /pub-podium/);
  assert.match(html, /Ana/);
});
