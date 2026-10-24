import { escapeHtml } from "./common/format.js";
import { renderHeatResult } from "./common/result_views.js";

const params = new URLSearchParams(window.location.search);
const heatId = params.get("heat");
const container = document.getElementById("sum-content");
const printButton = document.getElementById("sum-print");
const backLink = document.getElementById("sum-back");

const BADGE_LABELS = {
  official: "Oficial",
  provisional: "Provisório",
  corrected: "Retificado",
};

function message(text) {
  container.innerHTML = `<div class="message">${escapeHtml(text)}</div>`;
  printButton.hidden = true;
}

function render(heat, event) {
  const prova = event
    ? (event.provas || []).find((item) => item.id === heat.prova_id)
    : null;
  const snapshot = heat.result_snapshot;
  const status = snapshot ? snapshot.status : "provisional";
  const revision = snapshot ? snapshot.revision : "—";
  const printedAt = new Date().toLocaleString("pt-BR");
  container.innerHTML = `
    <div class="sheet">
      <h1>${escapeHtml(event ? event.name : "")} — ${escapeHtml(
        prova ? Labels.provaLabel(prova) : heat.prova_name || ""
      )}</h1>
      <h2><span class="level-chip bateria">BATERIA</span> ${escapeHtml(
        Labels.bateriaLabel(heat, { includeProva: false })
      )} ·
        <span class="badge ${escapeHtml(status)}">${escapeHtml(
          BADGE_LABELS[status] || "Provisório"
        )}</span> · revisão ${escapeHtml(String(revision))}</h2>
      <div class="meta">
        <span>Status: ${escapeHtml(heat.status || "—")}</span>
        <span>Distância: ${heat.distance_m ? escapeHtml(String(heat.distance_m)) + " m" : "—"}</span>
        <span>Impresso em: ${escapeHtml(printedAt)}</span>
      </div>
      ${
        renderHeatResult(heat, { variant: "print" }) ||
        "<p>Sem participantes.</p>"
      }
      <div class="signatures">
        <div>Árbitro</div>
        <div>Mesário</div>
        <div>Organização</div>
      </div>
    </div>`;
  printButton.hidden = false;
  if (event && event.id) {
    backLink.href = `resultados.html?event=${encodeURIComponent(event.id)}`;
  }
}

async function init() {
  if (!heatId) {
    message("Informe a bateria: sumula.html?heat=<id>");
    return;
  }
  try {
    const response = await fetch(`/api/heats/${encodeURIComponent(heatId)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      message("Bateria não encontrada.");
      return;
    }
    const heat = await response.json();
    let event = null;
    if (heat.event_id) {
      try {
        const eventResponse = await fetch(
          `/api/events/${encodeURIComponent(heat.event_id)}`,
          { headers: { Accept: "application/json" } }
        );
        if (eventResponse.ok) event = await eventResponse.json();
      } catch (error) {
        /* cabeçalho sem evento */
      }
    }
    render(heat, event);
  } catch (error) {
    message("Não foi possível carregar a súmula.");
  }
}

printButton.addEventListener("click", () => window.print());
init();
