import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { showToast, statusLabel } from "../common/ui.js";
import { els, eventId, state } from "./state.js";
import {
  heatDistanceText,
  heatsOfProva,
  participantsOfHeat,
  provaMeta,
  provasSorted,
  setFieldError,
  withButton,
} from "./ui.js";


function renderOverview() {
  if (!state.eventData) return;
  const provas = provasSorted();
  const heats = state.eventData.heats;
  const finished = heats.filter((heat) => heat.status === "finished").length;
  const teams = state.eventData.teams.length;
  const athletes = state.allAthletes.length;
  const participants = heats.reduce(
    (sum, heat) => sum + participantsOfHeat(heat).length,
    0
  );
  const provaRows = provas
    .map(
      (prova) => `
      <tr data-action="open-prova" data-id="${prova.id}">
        <td>${prova.order_num}</td>
        <td>${escapeHtml(prova.name)}</td>
        <td>${escapeHtml(provaMeta(prova) || "—")}</td>
        <td>${heatsOfProva(prova.id).length}</td>
        <td><span class="status-pill ${prova.status}">${statusLabel(prova.status)}</span></td>
      </tr>`
    )
    .join("");
  const heatRows = heats
    .map((heat) => {
      const prova = provas.find((item) => item.id === heat.prova_id);
      return `
      <tr data-action="open-heat" data-id="${heat.id}">
        <td>${escapeHtml(prova ? prova.name : "—")}</td>
        <td>B${heat.order_num}</td>
        <td>${escapeHtml(heat.name)}</td>
        <td>${heat.heat_type === "bateria" ? "Bateria" : "Maratona"}</td>
        <td>${heatDistanceText(heat)}</td>
        <td>${participantsOfHeat(heat).length}</td>
        <td><span class="status-pill ${heat.status}">${statusLabel(heat.status)}</span></td>
      </tr>`;
    })
    .join("");
  els.overview.innerHTML = `
    <div class="summary-cards">
      <div class="summary-card"><div class="value">${provas.length}</div><div class="label">Provas</div></div>
      <div class="summary-card"><div class="value">${heats.length}</div><div class="label">Baterias</div></div>
      <div class="summary-card"><div class="value">${finished}</div><div class="label">Finalizadas</div></div>
      <div class="summary-card"><div class="value">${teams}</div><div class="label">Equipes</div></div>
      <div class="summary-card"><div class="value">${athletes}</div><div class="label">Atletas inscritos</div></div>
      <div class="summary-card"><div class="value">${participants}</div><div class="label">Em raias</div></div>
    </div>
    <div class="panel">
      <h2>Provas</h2>
      ${
        provas.length
          ? `<table class="data-table"><thead><tr><th>Ordem</th><th>Prova</th><th>Modalidade</th><th>Baterias</th><th>Status</th></tr></thead><tbody>${provaRows}</tbody></table>`
          : `<div class="empty-state"><p>Nenhuma prova criada.</p><p class="muted">Crie uma prova na aba "Provas e baterias".</p></div>`
      }
    </div>
    <div class="panel">
      <h2>Baterias</h2>
      ${
        heats.length
          ? `<table class="data-table"><thead><tr><th>Prova</th><th>Bateria</th><th>Nome</th><th>Tipo</th><th>Distância</th><th>Participantes</th><th>Status</th></tr></thead><tbody>${heatRows}</tbody></table>`
          : `<div class="empty-state"><p>Nenhuma bateria criada.</p></div>`
      }
    </div>
  `;
}


function renderSettings() {
  if (!state.eventData) return;
  els.settings.innerHTML = `
    <div class="panel">
      <h2>Configurações do evento</h2>
      <div class="grid">
        <div>
          <label>Nome completo</label>
          <input id="set-name" type="text" value="${escapeHtml(state.eventData.name)}" />
        </div>
        <div>
          <label>Local</label>
          <input id="set-location" type="text" value="${escapeHtml(state.eventData.location || "")}" />
        </div>
        <div>
          <label>Data</label>
          <input id="set-date" type="date" value="${escapeHtml(state.eventData.date || "")}" />
        </div>
        <div>
          <label>Tamanho da piscina</label>
          <div class="radio-row">
            <label><input type="radio" name="set-pool" value="25" ${state.eventData.pool_length_m === 25 ? "checked" : ""} /> 25m</label>
            <label><input type="radio" name="set-pool" value="50" ${state.eventData.pool_length_m === 50 ? "checked" : ""} /> 50m</label>
          </div>
        </div>
      </div>
      <button class="primary" data-action="save-settings">Salvar configurações</button>
      <div class="field-error" id="set-error" hidden></div>
    </div>
    <div class="panel">
      <h2>Exibição no telão</h2>
      <div class="radio-row" style="margin-top:12px">
        <label><input type="radio" name="set-name-mode" value="full" ${state.eventData.public_name_mode !== "initials" ? "checked" : ""} /> Nome completo</label>
        <label><input type="radio" name="set-name-mode" value="initials" ${state.eventData.public_name_mode === "initials" ? "checked" : ""} /> Iniciais (Maria S.)</label>
      </div>
      <p class="muted">O modo de iniciais afeta apenas a TV. Súmulas, exportações, snapshots e a gestão mantêm o nome completo. A curadoria de resultados fica em <a href="resultados.html?event=${eventId}">Resultados</a>.</p>
      <button class="primary" data-action="save-settings">Salvar exibição</button>
      <div class="field-error" id="set-public-error" hidden></div>
    </div>
    <div class="panel" id="appearance-panel"></div>
    <div class="panel">
      <h2>Zona de perigo</h2>
      <button class="danger" data-action="delete-event" ${state.eventData.status === "draft" ? "" : "disabled"}>🗑 Excluir evento</button>
      ${state.eventData.status === "draft" ? "" : '<p class="muted">Só é possível excluir eventos em rascunho.</p>'}
    </div>
  `;
}


async function saveSettings(button) {
  const pool = document.querySelector('input[name="set-pool"]:checked');
  const nameMode = document.querySelector(
    'input[name="set-name-mode"]:checked'
  );
  const payload = {
    name: document.getElementById("set-name").value.trim(),
    location: document.getElementById("set-location").value.trim() || null,
    date: document.getElementById("set-date").value || null,
    pool_length_m: pool ? Number(pool.value) : state.eventData.pool_length_m,
    public_name_mode: nameMode
      ? nameMode.value
      : state.eventData.public_name_mode || "full",
  };
  if (!payload.name) {
    setFieldError("set-error", "Informe o nome do evento");
    return;
  }
  setFieldError("set-error", "");
  await withButton(button, async () => {
    await api("PATCH", `/api/events/${eventId}`, payload);
  });
}


async function deleteEvent() {
  const typed = window.prompt(
    `Digite o nome do evento para confirmar a exclusão:`
  );
  if (typed === null) return;
  if (typed.trim() !== state.eventData.name) {
    showToast("Nome não confere — exclusão cancelada", true);
    return;
  }
  try {
    await api("DELETE", `/api/events/${eventId}`);
    window.location.href = "index.html";
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

export {
  deleteEvent,
  renderOverview,
  renderSettings,
  saveSettings,
};
