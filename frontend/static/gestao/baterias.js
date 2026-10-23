import { api } from "../common/api.js";
import { escapeHtml, formatDuration } from "../common/format.js";
import {
  heatTypeLabel,
  showFeedback,
  showToast,
  statusLabel,
} from "../common/ui.js";
import {
  DISTANCES,
  DURATIONS,
  LANE_COUNTS,
  els,
  eventId,
  state,
} from "./state.js";
import { isOverrideError, promptSupervisorOverride } from "./override.js";
import {
  isEditableHeat,
  refresh,
  setFieldError,
  teamOptions,
  withButton,
} from "./ui.js";

const CATEGORY_OPTIONS = () => window.Labels.CATEGORIES;
const STROKE_OPTIONS = () => window.Labels.STROKES;

function heatsSorted() {
  return [...(state.eventData.heats || [])].sort(
    (a, b) => a.order_num - b.order_num
  );
}

function provaOf(heat) {
  return (state.eventData.provas || []).find(
    (item) => item.id === heat.prova_id
  );
}

function heatDistanceText(heat) {
  if (heat.heat_type === "maratona") {
    return formatDuration(heat.duration_s || 0);
  }
  return heat.distance_m ? `${heat.distance_m} m` : "—";
}

function participantsCount(heat) {
  return (heat.heat_lanes || []).filter(
    (lane) => lane.participant_name || lane.athlete_id
  ).length;
}

function chipsHTML(heat) {
  const chips = [
    Labels.strokeLabel(heat.stroke) || "Sem estilo",
    heat.heat_type === "bateria" ? `${heat.distance_m || "?"} m` : "Maratona",
    Labels.naipeLabel(heat.naipe) || "Sem naipe",
    Labels.categoryLabel(heat.category) || "Sem categoria",
  ];
  return `<span class="heat-chips">${chips
    .map((text) => `<span class="chip">${escapeHtml(text)}</span>`)
    .join("")}</span>`;
}

function provaBadgeHTML(heat) {
  const prova = provaOf(heat);
  if (!prova) return "";
  const count = prova.heat_count || 0;
  return `<span class="prova-badge"><span class="level-chip prova"><span class="level-icon">◆</span>PROVA</span>
    ${escapeHtml(prova.name)} <span class="muted">(${count} ${count === 1 ? "bateria" : "baterias"})</span></span>`;
}

function laneEditorHTML(heat) {
  const teams = state.eventData.teams || [];
  if (!teams.length) {
    return '<div class="empty-state"><p>Cadastre uma equipe para alocar atletas.</p></div>';
  }
  const selectedTeam = state.laneTeams[heat.id] || "";
  const athletes = state.laneAthletes[heat.id] || [];
  const loading = state.laneLoading[heat.id];
  const editable = isEditableHeat(heat);
  const lanes = [];
  for (let number = 1; number <= heat.lane_count; number += 1) {
    const lane = (heat.heat_lanes || []).find(
      (item) => item.lane_number === number
    );
    const occupied = lane && (lane.participant_name || lane.athlete_id);
    lanes.push(`
      <div class="lane-cell ${occupied ? "" : "empty"}">
        <div class="lane-title">RAIA ${number}</div>
        <div class="lane-occupant">${escapeHtml(
          occupied ? lane.participant_name || "Atleta" : "Vazia"
        )}</div>
        ${
          occupied && editable
            ? `<button data-action="remove-lane" data-heat="${heat.id}" data-lane="${number}">Remover</button>`
            : ""
        }
        ${
          !occupied && editable
            ? `<button data-action="manual-lane" data-heat="${heat.id}" data-lane="${number}">Nome manual</button>`
            : ""
        }
      </div>`);
  }
  const athleteOptions = athletes
    .map((athlete) => {
      const disabled = athlete.allocated;
      const detail = disabled
        ? `Alocado em ${athlete.allocated_heat_name || "outra bateria"}`
        : `${Labels.naipeLabel(athlete.naipe)} · ${Labels.categoryLabel(athlete.category) || "sem categoria"}`;
      return `
        <button class="athlete-option ${disabled ? "allocated" : ""}"
          data-action="allocate-athlete" data-heat="${heat.id}"
          data-athlete="${athlete.id}" ${disabled ? "disabled" : ""}>
          <strong>${escapeHtml(athlete.name)}</strong>
          <span class="muted">${escapeHtml(detail)}</span>
        </button>`;
    })
    .join("");
  return `
    <div class="lane-editor">
      <div class="row">
        <label>Equipe</label>
        <select data-lane-team-select="${heat.id}" ${editable ? "" : "disabled"}>
          ${teamOptions(selectedTeam)}
        </select>
        <button data-action="load-eligible" data-heat="${heat.id}" ${editable ? "" : "disabled"}>Carregar atletas</button>
        ${loading ? '<span class="muted">Carregando…</span>' : ""}
      </div>
      <div class="lane-grid">${lanes.join("")}</div>
      <div class="athlete-list">
        ${
          !selectedTeam
            ? '<p class="muted">Escolha a equipe e carregue os atletas elegíveis.</p>'
            : athletes.length
              ? athleteOptions
              : '<p class="muted">Nenhum atleta elegível nesta equipe.</p>'
        }
      </div>
      ${editable ? "" : '<p class="muted">Bateria iniciada — raias somente leitura.</p>'}
    </div>`;
}

