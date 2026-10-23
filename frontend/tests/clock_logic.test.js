const test = require("node:test");
const assert = require("node:assert");

const {
  pickBestSample,
  sampleOffset,
  newOpId,
  nextReconnectDelay,
  RECONNECT_DELAYS,
} = require("../static/clock_logic.js");

test("pickBestSample escolhe a amostra de menor RTT", () => {
  const samples = [
    { rtt: 120, offset: 1 },
    { rtt: 15, offset: 2 },
    { rtt: 60, offset: 3 },
  ];
  assert.equal(pickBestSample(samples), samples[1]);
});

test("pickBestSample usa a primeira em caso de empate e trata vazio", () => {
  const samples = [
    { rtt: 20, offset: 1 },
    { rtt: 20, offset: 2 },
  ];
  assert.equal(pickBestSample(samples), samples[0]);
  assert.equal(pickBestSample([]), null);
  assert.equal(pickBestSample(null), null);
});

test("sampleOffset desconta o meio do RTT em segundos", () => {
  // Servidor respondeu 100 s; ida/volta de 200 ms (meio em 100 ms).
  const offset = sampleOffset(100, 0, 200);
  assert.ok(Math.abs(offset - 99.9) < 1e-9, String(offset));
});

test("newOpId usa o gerador injetado", () => {
  assert.equal(newOpId(() => "uuid-123"), "uuid-123");
});

test("newOpId cai para fallback único quando o gerador falha", () => {
  const failing = () => {
    throw new Error("sem crypto");
  };
  const first = newOpId(failing);
  const second = newOpId(failing);
  assert.equal(typeof first, "string");
  assert.ok(first.startsWith("op-"), first);
  assert.notEqual(first, second);
});

test("nextReconnectDelay progride 500/1000/2000/3000/5000 e satura", () => {
  assert.deepEqual(RECONNECT_DELAYS, [500, 1000, 2000, 3000, 5000]);
  assert.equal(nextReconnectDelay(0), 500);
  assert.equal(nextReconnectDelay(1), 1000);
  assert.equal(nextReconnectDelay(2), 2000);
  assert.equal(nextReconnectDelay(3), 3000);
  assert.equal(nextReconnectDelay(4), 5000);
  assert.equal(nextReconnectDelay(50), 5000);
});
