const test = require("node:test");
const assert = require("node:assert/strict");

const {
  provaLabel,
  provaDescriptor,
  bateriaLabel,
  classificationHelp,
} = require("../static/common/labels.js");

test("provaLabel segue PROVA n · distancia estilo · naipe · categoria", () => {
  assert.equal(
    provaLabel({
      order_num: 3,
      name: "25 m Livre · Masculino · Sub-12",
    }),
    "PROVA 3 · 25 m Livre · Masculino · Sub-12"
  );
});

test("provaDescriptor gera rotulo quando a prova nao tem nome", () => {
  assert.equal(
    provaDescriptor({
      order_num: 2,
      stroke: "costas",
      distance_m: 50,
      naipe: "F",
      category: "ABERTA",
    }),
    "50 m Costas · Feminino · Aberta"
  );
});

test("bateriaLabel usa indice/total e omite nome redundante", () => {
  assert.equal(
    bateriaLabel({
      heat_index_in_prova: 2,
      heats_in_prova: 5,
      name: "Bateria 2",
    }),
    "BATERIA 2 de 5"
  );
  assert.equal(
    bateriaLabel(
      { heat_index_in_prova: 1, heats_in_prova: 3, name: "Bateria 1" },
      { includeProva: true, provaOrder: 3 }
    ),
    "BATERIA 1 de 3 · Prova 3"
  );
});

test("bateriaLabel preserva nome customizado", () => {
  assert.equal(
    bateriaLabel({
      heat_index_in_prova: 2,
      heats_in_prova: 5,
      name: "Final A",
    }),
    "BATERIA 2 de 5 · Final A"
  );
});

test("classificationHelp descreve consolidacao de grupo", () => {
  assert.equal(
    classificationHelp(true, 4),
    "Classificação consolidada de 4 baterias (menor tempo)"
  );
  assert.equal(
    classificationHelp(false, 4),
    "Classificação consolidada de 4 baterias (menor tempo)"
  );
});
