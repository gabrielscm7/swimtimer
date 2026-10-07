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

test("applyLaneUpdate mescla campos no objeto da raia", () => {
  const lane = { id: "1", status: "active", laps: 0 };
  const result = applyLaneUpdate(lane, { status: "finished", laps: 3 });
  assert.equal(result, lane);
  assert.equal(lane.status, "finished");
  assert.equal(lane.laps, 3);
});
