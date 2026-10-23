// Fluxo de exceção do supervisor: o backend bloqueia inscrições inválidas,
// mas um supervisor pode autorizar com PIN + motivo (auditado no action_log).
const OVERRIDE_CODES = new Set([
  "naipe_incompativel",
  "categoria_incompativel",
  "atleta_duplicado_na_bateria",
  "atleta_duplicado_na_prova",
  "atleta_em_outra_bateria_ativa",
  "atleta_com_resultado",
]);

function overrideCode(error) {
  const message = error && error.message ? String(error.message) : "";
  const code = message.split(":")[0].trim();
  return OVERRIDE_CODES.has(code) ? code : null;
}

export function isOverrideError(error) {
  return overrideCode(error) !== null;
}

/**
 * Abre o modal de autorização. `onConfirm(pin, reason)` deve reenviar a
 * operação com force/override_reason + X-Operator-Pin e pode lançar erro
 * (exibido dentro do modal).
 */
export function promptSupervisorOverride({ message, onConfirm }) {
  const modal = document.getElementById("override-modal");
  if (!modal) return;
  const messageEl = document.getElementById("override-message");
  const pinInput = document.getElementById("override-pin");
  const reasonInput = document.getElementById("override-reason");
  const errorEl = document.getElementById("override-error");
  const confirm = document.getElementById("override-confirm");
  const cancel = document.getElementById("override-cancel");

  messageEl.textContent = message || "A inscrição viola uma regra.";
  pinInput.value = "";
  reasonInput.value = "";
  errorEl.textContent = "";
  errorEl.hidden = true;
  confirm.disabled = false;
  modal.classList.add("open");
  pinInput.focus();

  const close = () => {
    modal.classList.remove("open");
    confirm.onclick = null;
    cancel.onclick = null;
  };

  cancel.onclick = close;
  confirm.onclick = async () => {
    const pin = pinInput.value.trim();
    const reason = reasonInput.value.trim();
    if (!pin || !reason) {
      errorEl.textContent = "Informe o PIN e o motivo da exceção.";
      errorEl.hidden = false;
      return;
    }
    confirm.disabled = true;
    errorEl.hidden = true;
    try {
      await onConfirm(pin, reason);
      close();
    } catch (error) {
      errorEl.textContent =
        typeof GestaoLogic !== "undefined"
          ? GestaoLogic.gestaoErrorMessage(error)
          : String(error.message || error);
      errorEl.hidden = false;
      confirm.disabled = false;
    }
  };
}
