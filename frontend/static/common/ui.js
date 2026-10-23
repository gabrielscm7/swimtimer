import { formatDuration } from "./format.js";

export function showToast(message, isError = false) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.remove("show"), 2200);
}

export function showFeedback(element, state, message) {
  if (!element) return;
  if (state === "loading") {
    if (!element.dataset.label) element.dataset.label = element.textContent;
    element.classList.remove("success", "error");
    element.classList.add("loading");
    element.disabled = true;
    element.textContent = message || "Salvando...";
    return;
  }
  element.classList.remove("loading");
  element.disabled = false;
  const label = element.dataset.label;
  if (state === "success") {
    element.classList.add("success");
    element.textContent = message || "✓ Salvo";
    setTimeout(() => {
      element.classList.remove("success");
      if (label) element.textContent = label;
    }, 1500);
  } else if (state === "error") {
    element.classList.add("error");
    element.textContent = message || "Erro";
    setTimeout(() => {
      element.classList.remove("error");
      if (label) element.textContent = label;
    }, 2500);
  }
}

export const STATUS_LABELS = {
  draft: "Rascunho",
  active: "Em andamento",
  finished: "Encerrado",
  scheduled: "Agendada",
  ready_check: "Chamada",
  assigned: "Aguardando",
  ready: "Pronta",
  dq: "DQ",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}

export function heatTypeLabel(heat) {
  if (!heat) return "—";
  if (heat.heat_type === "bateria") return `Bateria · ${heat.distance_m}m`;
  return `Maratona · ${formatDuration(heat.duration_s || 0)}`;
}

export function heatLabel(heat) {
  if (!heat) return "—";
  const type = heat.heat_type === "bateria" ? "bateria" : "maratona";
  return `${heat.name} · ${type}#${heat.order_num}`;
}

export function pluralize(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural || singular + "s"}`;
}
