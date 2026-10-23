const test = require("node:test");
const assert = require("node:assert");

const { isTerminalError, applyLaneUpdate } = require("../static/fiscal_logic.js");

test("erro de rede (sem status) é reprocessável", () => {
  assert.equal(isTerminalError(new Error("Failed to fetch")), false);
  assert.equal(isTerminalError(null), false);
});

test("erros 5xx são reprocessáveis", () => {
  const error = new Error("boom");
  error.status = 500;
  assert.equal(isTerminalError(error), false);
});

test("erros 4xx são definitivos", () => {
  for (const status of [400, 404, 409]) {
    const error = new Error("x");
    error.status = status;
    assert.equal(isTerminalError(error), true, `status ${status}`);
  }
});

test("erros definitivos por mensagem quando não há status", () => {
  assert.equal(
    isTerminalError({ message: "prova_nao_ativa" }),
    true
  );
  assert.equal(
    isTerminalError({ message: "nao_e_maratona" }),
    true
  );
  assert.equal(
    isTerminalError({ message: "erro desconhecido" }),
    false
  );
});

test("volta_duplicada é erro terminal (debounce do servidor)", () => {
  assert.equal(isTerminalError({ message: "volta_duplicada" }), true);
  const error = new Error("volta_duplicada");
  error.status = 409;
  assert.equal(isTerminalError(error), true);
});

test("applyLaneUpdate mescla campos no objeto da raia", () => {
  const lane = { id: "1", status: "active", laps: 0 };
  const result = applyLaneUpdate(lane, { status: "finished", laps: 3 });
  assert.equal(result, lane);
  assert.equal(lane.status, "finished");
  assert.equal(lane.laps, 3);
});

test("codigos de bateria sao terminais durante a transicao", () => {
  for (const message of [
    "bateria_nao_ativa",
    "bateria_nao_iniciada",
    "bateria_nao_encontrada",
    "bateria_nao_esta_em_ready_check",
    "bateria_nao_esta_scheduled",
  ]) {
    assert.equal(isTerminalError({ message }), true, message);
  }
  // Nomes antigos continuam reconhecidos.
  assert.equal(isTerminalError({ message: "prova_nao_ativa" }), true);
});
