const test = require("node:test");
const assert = require("node:assert/strict");

const {
  heatsSorted,
  nextScheduledAfter,
  lastFinished,
  nextInProva,
  nextProvaAfter,
  provaHeaderLabel,
} = require("../static/sequence_logic.js");

// Cenario A1/A2/B1/B2: order_num reinicia por prova (A1=1, A2=2, B1=1, B2=2).
const provas = [
  { id: "A", order_num: 1, name: "Prova A" },
  { id: "B", order_num: 2, name: "Prova B" },
];

function scenario() {
  return [
    {
      id: "b2",
      prova_id: "B",
      order_num: 2,
      event_seq: 4,
      heat_index_in_prova: 2,
      heats_in_prova: 2,
      prova_order_num: 2,
      prova_name: "Prova B",
      status: "scheduled",
    },
    {
      id: "a1",
      prova_id: "A",
      order_num: 1,
      event_seq: 1,
      heat_index_in_prova: 1,
      heats_in_prova: 2,
      prova_order_num: 1,
      prova_name: "Prova A",
      status: "finished",
    },
    {
      id: "a2",
      prova_id: "A",
      order_num: 2,
      event_seq: 2,
      heat_index_in_prova: 2,
      heats_in_prova: 2,
      prova_order_num: 1,
      prova_name: "Prova A",
      status: "scheduled",
    },
    {
      id: "b1",
      prova_id: "B",
      order_num: 1,
      event_seq: 3,
      heat_index_in_prova: 1,
      heats_in_prova: 2,
      prova_order_num: 2,
      prova_name: "Prova B",
      status: "scheduled",
    },
  ];
}

test("heatsSorted usa event_seq, nao order_num isolado", () => {
  const heats = scenario();
  assert.deepEqual(
    heatsSorted(heats).map((heat) => heat.id),
    ["a1", "a2", "b1", "b2"]
  );
  // order_num isolado mistura provas (nao e a sequencia canonica).
  const byOrderNum = [...heats]
    .sort((a, b) => a.order_num - b.order_num)
    .map((heat) => heat.id);
  assert.notDeepEqual(byOrderNum, ["a1", "a2", "b1", "b2"]);
  assert.equal(byOrderNum[0], "a1");
  assert.equal(byOrderNum[1], "b1");
});

test("proxima bateria apos A1 e A2 e depois B1 (nunca 'nenhuma')", () => {
  const heats = scenario();
  assert.equal(nextScheduledAfter(heats, 1).id, "a2");
  assert.equal(nextScheduledAfter(heats, 2).id, "b1");
  assert.equal(nextScheduledAfter(heats, 3).id, "b2");
  assert.equal(nextScheduledAfter(heats, 4), null);
});

test("lastFinished usa event_seq", () => {
  const heats = scenario();
  assert.equal(lastFinished(heats).id, "a1");
  heats.find((heat) => heat.id === "b1").status = "finished";
  assert.equal(lastFinished(heats).id, "b1");
});

test("nextInProva respeita os limites da prova", () => {
  const heats = scenario();
  const a1 = heats.find((heat) => heat.id === "a1");
  const a2 = heats.find((heat) => heat.id === "a2");
  assert.equal(nextInProva(heats, a1).id, "a2");
  assert.equal(nextInProva(heats, a2), null);
});

test("nextProvaAfter aponta a proxima prova com bateria agendada", () => {
  const heats = scenario();
  const a2 = heats.find((heat) => heat.id === "a2");
  const next = nextProvaAfter(heats, provas, a2);
  assert.equal(next.prova.id, "B");
  assert.equal(next.heat.id, "b1");
  const b2 = heats.find((heat) => heat.id === "b2");
  assert.equal(nextProvaAfter(heats, provas, b2), null);
});

test("provaHeaderLabel monta 'Prova X · Bateria i de N'", () => {
  const heats = scenario();
  const a2 = heats.find((heat) => heat.id === "a2");
  assert.equal(
    provaHeaderLabel(a2),
    "Prova 1 · Prova A · Bateria 2 de 2"
  );
  assert.equal(provaHeaderLabel(null), "");
});
