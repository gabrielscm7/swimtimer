const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const GESTAO_DIR = path.join(__dirname, "..", "static", "gestao");
const STATIC_DIR = path.join(__dirname, "..", "static");

function read(name) {
  return fs.readFileSync(name, "utf8");
}

function stateImports(source) {
  const match = source.match(/import\s+\{([^}]+)\}\s+from\s+"\.\/state\.js"/);
  if (!match) return [];
  return match[1].split(",").map((item) => item.trim());
}

test("modulos da gestao importam eventId quando usam eventId", () => {
  for (const name of fs.readdirSync(GESTAO_DIR)) {
    if (!name.endsWith(".js") || name === "state.js") continue;
    const source = read(path.join(GESTAO_DIR, name));
    if (!/\beventId\b/.test(source)) continue;
    assert.ok(
      stateImports(source).includes("eventId"),
      `${name} usa eventId sem importar de state.js`
    );
  }
});

test("gestaoErrorMessage e sempre acessado via GestaoLogic", () => {
  for (const name of fs.readdirSync(GESTAO_DIR)) {
    if (!name.endsWith(".js")) continue;
    const source = read(path.join(GESTAO_DIR, name));
    assert.ok(
      !/(?<!GestaoLogic\.)\bgestaoErrorMessage\s*\(/.test(source),
      `${name} chama gestaoErrorMessage sem o namespace GestaoLogic`
    );
  }
});

test("salvar raia individual nao converte UUID para Number", () => {
  const source = read(path.join(GESTAO_DIR, "main.js"));
  assert.match(source, /saveLane\(target\.dataset\.heat/);
  assert.doesNotMatch(source, /saveLane\(Number\(target\.dataset\.heat\)/);
});

test("publico nao referencia perBattery indefinido", () => {
  const source = read(path.join(STATIC_DIR, "publico.js"));
  assert.doesNotMatch(source, /\bperBattery\b/);
});

function htmlIds(htmlPath) {
  const source = fs.readFileSync(htmlPath, "utf8");
  const ids = new Set();
  for (const match of source.matchAll(/\bid="([^"]+)"/g)) ids.add(match[1]);
  return ids;
}

function referencedIds(jsPath) {
  const source = read(jsPath);
  return [...source.matchAll(/getElementById\("([^"]+)"\)/g)].map(
    (match) => match[1]
  );
}

test("paginas referenciam apenas IDs existentes", () => {
  const pages = [
    ["publico.html", ["static/publico.js"]],
    ["resultados.html", ["static/results.js"]],
    ["gestao.html", ["static/gestao/state.js"]],
    ["fiscal.html", ["static/fiscal.js"]],
    ["supervisor.html", ["static/supervisor.js"]],
  ];
  for (const [page, scripts] of pages) {
    const ids = htmlIds(path.join(__dirname, "..", page));
    for (const script of scripts) {
      for (const id of referencedIds(path.join(__dirname, "..", script))) {
        if (["toast", "pub-clock", "sup-clock"].includes(id)) continue;
        assert.ok(ids.has(id), `${script} referencia #${id} ausente em ${page}`);
      }
    }
  }
});
