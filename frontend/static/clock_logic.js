// Funções puras de sincronização de relógio e idempotência — testáveis no Node.
(function (root) {
  const RECONNECT_DELAYS = [500, 1000, 2000, 3000, 5000];

  // Escolhe a amostra de menor RTT (menor incerteza); empate mantém a primeira.
  function pickBestSample(samples) {
    if (!Array.isArray(samples) || samples.length === 0) return null;
    let best = null;
    for (const sample of samples) {
      if (!sample || typeof sample.rtt !== "number") continue;
      if (best === null || sample.rtt < best.rtt) best = sample;
    }
    return best;
  }

  // offset = serverNow - instante local (meio do RTT), em segundos.
  function sampleOffset(serverNow, t0Ms, t1Ms) {
    const midpointMs = (t0Ms + t1Ms) / 2;
    return serverNow - midpointMs / 1000;
  }

  // Gera um op_id estável; usa crypto.randomUUID quando disponível.
  function newOpId(randomUUID) {
    let generate = randomUUID;
    if (!generate && typeof crypto !== "undefined" && crypto.randomUUID) {
      generate = () => crypto.randomUUID();
    }
    if (generate) {
      try {
        const value = generate();
        if (value) return value;
      } catch (error) {
        /* cai para o fallback */
      }
    }
    const rand = Math.random().toString(16).slice(2, 10);
    return `op-${Date.now().toString(36)}-${rand}`;
  }

  function nextReconnectDelay(attempts, delays) {
    const list = Array.isArray(delays) && delays.length ? delays : RECONNECT_DELAYS;
    const index = Math.min(Math.max(0, attempts | 0), list.length - 1);
    return list[index];
  }

  const api = {
    RECONNECT_DELAYS,
    pickBestSample,
    sampleOffset,
    newOpId,
    nextReconnectDelay,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ClockLogic = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