function heatFormHTML() {
  const form = state.heatForm;
  if (!form) return "";
  const editing = form.mode === "edit";
  const heat = editing
    ? state.eventData.heats.find((item) => item.id === form.heatId)
    : null;
  const base = heat || form.defaults || {};
  const type = base.heat_type || "bateria";
  const laneCount = form.laneCount || base.lane_count || state.eventData.default_lane_count || 3;
  const duration = Math.round((base.duration_s || 10800) / 3600);
  const order = editing ? heat.order_num : "";
  return `
    <div class="form-card" id="heat-form">
      <h2>${editing ? "Editar bateria" : "Nova bateria"}</h2>
      <div class="grid">
        <div>
          <label>Tipo</label>
          <select id="hf-type">
            <option value="bateria" ${type === "bateria" ? "selected" : ""}>Bateria cronometrada</option>
            <option value="maratona" ${type === "maratona" ? "selected" : ""}>Maratona aquática</option>
          </select>
        </div>
        <div>
          <label>Estilo</label>
          <select id="hf-stroke">
            ${STROKE_OPTIONS().map((value) => `<option value="${value}" ${value === base.stroke ? "selected" : ""}>${Labels.strokeLabel(value)}</option>`).join("")}
          </select>
        </div>
        <div id="hf-distance-wrap" ${type === "maratona" ? "hidden" : ""}>
          <label>Distância</label>
          <select id="hf-distance">
            ${DISTANCES.map((value) => `<option value="${value}" ${value === (base.distance_m || 25) ? "selected" : ""}>${value} m</option>`).join("")}
          </select>
        </div>
        <div id="hf-duration-wrap" ${type === "bateria" ? "hidden" : ""}>
          <label>Duração</label>
          <select id="hf-duration">
            ${DURATIONS.map((value) => `<option value="${value}" ${value === duration ? "selected" : ""}>${value}h</option>`).join("")}
          </select>
        </div>
        <div>
          <label>Naipe</label>
          <select id="hf-naipe">
            ${["M", "F", "MISTO"].map((value) => `<option value="${value}" ${value === (base.naipe || "MISTO") ? "selected" : ""}>${Labels.naipeLabel(value)}</option>`).join("")}
          </select>
        </div>
        <div>
          <label>Categoria</label>
          <select id="hf-category">
            ${CATEGORY_OPTIONS().map((value) => `<option value="${value}" ${value === (base.category || "livre") ? "selected" : ""}>${Labels.categoryLabel(value)}</option>`).join("")}
          </select>
        </div>
        <div>
          <label>Número de raias</label>
          <select id="hf-lanes">
            ${LANE_COUNTS.map((value) => `<option value="${value}" ${value === laneCount ? "selected" : ""}>${value}</option>`).join("")}
          </select>
        </div>
        <div>
          <label>Nome da bateria (opcional)</label>
          <input id="hf-name" type="text" value="${escapeHtml(base.name || "")}" placeholder="Gerado como BATERIA i de N" />
        </div>
        <div>
          <label>Posição no evento (opcional)</label>
          <input id="hf-order" type="number" min="1" value="${order}" placeholder="Fim do programa" />
        </div>
        <div>
          <label>Baterias a criar</label>
          <input id="hf-copies" type="number" min="1" max="50" value="1" ${editing ? "disabled" : ""} />
          <p class="muted" style="margin:4px 0 0">"Criar N baterias deste grupo" usa os mesmos atributos.</p>
        </div>
      </div>
      <label class="checkbox-row" style="margin-top:10px">
        <input type="checkbox" id="hf-isolated" ${base.classify_alone ? "checked" : ""} />
        Classificar isolada (grupo próprio)
      </label>
      <div class="row" style="margin-top:12px">
        <button class="primary" data-action="save-heat-form">Salvar</button>
        <button data-action="cancel-heat-form">Cancelar</button>
      </div>
      <div class="field-error" id="hf-error" hidden></div>
    </div>`;
}

