const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const Labels = require("../static/common/labels.js");

function backendDomain() {
  const file = path.join(__dirname, "..", "..", "backend", "app", "domain.py");
  return fs.readFileSync(file, "utf8");
}

function tupleValues(source, name) {
  const match = source.match(
    new RegExp(`${name}\\s*=\\s*\\(([\\s\\S]*?)\\)`)
  );
  if (!match) throw new Error(`constante ${name} ausente`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]);
}

test("STROKES do backend e frontend sao identicos", () => {
  assert.deepEqual(
    tupleValues(backendDomain(), "STROKES"),
    Labels.STROKES
  );
});

test("CATEGORIES do backend e frontend sao identicas", () => {
  assert.deepEqual(
    tupleValues(backendDomain(), "CATEGORIES"),
    Labels.CATEGORIES
  );
});

test("crawl e livre sao estilos distintos", () => {
  assert.ok(Labels.STROKES.includes("crawl"));
  assert.ok(Labels.STROKES.includes("livre"));
  assert.equal(Labels.strokeLabel("crawl"), "Crawl");
  assert.equal(Labels.strokeLabel("livre"), "Livre");
});

test("categoria livre aparece como Cat. Livre", () => {
  assert.equal(Labels.categoryLabel("livre"), "Cat. Livre");
  assert.equal(Labels.categoryLabel("pre_mirim"), "Pré Mirim");
  assert.equal(Labels.categoryLabel("junior"), "Júnior");
});

test("nome gerado omite Cat. Livre e formata maratona", () => {
  assert.equal(
    Labels.generateProvaName({
      heat_type: "bateria",
      stroke: "crawl",
      distance_m: 25,
      naipe: "M",
      category: "livre",
    }),
    "25 m Crawl · Masculino"
  );
  assert.equal(
    Labels.generateProvaName({
      heat_type: "bateria",
      stroke: "livre",
      distance_m: 25,
      naipe: "F",
      category: "mirim",
    }),
    "25 m Livre · Feminino · Mirim"
  );
  assert.equal(
    Labels.generateProvaName({
      heat_type: "maratona",
      stroke: "peito",
      naipe: "MISTO",
      category: "livre",
      duration_s: 7200,
    }),
    "Maratona 2 h · Peito · Misto"
  );
});
