import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import {
  heatTypeLabel,
  showFeedback,
  showToast,
  statusLabel,
} from "../common/ui.js";
import { DISTANCES, DURATIONS, LANE_COUNTS, els, state } from "./state.js";
import { isOverrideError, promptSupervisorOverride } from "./override.js";
import {
  heatsOfProva,
  isEditableHeat,
  refresh,
  setFieldError,
  teamOptions,
  withButton,
} from "./ui.js";


function laneGridHTML(heat) {
  const editable = isEditableHeat(heat);
  const prova = (state.eventData.provas || []).find(
    (item) => item.id === heat.prova_id
  );
  const provaNaipe = prova ? prova.naipe || "" : "";
  const existingMax = heat.heat_lanes.reduce(
    (max, lane) => Math.max(max, lane.lane_number),
    0
  );
  const draftCount =
    state.heatForm &&
    state.heatForm.mode === "edit" &&
    state.heatForm.heatId === heat.id &&
    state.heatForm.provaId === heat.prova_id
      ? state.heatForm.laneCount
      : 0;
  const maxLane = Math.max(existingMax, draftCount);
  if (maxLane === 0) {
    return '<div class="empty-state"><p>Nenhuma raia configurada.</p></div>';
  }
  let cells = "";
  for (let number = 1; number <= maxLane; number += 1) {
    const lane = heat.heat_lanes.find((item) => item.lane_number === number);
    const empty =
      !lane || (!lane.participant_name && !lane.athlete_id && !lane.team_id);
    const naipeMismatch = Boolean(
      lane &&
        lane.athlete_id &&
        provaNaipe &&
        provaNaipe !== "MISTO" &&
        lane.naipe &&
        lane.naipe !== provaNaipe
    );
    cells += `
      <div class="lane-cell ${empty ? "empty" : ""}" data-prova-naipe="${provaNaipe}">
        <div class="lane-title">RAIA ${number}</div>
        <label>Participante</label>
        <input type="text" data-lane-input="${number}" list="athlete-datalist"
          data-athlete-id="${escapeHtml(lane && lane.athlete_id ? lane.athlete_id : "")}"
          placeholder="Nome ou atleta cadastrado"
          value="${escapeHtml(lane ? lane.participant_name || "" : "")}"
          ${editable ? "" : "disabled"} />
        <label style="margin-top: 8px">Equipe</label>
        <select data-lane-team="${number}" ${editable ? "" : "disabled"}>
          ${teamOptions(lane ? lane.team_id : null)}
        </select>
        ${
          lane && lane.athlete_id
            ? '<p class="muted lane-athlete-hint" style="margin:4px 0 0">Atleta cadastrado</p>'
            : ""
        }
        <p class="lane-naipe-warning" ${naipeMismatch ? "" : "hidden"}>Naipe do atleta difere do naipe da prova.</p>
        ${
          editable
            ? `<div class="lane-actions"><button data-action="save-lane" data-heat="${heat.id}" data-lane="${number}">Salvar raia</button></div>`
            : ""
        }
        ${empty && editable ? '<p class="muted" style="margin:6px 0 0">Raia vazia — não participará</p>' : ""}
      </div>`;
  }
  return `
    <div class="lane-grid">${cells}</div>
    ${
      editable
        ? `<div class="actions" style="margin-top: 12px"><button class="primary" data-action="save-all-lanes" data-heat="${heat.id}">Salvar todas as raias</button></div>`
        : '<p class="muted" style="margin-top: 10px">Prova iniciada — raias somente leitura.</p>'
    }`;
}