function rowHTML(heat, index) {
  const editable = heat.status === "scheduled";
  const expanded = state.expanded.has(heat.id);
  const editing = state.heatForm && state.heatForm.mode === "edit" && state.heatForm.heatId === heat.id;
  const isIsolated = heat.classify_alone;
  return `
    <div class="accordion heat-row ${expanded ? "" : "collapsed"}" data-heat-row="${heat.id}">
      <div class="accordion-header" draggable="${editable}" data-drag-heat="${heat.id}">
        <span class="drag-handle" title="${editable ? "Arraste para reordenar" : "Bateria ancorada"}">${editable ? "⠿" : "🔒"}</span>
        <input class="order-input" type="number" min="1" value="${index + 1}" data-order-heat="${heat.id}" ${editable ? "" : "disabled"} title="Mover para a posição" />
        <span class="accordion-title" data-action="toggle-heat" data-id="${heat.id}">
          <strong>${escapeHtml(Labels.bateriaLabel(heat))}</strong>
          ${chipsHTML(heat)}
        </span>
        <span class="status-pill ${heat.status}">${statusLabel(heat.status)}</span>
        <span class="spacer"></span>
        <button data-action="toggle-heat" data-id="${heat.id}" title="Raias">🏊 ${participantsCount(heat)}</button>
        ${
          isEditableHeat(heat)
            ? `<button data-action="edit-heat" data-id="${heat.id}" title="Editar">✏️</button>`
            : ""
        }
        <button data-action="duplicate-heat" data-id="${heat.id}" title="Duplicar">⧉</button>
        ${
          heat.status === "scheduled"
            ? `<button class="danger" data-action="delete-heat" data-id="${heat.id}" title="Excluir">🗑</button>`
            : ""
        }
      </div>
      <div class="heat-meta">
        ${provaBadgeHTML(heat)}
        ${isIsolated ? '<span class="status-pill">Isolada</span>' : ""}
        ${heat.legacy_incomplete ? '<span class="status-pill warning">legado incompleto — complete estilo, naipe e categoria</span>' : ""}
        <span class="muted">${escapeHtml(heat.heat_type === "maratona" ? "Maratona" : "Bateria de tempo")} · ${escapeHtml(heatDistanceText(heat))}</span>
      </div>
      <div class="accordion-body">
        ${editing ? heatFormHTML() : ""}
        ${expanded ? laneEditorHTML(heat) : ""}
      </div>
    </div>`;
}

export function renderHeats() {
  if (!state.eventData) return;
  const heats = heatsSorted();
  const creating = state.heatForm && state.heatForm.mode === "create";
  els.heats.innerHTML = `
    <div class="panel">
      <div class="row" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Baterias</h2>
        <button class="primary" data-action="new-heat">+ Nova bateria</button>
      </div>
      <p class="muted">Arraste as baterias ou use o campo numérico para definir a ordem livre do evento. A prova (grupo) é criada automaticamente.</p>
      ${creating ? heatFormHTML() : ""}
      ${
        heats.length
          ? `<div class="heat-list">${heats.map((heat, index) => rowHTML(heat, index)).join("")}</div>`
          : '<div class="empty-state"><p>Nenhuma bateria cadastrada.</p></div>'
      }
    </div>`;
  wireHeatInteractions();
}

