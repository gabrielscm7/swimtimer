// Funções puras do fiscal — extraídas para permitir teste com `node --test`.
(function (root) {
  const TERMINAL_MESSAGES = [
    "ja_finalizou",
    "prova_nao_ativa",
    "nao_e_bateria",
    "nao_e_maratona",
    "fora_do_prazo",
    "prova_nao_esta_em_ready_check",
    "prova_nao_esta_scheduled",
    "raia_nao_encontrada",
    "prova_nao_encontrada",
    "nenhum_lap",
    "sem_participantes",
    "raias_duplicadas",
  ];

  // Erros definitivos (4xx) não devem permanecer na fila offline; erros de
  // rede (sem status) e 5xx transitórios devem ser reprocessados.
  function isTerminalError(error) {
    if (!error) return false;
    if (typeof error.status === "number") {
      if (error.status >= 500) return false;
      return error.status >= 400;
    }
    const message = String(error.message || "");
    return TERMINAL_MESSAGES.some((item) => message.includes(item));
  }

  function applyLaneUpdate(lane, patch) {
    if (!lane || !patch) return lane;
    Object.assign(lane, patch);
    return lane;
  }

  const api = { isTerminalError, applyLaneUpdate, TERMINAL_MESSAGES };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.FiscalLogic = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