function accordionHTML(heat) {
  const collapsed = !state.expanded.has(heat.id);
  const editable = isEditableHeat(heat);
  return `
    <div class="accordion ${collapsed ? "collapsed" : ""}" data-heat-acc="${heat.id}" data-prova="${heat.prova_id}">
      <div class="accordion-header" draggable="true" data-drag-heat="${heat.id}" data-prova="${heat.prova_id}">
        <span class="drag-handle">⠿</span>
        <span class="accordion-title" data-action="toggle-heat" data-id="${heat.id}">
          <strong>${escapeHtml(GestaoLogic.bateriaLabel(heat))}</strong>
        </span>
        <span class="status-pill">${heatTypeLabel(heat)}</span>
        <span class="status-pill ${heat.status}">${statusLabel(heat.status)}</span>
        <span class="spacer"></span>
        ${editable ? `<button data-action="edit-heat" data-id="${heat.id}">✏️</button>` : ""}
        ${editable ? `<button class="danger" data-action="delete-heat" data-id="${heat.id}">🗑</button>` : ""}
      </div>
      <div class="accordion-body">${laneGridHTML(heat)}</div>
    </div>`;
}


function heatFormHTML() {
  const editing = state.heatForm.mode === "edit";
  const heat = editing
    ? state.eventData.heats.find((item) => item.id === state.heatForm.heatId)
    : null;
  const prova = (state.eventData.provas || []).find(
    (item) => item.id === (heat ? heat.prova_id : state.heatForm.provaId)
  );
  const type = heat ? heat.heat_type : "bateria";
  const distance = heat ? heat.distance_m : 50;
  const duration = heat
    ? Math.round((heat.duration_s || 10800) / 3600)
    : 3;
  const laneCount = state.heatForm.laneCount || 3;
  const order = editing
    ? heat.order_num
    : GestaoLogic.nextHeatOrder(heatsOfProva(state.heatForm.provaId));
  return `
    <div class="form-card" id="heat-form">
      <h2>${editing ? "Editar bateria" : "Nova bateria"}${
        prova ? ` — ${escapeHtml(prova.name)}` : ""
      }</h2>
      <div class="grid">
        <div>
          <label>Nome da bateria</label>
          <input id="hf-name" type="text" placeholder="Ex: Bateria 1"
            value="${escapeHtml(heat ? heat.name : "")}" />
        </div>
        <div>
          <label>Ordem na prova</label>
          <input id="hf-order" type="number" min="1" value="${order}" />
          <p class="muted" style="margin:4px 0 0">Única dentro desta prova; reinicia em 1 a cada prova.</p>
        </div>
        <div>
          <label>Tipo</label>
          <div class="radio-row">
            <label><input type="radio" name="hf-type" value="bateria" ${type === "bateria" ? "checked" : ""} ${editing ? "disabled" : ""} /> Bateria Cronometrada</label>
            <label><input type="radio" name="hf-type" value="maratona" ${type === "maratona" ? "checked" : ""} ${editing ? "disabled" : ""} /> Maratona Aquática</label>
          </div>
        </div>
        <div id="hf-distance-wrap" ${type === "maratona" ? "hidden" : ""}>
          <label>Distância</label>
          <select id="hf-distance">
            ${DISTANCES.map((value) => `<option value="${value}" ${value === distance ? "selected" : ""}>${value}m</option>`).join("")}
          </select>
        </div>
        <div id="hf-duration-wrap" ${type === "bateria" ? "hidden" : ""}>
          <label>Duração</label>
          <select id="hf-duration">
            ${DURATIONS.map((value) => `<option value="${value}" ${value === duration ? "selected" : ""}>${value}h</option>`).join("")}
          </select>
        </div>
        <div>
          <label>Número de raias</label>
          <select id="hf-lanes">
            ${LANE_COUNTS.map((value) => `<option value="${value}" ${value === laneCount ? "selected" : ""}>${value}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="row">
        <button class="primary" data-action="save-heat-form">Salvar</button>
        <button data-action="cancel-heat-form">Cancelar</button>
      </div>
      <div class="field-error" id="hf-error" hidden></div>
    </div>`;
}


function wireHeatForm() {
  const form = document.getElementById("heat-form");
  if (!form) return;
  form.querySelectorAll('input[name="hf-type"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const type = form.querySelector('input[name="hf-type"]:checked').value;
      form.querySelector("#hf-distance-wrap").hidden = type !== "bateria";
      form.querySelector("#hf-duration-wrap").hidden = type !== "maratona";
    });
  });
}


function wireAthleteDatalist() {
  const index = GestaoLogic.athleteLabelIndex(state.allAthletes);
  els.heats.querySelectorAll("[data-lane-input]").forEach((input) => {
    input.addEventListener("input", () => {
      const cell = input.closest(".lane-cell");
      const athlete = index.get(input.value.trim());
      const teamSelect = cell.querySelector("[data-lane-team]");
      const warning = cell.querySelector(".lane-naipe-warning");
      const provaNaipe = cell.dataset.provaNaipe || "";
      if (athlete) {
        input.dataset.athleteId = athlete.id;
        if (teamSelect) teamSelect.value = athlete.team_id || "";
        if (warning) {
          warning.hidden = !(
            provaNaipe &&
            provaNaipe !== "MISTO" &&
            athlete.naipe &&
            athlete.naipe !== provaNaipe
          );
        }
      } else {
        delete input.dataset.athleteId;
        if (warning) warning.hidden = true;
      }
    });
  });
}


async function handleHeatDrop(targetId, provaId) {
  if (!state.dragHeat || state.dragHeat.provaId !== provaId || state.dragHeat.id === targetId) {
    return;
  }
  const ordered = heatsOfProva(provaId);
  if (ordered.some((heat) => !isEditableHeat(heat))) {
    showToast("Não é possível reordenar com baterias já iniciadas", true);
    return;
  }
  const from = ordered.findIndex((heat) => heat.id === state.dragHeat.id);
  const to = ordered.findIndex((heat) => heat.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  try {
    await api("PUT", `/api/provas/${provaId}/heats/order`, {
      ids: ordered.map((heat) => heat.id),
    });
    await refresh();
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


async function saveHeatForm(button) {
  const form = document.getElementById("heat-form");
  const name = form.querySelector("#hf-name").value.trim();
  if (!name) {
    setFieldError("hf-error", "Informe o nome da bateria");
    return;
  }
  setFieldError("hf-error", "");
  const editing = state.heatForm.mode === "edit";
  const heat = editing
    ? state.eventData.heats.find((item) => item.id === state.heatForm.heatId)
    : null;
  const provaId = editing ? heat.prova_id : state.heatForm.provaId;
  const type = editing
    ? heat.heat_type
    : form.querySelector('input[name="hf-type"]:checked').value;
  const laneCount = Number(form.querySelector("#hf-lanes").value);

  const payload = { name };
  const orderInput = form.querySelector("#hf-order");
  if (orderInput && orderInput.value) {
    payload.order_num = Number(orderInput.value);
  }
  if (type === "bateria") {
    payload.distance_m = Number(form.querySelector("#hf-distance").value);
  } else {
    payload.duration_s =
      Number(form.querySelector("#hf-duration").value) * 3600;
  }

  await withButton(button, async () => {
    let heatId;
    if (editing) {
      await api("PATCH", `/api/heats/${heat.id}`, payload);
      heatId = heat.id;
    } else {
      const created = await api(
        "POST",
        `/api/provas/${provaId}/heats`,
        { ...payload, heat_type: type }
      );
      heatId = created.id;
    }
    const current = editing
      ? heat.heat_lanes.reduce((max, lane) => Math.max(max, lane.lane_number), 0)
      : 0;
    if (laneCount > current) {
      const lanes = [];
      for (let number = current + 1; number <= laneCount; number += 1) {
        lanes.push({ lane_number: number, participant_name: null, team_id: null });
      }
      await api("POST", `/api/heats/${heatId}/lanes`, { lanes });
    }
    state.expanded.add(heatId);
    state.expandedProvas.add(provaId);
    state.heatForm = null;
  });
}


function saveLaneInputs(heatId, numbers) {
  const accordion = els.heats.querySelector(`[data-heat-acc="${heatId}"]`);
  if (!accordion) return [];
  return numbers.map((number) => {
    const participant = accordion.querySelector(`[data-lane-input="${number}"]`);
    const team = accordion.querySelector(`[data-lane-team="${number}"]`);
    const athleteId = participant ? participant.dataset.athleteId || null : null;
    return {
      lane_number: number,
      athlete_id: athleteId,
      participant_name: athleteId
        ? null
        : participant && participant.value.trim()
          ? participant.value.trim()
          : null,
      team_id: athleteId ? null : team && team.value ? team.value : null,
    };
  });
}


function laneNumbersOf(heatId) {
  const accordion = els.heats.querySelector(`[data-heat-acc="${heatId}"]`);
  if (!accordion) return [];
  return Array.from(accordion.querySelectorAll("[data-lane-input]")).map(
    (input) => Number(input.dataset.laneInput)
  );
}


async function submitLanes(heatId, lanes, button) {
  const send = (extra = {}, headers = {}) =>
    api(
      "POST",
      `/api/heats/${heatId}/lanes`,
      { lanes, ...extra },
      headers
    );
  showFeedback(button, "loading");
  try {
    await send();
    showFeedback(button, "success");
    setTimeout(refresh, 400);
  } catch (error) {
    showFeedback(button, "error");
    const message = GestaoLogic.gestaoErrorMessage(error);
    showToast(message, true);
    if (!isOverrideError(error)) return;
    promptSupervisorOverride({
      message,
      onConfirm: async (pin, reason) => {
        await send(
          { force: true, override_reason: reason },
          { "X-Operator-Pin": pin }
        );
        await refresh();
        showToast("Exceção autorizada");
      },
    });
  }
}


async function saveLane(heatId, laneNumber, button) {
  const lanes = saveLaneInputs(heatId, [laneNumber]);
  await submitLanes(heatId, lanes, button);
}


async function saveAllLanes(heatId, button) {
  const lanes = saveLaneInputs(heatId, laneNumbersOf(heatId));
  await submitLanes(heatId, lanes, button);
}


async function deleteHeat(heatId) {
  const heat = state.eventData.heats.find((item) => item.id === heatId);
  if (!window.confirm(`Deletar a bateria "${heat ? heat.name : ""}"?`)) return;
  try {
    await api("DELETE", `/api/heats/${heatId}`);
    state.expanded.delete(heatId);
    await refresh();
    showToast("Bateria excluída");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

function wireHeatDragAndDrop() {
  els.heats.querySelectorAll("[data-drag-heat]").forEach((header) => {
    header.addEventListener("dragstart", (event) => {
      state.dragHeat = {
        id: header.dataset.dragHeat,
        provaId: header.dataset.prova,
      };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", state.dragHeat.id);
      header.closest(".accordion").classList.add("dragging");
    });
    header.addEventListener("dragend", () => {
      header.closest(".accordion").classList.remove("dragging");
      state.dragHeat = null;
    });
  });

  els.heats.querySelectorAll(".accordion").forEach((accordion) => {
    accordion.addEventListener("dragover", (event) => {
      if (state.dragHeat && state.dragHeat.provaId === accordion.dataset.prova) {
        event.preventDefault();
      }
    });
    accordion.addEventListener("drop", (event) => {
      event.preventDefault();
      handleHeatDrop(accordion.dataset.heatAcc, accordion.dataset.prova);
    });
  });
}


export {
  accordionHTML,
  deleteHeat,
  handleHeatDrop,
  heatFormHTML,
  laneGridHTML,
  laneNumbersOf,
  saveAllLanes,
  saveHeatForm,
  saveLane,
  saveLaneInputs,
  wireAthleteDatalist,
  wireHeatDragAndDrop,
  wireHeatForm,
};