function wireHeatInteractions() {
  const typeSelect = els.heats.querySelector("#hf-type");
  if (typeSelect) {
    typeSelect.addEventListener("change", () => {
      const marathon = typeSelect.value === "maratona";
      const distanceWrap = els.heats.querySelector("#hf-distance-wrap");
      const durationWrap = els.heats.querySelector("#hf-duration-wrap");
      if (distanceWrap) distanceWrap.hidden = marathon;
      if (durationWrap) durationWrap.hidden = !marathon;
    });
  }

  els.heats.querySelectorAll("[data-lane-team-select]").forEach((select) => {
    select.addEventListener("change", () => {
      state.laneTeams[select.dataset.laneTeamSelect] = select.value;
      state.laneAthletes[select.dataset.laneTeamSelect] = [];
      renderHeats();
    });
  });

  els.heats.querySelectorAll("[data-order-heat]").forEach((input) => {
    input.addEventListener("change", async () => {
      const position = Number(input.value);
      if (!Number.isFinite(position) || position < 1) return;
      try {
        await api("PATCH", `/api/events/${eventId}/heats/order`, {
          heat_id: input.dataset.orderHeat,
          position,
        });
        await refresh();
      } catch (error) {
        showToast(GestaoLogic.gestaoErrorMessage(error), true);
        renderHeats();
      }
    });
  });

  els.heats.querySelectorAll("[data-drag-heat]").forEach((header) => {
    header.addEventListener("dragstart", (event) => {
      if (header.getAttribute("draggable") !== "true") return;
      state.dragHeat = { id: header.dataset.dragHeat };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", state.dragHeat.id);
      header.closest(".accordion").classList.add("dragging");
    });
    header.addEventListener("dragend", () => {
      header.closest(".accordion").classList.remove("dragging");
      state.dragHeat = null;
    });
  });

  els.heats.querySelectorAll("[data-heat-row]").forEach((row) => {
    row.addEventListener("dragover", (event) => {
      if (state.dragHeat) event.preventDefault();
    });
    row.addEventListener("drop", async (event) => {
      event.preventDefault();
      if (!state.dragHeat || state.dragHeat.id === row.dataset.heatRow) return;
      await reorderDrag(state.dragHeat.id, row.dataset.heatRow);
    });
  });
}

async function reorderDrag(sourceId, targetId) {
  const ordered = heatsSorted();
  const from = ordered.findIndex((heat) => heat.id === sourceId);
  const to = ordered.findIndex((heat) => heat.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  try {
    await api("PATCH", `/api/events/${eventId}/heats/order`, {
      ids: ordered.map((heat) => heat.id),
    });
    await refresh();
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
    renderHeats();
  }
}

export async function loadEligibleAthletes(heatId) {
  const teamId = state.laneTeams[heatId];
  if (!teamId) {
    showToast("Escolha uma equipe primeiro", true);
    return;
  }
  state.laneLoading[heatId] = true;
  renderHeats();
  try {
    state.laneAthletes[heatId] = await api(
      "GET",
      `/api/heats/${heatId}/eligible-athletes?team_id=${encodeURIComponent(teamId)}`
    );
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
    state.laneAthletes[heatId] = [];
  } finally {
    state.laneLoading[heatId] = false;
    renderHeats();
  }
}

async function submitLanes(heatId, lanes, button) {
  const send = (extra = {}, headers = {}) =>
    api("POST", `/api/heats/${heatId}/lanes`, { lanes, ...extra }, headers);
  if (button) showFeedback(button, "loading");
  try {
    await send();
    if (button) showFeedback(button, "success");
    await loadEligibleAthletesSilently(heatId);
    await refresh();
  } catch (error) {
    if (button) showFeedback(button, "error");
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
        await loadEligibleAthletesSilently(heatId);
        await refresh();
        showToast("Exceção autorizada");
      },
    });
  }
}

async function loadEligibleAthletesSilently(heatId) {
  const teamId = state.laneTeams[heatId];
  if (!teamId) return;
  try {
    state.laneAthletes[heatId] = await api(
      "GET",
      `/api/heats/${heatId}/eligible-athletes?team_id=${encodeURIComponent(teamId)}`
    );
  } catch (error) {
    state.laneAthletes[heatId] = [];
  }
}

export async function allocateAthlete(heatId, athleteId, button) {
  const heat = state.eventData.heats.find((item) => item.id === heatId);
  if (!heat) return;
  const used = new Set(
    (heat.heat_lanes || [])
      .filter((lane) => lane.athlete_id || lane.participant_name)
      .map((lane) => lane.lane_number)
  );
  let laneNumber = null;
  for (let number = 1; number <= heat.lane_count; number += 1) {
    if (!used.has(number)) {
      laneNumber = number;
      break;
    }
  }
  if (laneNumber === null) {
    showToast("Sem raia livre nesta bateria", true);
    return;
  }
  await submitLanes(
    heatId,
    [{ lane_number: laneNumber, athlete_id: athleteId }],
    button
  );
}

export async function removeLane(heatId, laneNumber, button) {
  await submitLanes(
    heatId,
    [
      {
        lane_number: laneNumber,
        athlete_id: null,
        participant_name: null,
        team_id: null,
      },
    ],
    button
  );
}

export async function manualLane(heatId, laneNumber) {
  const name = window.prompt("Nome do participante sem cadastro:");
  if (!name || !name.trim()) return;
  await submitLanes(heatId, [
    {
      lane_number: laneNumber,
      athlete_id: null,
      participant_name: name.trim(),
      team_id: state.laneTeams[heatId] || null,
    },
  ]);
}

