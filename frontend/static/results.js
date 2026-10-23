import { escapeHtml } from "./common/format.js";
import { WSClient, wsUrl } from "./common/ws.js";

const { badgeLabel, displayName, laneStatusLabel, filterProvas } =
  window.ResultsLogic;

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");

const els = {
  name: document.getElementById("res-event-name"),
  meta: document.getElementById("res-event-meta"),
  settings: document.getElementById("res-settings-note"),
  search: document.getElementById("res-search"),
  status: document.getElementById("res-status"),
  provas: document.getElementById("res-provas"),
  footer: document.getElementById("res-footer"),
};

let data = null;
let query = "";
let unavailable = false;
let loadTimer = null;

function badge(badgeValue) {
  return `<span class="res-badge ${escapeHtml(badgeValue || "provisional")}">${escapeHtml(
    badgeLabel(badgeValue)
  )}</span>`;
}

function row(entry, mode) {
  const label = laneStatusLabel(entry);
  const position = entry.position ?? "—";
  return `<tr>
    <td class="pos">${entry.position ? `${position}º${entry.tied ? "=" : ""}` : "—"}</td>
    <td>${escapeHtml(displayName(entry.participant_name, mode) || "—")}</td>
    <td class="muted">${escapeHtml(entry.team_name || "—")}</td>
    <td class="time">${escapeHtml(label)}</td>
  </tr>`;
}

function standingsTable(title, entries, mode) {
  if (!entries || !entries.length) return "";
  return `
    <div class="res-section-title">${escapeHtml(title)}</div>
    <table class="res-table">
      <thead><tr><th>Pos</th><th>Atleta</th><th>Equipe</th><th>Tempo</th></tr></thead>
      <tbody>${entries.map((entry) => row(entry, mode)).join("")}</tbody>
    </table>`;
}

function heatBlock(heat, mode) {
  const lanes = heat.lanes || [];
  if (!lanes.length) return "";
  return `
    <details class="res-heat">
      <summary>
        <span>${escapeHtml(heat.name || "Bateria")}</span>
        ${badge(heat.badge)}
      </summary>
      <table class="res-table">
        <thead><tr><th>Pos</th><th>Atleta</th><th>Equipe</th><th>Tempo</th></tr></thead>
        <tbody>${lanes.map((entry) => row(entry, mode)).join("")}</tbody>
      </table>
    </details>`;
}

function provaBlock(prova, mode) {
  const byNaipe = prova.standings_by_naipe || {};
  const sections = [
    standingsTable("Classificação geral", prova.standings, mode),
    standingsTable("Masculino", byNaipe.M, mode),
    standingsTable("Feminino", byNaipe.F, mode),
    standingsTable("Excluídos / sem tempo", prova.excluded, mode),
  ]
    .filter(Boolean)
    .join("");
  const heats = (prova.heats || [])
    .map((heat) => heatBlock(heat, mode))
    .join("");
  return `
    <article class="res-prova">
      <div class="res-prova-head">
        <h2>${escapeHtml(prova.name)}</h2>
        ${badge(prova.badge)}
      </div>
      ${sections || '<p class="muted">Sem resultados publicados ainda.</p>'}
      ${heats ? `<div class="res-heats"><div class="res-section-title">Baterias</div>${heats}</div>` : ""}
    </article>`;
}

function showMessage(text) {
  els.status.hidden = false;
  els.status.textContent = text;
  els.provas.innerHTML = "";
}

function render() {
  if (!eventId) {
    showMessage("Selecione um evento na página inicial.");
    return;
  }
  if (unavailable || !data) {
    if (unavailable) {
      els.name.textContent = "Resultados";
      els.meta.textContent = "";
      els.settings.textContent = "";
      showMessage("Os resultados públicos estão desativados para este evento.");
    }
    return;
  }
  const event = data.event || {};
  const mode = event.public_name_mode || "full";
  els.name.textContent = event.name || "Resultados";
  const meta = [event.date, event.location, `Piscina ${event.pool_length_m}m`]
    .filter(Boolean)
    .join(" · ");
  els.meta.textContent = meta;
  els.settings.textContent =
    mode === "initials"
      ? "Nomes abreviados a pedido da organização (ex.: Maria S.)."
      : "";
  els.settings.hidden = mode !== "initials";
  els.status.hidden = true;

  const provas = filterProvas(data.provas || [], query);
  if (!provas.length) {
    els.provas.innerHTML =
      '<div class="res-message">Nenhum resultado encontrado para a busca.</div>';
    return;
  }
  els.provas.innerHTML = provas
    .map((prova) => provaBlock(prova, mode))
    .join("");
}

async function load() {
  if (!eventId) {
    render();
    return;
  }
  try {
    const response = await fetch(
      `/api/public/events/${encodeURIComponent(eventId)}/results`,
      { headers: { Accept: "application/json" } }
    );
    if (response.status === 304) return;
    if (response.status === 404) {
      unavailable = true;
      render();
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
    unavailable = false;
    render();
  } catch (error) {
    if (!data) showMessage("Não foi possível carregar os resultados agora.");
  }
}

els.search.addEventListener("input", (event) => {
  query = event.target.value;
  render();
});

const ws = new WSClient(wsUrl(), (message) => {
  if (
    message.type === "heat_state" ||
    message.type === "prova_state" ||
    message.type === "settings_updated"
  ) {
    clearTimeout(loadTimer);
    loadTimer = setTimeout(load, 300);
  }
});

ws.onStatusChange = (connected) => {
  if (connected) {
    if (eventId) ws.send({ type: "subscribe", event_id: eventId });
    load();
  }
};

load();
if (eventId) ws.connect();
setInterval(load, 10000);
