import { escapeHtml, formatDuration } from "../common/format.js";
import { showFeedback, showToast, statusLabel } from "../common/ui.js";
import { els, state } from "./state.js";

let _loadEventHandler = null;
let _discardHandler = null;
const _renderers = [];

export function setLoadEventHandler(handler) {
  _loadEventHandler = handler;
}

export function setDiscardHandler(handler) {
  _discardHandler = handler;
}

export function registerRenderer(renderer) {
  _renderers.push(renderer);
}

function discardChanges() {
  setDirty(false);
  if (typeof _discardHandler === "function") _discardHandler();
}

export async function refresh() {
  try {
    await _loadEventHandler();
    setDirty(Boolean(state.themeDirty));
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

export function renderAll() {
  for (const renderer of _renderers) renderer();
}


function provasSorted() {
  return [...(state.eventData.provas || [])].sort(
    (a, b) => a.order_num - b.order_num
  );
}


function heatsOfProva(provaId) {
  return state.eventData.heats
    .filter((heat) => heat.prova_id === provaId)
    .sort((a, b) => a.order_num - b.order_num);
}


function isEditableHeat(heat) {
  return heat.status === "scheduled" || heat.status === "ready_check";
}


function isEditableProva(prova) {
  return prova.status === "scheduled" || prova.status === undefined;
}


function heatDistanceText(heat) {
  if (heat.heat_type === "bateria") return `${heat.distance_m}m`;
  return formatDuration(heat.duration_s || 0);
}


function participantsOfHeat(heat) {
  return heat.heat_lanes.filter(
    (lane) => lane.participant_name || lane.athlete_id
  );
}


function provaMeta(prova) {
  const parts = [];
  if (prova.naipe) parts.push(GestaoLogic.naipeLabel(prova.naipe));
  if (prova.stroke) parts.push(prova.stroke);
  if (prova.distance_m) parts.push(`${prova.distance_m}m`);
  if (prova.category) parts.push(prova.category);
  return parts.join(" · ");
}


function teamLogoHTML(logoUrl, name, size = "small") {
  if (!logoUrl) return "";
  return `<img class="team-logo ${size}" src="${escapeHtml(logoUrl)}" alt="${escapeHtml(
    name || "Logo da equipe"
  )}" loading="lazy" />`;
}


function setDirty(value) {
  state.dirty = value;
}


function setFieldError(id, message) {
  const el = document.getElementById(id);
  if (!el) return;
  if (message) {
    el.textContent = message;
    el.hidden = false;
  } else {
    el.textContent = "";
    el.hidden = true;
  }
}


async function withButton(button, fn) {
  showFeedback(button, "loading");
  try {
    await fn();
    showFeedback(button, "success");
    setTimeout(refresh, 400);
  } catch (error) {
    showFeedback(button, "error");
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


function renderSidebar() {
  if (!state.eventData) return;
  if (document.activeElement !== els.eventName) {
    els.eventName.value = state.eventData.name;
  }
  els.eventStatus.textContent = statusLabel(state.eventData.status);
  els.eventStatus.className = `status-pill ${state.eventData.status}`;
  document.querySelectorAll(".sidebar-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === state.activeSection);
  });
}


function teamOptions(selectedId) {
  const options = ['<option value="">— Sem equipe —</option>'];
  for (const team of state.eventData.teams) {
    options.push(
      `<option value="${team.id}" ${team.id === selectedId ? "selected" : ""}>${escapeHtml(team.name)}</option>`
    );
  }
  return options.join("");
}


function switchSection(section) {
  if (section === state.activeSection) return;
  const pending = state.dirty || state.themeDirty;
  if (pending && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) {
    return;
  }
  if (pending) discardChanges();
  state.activeSection = section;
  for (const name of ["overview", "heats", "teams", "athletes", "settings"]) {
    els[name].hidden = name !== section;
  }
  renderSidebar();
  els.sidebar.classList.remove("open");
}


function openSection(section, callback) {
  const pending = state.dirty || state.themeDirty;
  if (pending && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) {
    return false;
  }
  if (pending) discardChanges();
  state.activeSection = section;
  for (const name of ["overview", "heats", "teams", "athletes", "settings"]) {
    els[name].hidden = name !== section;
  }
  renderSidebar();
  if (callback) callback();
  return true;
}

export {
  heatDistanceText,
  heatsOfProva,
  isEditableHeat,
  isEditableProva,
  openSection,
  participantsOfHeat,
  provaMeta,
  provasSorted,
  renderSidebar,
  setDirty,
  setFieldError,
  switchSection,
  teamLogoHTML,
  teamOptions,
  withButton,
};