function heatPayloadFromForm(form) {
  const type = form.querySelector("#hf-type").value;
  const name = form.querySelector("#hf-name").value.trim();
  const payload = {
    heat_type: type,
    stroke: form.querySelector("#hf-stroke").value,
    naipe: form.querySelector("#hf-naipe").value,
    category: form.querySelector("#hf-category").value,
    lane_count: Number(form.querySelector("#hf-lanes").value),
    classify_alone: form.querySelector("#hf-isolated").checked,
  };
  if (name) payload.name = name;
  if (type === "bateria") {
    payload.distance_m = Number(form.querySelector("#hf-distance").value);
  } else {
    payload.duration_s =
      Number(form.querySelector("#hf-duration").value) * 3600;
  }
  const order = form.querySelector("#hf-order").value;
  if (order) payload.order_num = Number(order);
  return payload;
}

export async function saveHeatForm(button) {
  const form = document.getElementById("heat-form");
  if (!form) return;
  setFieldError("hf-error", "");
  const editing = state.heatForm.mode === "edit";
  const payload = heatPayloadFromForm(form);
  const copies = editing
    ? 1
    : Math.max(1, Number(form.querySelector("#hf-copies").value) || 1);
  await withButton(button, async () => {
    if (editing) {
      await api("PATCH", `/api/heats/${state.heatForm.heatId}`, payload);
      state.expanded.add(state.heatForm.heatId);
    } else {
      let firstId = null;
      for (let index = 0; index < copies; index += 1) {
        const body = { ...payload };
        if (index > 0) delete body.order_num;
        const created = await api(
          "POST",
          `/api/events/${eventId}/heats`,
          body
        );
        if (index === 0) firstId = created.id;
      }
      if (firstId) state.expanded.add(firstId);
    }
    state.heatForm = null;
  });
}

export async function duplicateHeat(heatId) {
  const heat = state.eventData.heats.find((item) => item.id === heatId);
  if (!heat) return;
  const payload = {
    heat_type: heat.heat_type,
    stroke: heat.stroke,
    naipe: heat.naipe,
    category: heat.category,
    lane_count: heat.lane_count,
    classify_alone: heat.classify_alone,
  };
  if (heat.heat_type === "bateria") payload.distance_m = heat.distance_m;
  else payload.duration_s = heat.duration_s;
  try {
    await api("POST", `/api/events/${eventId}/heats`, payload);
    await refresh();
    showToast("Bateria duplicada");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

export async function deleteHeat(heatId) {
  const heat = state.eventData.heats.find((item) => item.id === heatId);
  if (
    !window.confirm(
      `Deletar a ${heat ? Labels.bateriaLabel(heat).toLowerCase() : "bateria"}?`
    )
  ) {
    return;
  }
  try {
    await api("DELETE", `/api/heats/${heatId}`);
    state.expanded.delete(heatId);
    await refresh();
    showToast("Bateria excluída");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

export function upsertProva(payload) {
  if (!state.eventData) return;
  const provas = state.eventData.provas || (state.eventData.provas = []);
  const summary = {
    id: payload.id,
    event_id: payload.event_id,
    name: payload.name,
    order_num: payload.order_num,
    format: payload.format,
    stroke: payload.stroke,
    distance_m: payload.distance_m,
    naipe: payload.naipe,
    category: payload.category,
    classify_alone: payload.classify_alone,
    legacy_incomplete: payload.legacy_incomplete,
    mixed_ranking: payload.mixed_ranking,
    classification_criterion: payload.classification_criterion,
    status: payload.status,
    heat_count: payload.heat_count,
  };
  const index = provas.findIndex((prova) => prova.id === payload.id);
  if (index >= 0) provas[index] = summary;
  else provas.push(summary);
  if (Array.isArray(payload.heats)) {
    for (const heat of payload.heats) {
      const heatIndex = state.eventData.heats.findIndex(
        (item) => item.id === heat.id
      );
      if (heatIndex >= 0) state.eventData.heats[heatIndex] = heat;
      else state.eventData.heats.push(heat);
    }
  }
}

export function upsertHeat(payload) {
  if (!state.eventData) return;
  const index = state.eventData.heats.findIndex(
    (heat) => heat.id === payload.id
  );
  if (index >= 0) state.eventData.heats[index] = payload;
  else state.eventData.heats.push(payload);
}
