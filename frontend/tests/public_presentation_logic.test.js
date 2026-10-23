const test = require("node:test");
const assert = require("node:assert/strict");

globalThis.Labels = require("../static/common/labels.js");

const {
  parseRef,
  refOf,
  resolveRef,
  configOf,
  eligibleSlides,
  nextProva,
  nextProvaLabel,
} = require("../static/public_presentation_logic.js");

function eventData(overrides = {}) {
  return {
    provas: [
      { id: "p1", name: "100 Livres", order_num: 1, status: "finished" },
      { id: "p2", name: "50 Costas", order_num: 2, status: "scheduled" },
      { id: "p3", name: "100 Peito", order_num: 3, status: "scheduled" },
    ],
    heats: [
      {
        id: "h1",
        prova_id: "p1",
        name: "Bateria 1",
        order_num: 1,
        event_seq: 1,
        heat_index_in_prova: 1,
        status: "finished",
      },
      {
        id: "h2",
        prova_id: "p2",
        name: "Bateria 1",
        order_num: 1,
        event_seq: 2,
        heat_index_in_prova: 1,
        status: "scheduled",
      },
      {
        id: "h3",
        prova_id: "p2",
        name: "Bateria 2",
        order_num: 2,
        event_seq: 3,
        heat_index_in_prova: 2,
        status: "scheduled",
      },
    ],
    presentation: {
      enabled: true,
      rotation: true,
      slide_duration_s: 15,
      show_next_prova: true,
      pinned_ref: null,
      slides: [
        { kind: "prova", target_id: "p1" },
        { kind: "bateria", target_id: "h1" },
        { kind: "prova", target_id: "p2" },
      ],
    },
    ...overrides,
  };
}

test("parseRef/refOf aceitam prova e bateria", () => {
  assert.deepEqual(parseRef("prova:p1"), { kind: "prova", targetId: "p1" });
  assert.deepEqual(parseRef("bateria:h1"), {
    kind: "bateria",
    targetId: "h1",
  });
  assert.equal(parseRef("x:1"), null);
  assert.equal(parseRef(null), null);
  assert.equal(refOf({ kind: "prova", target_id: "p1" }), "prova:p1");
});

test("resolveRef calcula label e elegibilidade", () => {
  const data = eventData();
  const prova = resolveRef("prova:p1", data);
  assert.equal(prova.label, "PROVA 1 · 100 Livres");
  assert.equal(prova.eligible, true);
  assert.equal(resolveRef("prova:p2", data).eligible, false);

  const heat = resolveRef("bateria:h1", data);
  assert.equal(heat.label, "BATERIA 1 · Prova 1");
  assert.equal(heat.eligible, true);
  assert.equal(resolveRef("bateria:h2", data).eligible, false);
});

test("configOf usa defaults e limita duração", () => {
  assert.equal(configOf({}).slide_duration_s, 15);
  assert.equal(
    configOf({ presentation: { slide_duration_s: 999 } }).slide_duration_s,
    60
  );
  assert.equal(
    configOf({ presentation: { slide_duration_s: 1 } }).slide_duration_s,
    5
  );
});

test("eligibleSlides ignora desabilitado e alvos ainda sem resultado", () => {
  const data = eventData();
  assert.deepEqual(
    eligibleSlides(data).map((slide) => slide.ref),
    ["prova:p1", "bateria:h1"]
  );
  data.presentation.enabled = false;
  assert.deepEqual(eligibleSlides(data), []);
});

test("nextProva aponta a próxima prova distinta com bateria agendada", () => {
  const data = eventData();
  const next = nextProva(data.heats, data.provas, data.heats[0]);
  assert.equal(next.prova.id, "p2");
  assert.equal(next.heat.id, "h2");
  assert.equal(nextProvaLabel(next), "Próxima prova: PROVA 2 · 50 Costas · BATERIA 1");
});

test("nextProva usa prova_order_num quando o heat não traz a prova", () => {
  const data = eventData();
  const next = nextProva(
    data.heats,
    data.provas,
    { prova_id: "desconhecida", prova_order_num: 1 }
  );
  assert.equal(next.prova.id, "p2");
});

test("nextProva retorna null quando não há próxima", () => {
  const data = eventData();
  const last = data.heats[2];
  assert.equal(nextProva(data.heats, data.provas, last), null);
});
