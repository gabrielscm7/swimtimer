const DISTANCES = [25, 50, 100, 200, 400, 800, 1500];
const DURATIONS = [1, 2, 3, 4, 5];
const LANE_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8];

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");
if (!eventId) {
  window.location.replace("index.html");
}

const els = {
  sidebar: document.getElementById("sidebar"),
  hamburger: document.getElementById("btn-hamburger"),
  eventName: document.getElementById("event-name"),
  eventStatus: document.getElementById("event-status"),
  main: document.getElementById("main"),
  overview: document.getElementById("section-overview"),
  heats: document.getElementById("section-heats"),
  teams: document.getElementById("section-teams"),
  settings: document.getElementById("section-settings"),
};

let eventData = null;
let activeSection = "overview";
const expanded = new Set();
let heatForm = null;
let teamsFormOpen = false;
let dirty = false;
let dragId = null;

function isEditableHeat(heat) {
  return heat.status === "scheduled" || heat.status === "ready_check";
}

function heatDistanceText(heat) {
  if (heat.heat_type === "bateria") return `${heat.distance_m}m`;
  return formatDuration(heat.duration_s || 0);
}

function participantsOfHeat(heat) {
  return heat.heat_lanes.filter((lane) => lane.participant_name);
}

function teamParticipantCount(teamId) {
  return eventData.heats.reduce(
    (sum, heat) =>
      sum + heat.heat_lanes.filter((lane) => lane.team_id === teamId).length,
    0
  );
}

function setDirty(value) {
  dirty = value;
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

async function loadEvent() {
  eventData = await api("GET", `/api/events/${eventId}`);
  renderAll();
}

async function refresh() {
  try {
    await loadEvent();
    setDirty(false);
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
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
    showToast(`Erro: ${error.message}`, true);
  }
}

function renderAll() {
  renderSidebar();
  renderOverview();
  renderHeats();
  renderTeams();
  renderSettings();
}

function renderSidebar() {
  if (!eventData) return;
  if (document.activeElement !== els.eventName) {
    els.eventName.value = eventData.name;
  }
  els.eventStatus.textContent = statusLabel(eventData.status);
  els.eventStatus.className = `status-pill ${eventData.status}`;
  document.querySelectorAll(".sidebar-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === activeSection);
  });
}

function renderOverview() {
  if (!eventData) return;
  const heats = eventData.heats;
  const finished = heats.filter((heat) => heat.status === "finished").length;
  const teams = eventData.teams.length;
  const participants = heats.reduce(
    (sum, heat) => sum + participantsOfHeat(heat).length,
    0
  );
  const rows = heats
    .map(
      (heat) => `
      <tr data-action="open-heat" data-id="${heat.id}">
        <td>${heat.order_num}</td>
        <td>${escapeHtml(heat.name)}</td>
        <td>${heat.heat_type === "bateria" ? "Bateria" : "Maratona"}</td>
        <td>${heatDistanceText(heat)}</td>
        <td>${participantsOfHeat(heat).length}</td>
        <td><span class="status-pill ${heat.status}">${statusLabel(heat.status)}</span></td>
      </tr>`
    )
    .join("");
  els.overview.innerHTML = `
    <div class="summary-cards">
      <div class="summary-card"><div class="value">${heats.length}</div><div class="label">Baterias</div></div>
      <div class="summary-card"><div class="value">${finished}</div><div class="label">Finalizadas</div></div>
      <div class="summary-card"><div class="value">${teams}</div><div class="label">Equipes</div></div>
      <div class="summary-card"><div class="value">${participants}</div><div class="label">Participantes</div></div>
    </div>
    <div class="panel">
      <h2>Resumo das baterias</h2>
      ${
        heats.length
          ? `<table class="data-table"><thead><tr><th>Ordem</th><th>Nome</th><th>Tipo</th><th>Distância</th><th>Participantes</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`
          : `<div class="empty-state"><p>Nenhuma bateria criada.</p><p class="muted">Comece criando as equipes e depois as baterias.</p></div>`
      }
    </div>
  `;
}

function teamOptions(selectedId) {
  const options = ['<option value="">— Sem equipe —</option>'];
  for (const team of eventData.teams) {
    options.push(
      `<option value="${team.id}" ${team.id === selectedId ? "selected" : ""}>${escapeHtml(team.name)}</option>`
    );
  }
  return options.join("");
}

function laneGridHTML(heat) {
  const editable = isEditableHeat(heat);
  const existingMax = heat.heat_lanes.reduce(
    (max, lane) => Math.max(max, lane.lane_number),
    0
  );
  const draftCount =
    heatForm && heatForm.mode === "edit" && heatForm.heatId === heat.id
      ? heatForm.laneCount
      : 0;
  const maxLane = Math.max(existingMax, draftCount);
  if (maxLane === 0) {
    return '<div class="empty-state"><p>Nenhuma raia configurada.</p></div>';
  }
  let cells = "";
  for (let number = 1; number <= maxLane; number += 1) {
    const lane = heat.heat_lanes.find((item) => item.lane_number === number);
    const empty = !lane || (!lane.participant_name && !lane.team_id);
    cells += `
      <div class="lane-cell ${empty ? "empty" : ""}">
        <div class="lane-title">RAIA ${number}</div>
        <label>Participante</label>
        <input type="text" data-lane-input="${number}" placeholder="Nome"
          value="${escapeHtml(lane ? lane.participant_name || "" : "")}"
          ${editable ? "" : "disabled"} />
        <label style="margin-top: 8px">Equipe</label>
        <select data-lane-team="${number}" ${editable ? "" : "disabled"}>
          ${teamOptions(lane ? lane.team_id : null)}
        </select>
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
  const collapsed = !expanded.has(heat.id);
  const editable = isEditableHeat(heat);
  return `
    <div class="accordion ${collapsed ? "collapsed" : ""}" data-heat-acc="${heat.id}">
      <div class="accordion-header" draggable="true" data-drag-id="${heat.id}">
        <span class="drag-handle">⠿</span>
        <span class="accordion-title" data-action="toggle-heat" data-id="${heat.id}">
          <strong>${heat.order_num}.</strong> ${escapeHtml(heat.name)}
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
  const editing = heatForm.mode === "edit";
  const heat = editing
    ? eventData.heats.find((item) => item.id === heatForm.heatId)
    : null;
  const type = heat ? heat.heat_type : "bateria";
  const distance = heat ? heat.distance_m : 50;
  const duration = heat
    ? Math.round((heat.duration_s || 10800) / 3600)
    : 3;
  const laneCount = heatForm.laneCount || 3;
  return `
    <div class="form-card" id="heat-form">
      <h2>${editing ? "Editar bateria" : "Nova bateria"}</h2>
      <div class="grid">
        <div>
          <label>Nome da bateria</label>
          <input id="hf-name" type="text" placeholder="Ex: 50m livre masculino sub-12"
            value="${escapeHtml(heat ? heat.name : "")}" />
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

function renderHeats() {
  if (!eventData) return;
  const sorted = [...eventData.heats].sort((a, b) => a.order_num - b.order_num);
  els.heats.innerHTML = `
    <div class="section-head">
      <h2>Baterias</h2>
      <button class="primary" data-action="new-heat">+ Nova Bateria</button>
    </div>
    ${heatForm ? heatFormHTML() : ""}
    ${
      sorted.length
        ? sorted.map(accordionHTML).join("")
        : '<div class="empty-state"><p>Nenhuma bateria criada.</p><p class="muted">Clique em "+ Nova Bateria" para começar.</p></div>'
    }
  `;
  wireHeatForm();
  wireDragAndDrop();
}

function wireDragAndDrop() {
  els.heats.querySelectorAll("[data-drag-id]").forEach((header) => {
    header.addEventListener("dragstart", (event) => {
      dragId = header.dataset.dragId;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragId);
      header.closest(".accordion").classList.add("dragging");
    });
    header.addEventListener("dragend", () => {
      header.closest(".accordion").classList.remove("dragging");
      dragId = null;
    });
  });
  els.heats.querySelectorAll(".accordion").forEach((accordion) => {
    accordion.addEventListener("dragover", (event) => event.preventDefault());
    accordion.addEventListener("drop", (event) => {
      event.preventDefault();
      handleDrop(accordion.dataset.heatAcc);
    });
  });
}

async function handleDrop(targetId) {
  if (!dragId || dragId === targetId) return;
  if (eventData.heats.some((heat) => !isEditableHeat(heat))) {
    showToast("Não é possível reordenar com provas já iniciadas", true);
    return;
  }
  const ordered = [...eventData.heats].sort((a, b) => a.order_num - b.order_num);
  const from = ordered.findIndex((heat) => heat.id === dragId);
  const to = ordered.findIndex((heat) => heat.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  try {
    for (let index = 0; index < ordered.length; index += 1) {
      const heat = ordered[index];
      if (heat.order_num !== index + 1) {
        await api("PATCH", `/api/heats/${heat.id}`, { order_num: index + 1 });
      }
    }
    await refresh();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
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
  const editing = heatForm.mode === "edit";
  const heat = editing
    ? eventData.heats.find((item) => item.id === heatForm.heatId)
    : null;
  const type = editing
    ? heat.heat_type
    : form.querySelector('input[name="hf-type"]:checked').value;
  const laneCount = Number(form.querySelector("#hf-lanes").value);

  const payload = { name };
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
      const created = await api("POST", `/api/events/${eventId}/heats`, {
        ...payload,
        heat_type: type,
      });
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
    expanded.add(heatId);
    heatForm = null;
  });
}

function saveLaneInputs(heatId, numbers) {
  const accordion = els.heats.querySelector(`[data-heat-acc="${heatId}"]`);
  if (!accordion) return [];
  return numbers.map((number) => {
    const participant = accordion.querySelector(`[data-lane-input="${number}"]`);
    const team = accordion.querySelector(`[data-lane-team="${number}"]`);
    return {
      lane_number: number,
      participant_name:
        participant && participant.value.trim() ? participant.value.trim() : null,
      team_id: team && team.value ? team.value : null,
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

async function saveLane(heatId, laneNumber, button) {
  const lanes = saveLaneInputs(heatId, [laneNumber]);
  await withButton(button, async () => {
    await api("POST", `/api/heats/${heatId}/lanes`, { lanes });
  });
}

async function saveAllLanes(heatId, button) {
  const lanes = saveLaneInputs(heatId, laneNumbersOf(heatId));
  await withButton(button, async () => {
    await api("POST", `/api/heats/${heatId}/lanes`, { lanes });
  });
}

async function deleteHeat(heatId) {
  const heat = eventData.heats.find((item) => item.id === heatId);
  if (!window.confirm(`Deletar a bateria "${heat ? heat.name : ""}"?`)) return;
  try {
    await api("DELETE", `/api/heats/${heatId}`);
    expanded.delete(heatId);
    await refresh();
    showToast("Bateria excluída");
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

function renderTeams() {
  if (!eventData) return;
  let html = `
    <div class="section-head">
      <h2>Equipes</h2>
      <button class="primary" data-action="new-team">+ Nova Equipe</button>
    </div>`;
  if (teamsFormOpen) {
    html += `
      <div class="form-card">
        <div class="row">
          <input id="team-name-input" type="text" placeholder="Nome da equipe" />
          <button class="primary" data-action="confirm-team">Confirmar</button>
          <button data-action="cancel-team">Cancelar</button>
        </div>
        <div class="field-error" id="team-error" hidden></div>
      </div>`;
  }
  if (!eventData.teams.length) {
    html += `
      <div class="empty-state">
        <p>Nenhuma equipe cadastrada.</p>
        <p class="muted">Crie as equipes antes de configurar as raias.</p>
      </div>`;
  } else {
    html += '<div class="list">';
    for (const team of eventData.teams) {
      const count = teamParticipantCount(team.id);
      html += `
        <div class="list-item">
          <input type="text" data-team-name="${team.id}" value="${escapeHtml(team.name)}" style="max-width: 280px" />
          <span class="muted">${pluralize(count, "participante")}</span>
          <button class="danger" data-action="delete-team" data-id="${team.id}"
            ${count === 0 ? "" : 'disabled title="Equipe com participantes inscritos"'}>🗑</button>
        </div>`;
    }
    html += "</div>";
  }
  els.teams.innerHTML = html;

  els.teams.querySelectorAll("[data-team-name]").forEach((input) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") input.blur();
    });
    input.addEventListener("change", () => commitTeamRename(input));
  });
  if (teamsFormOpen) {
    const nameInput = document.getElementById("team-name-input");
    if (nameInput) nameInput.focus();
  }
}

async function commitTeamRename(input) {
  const team = eventData.teams.find((item) => item.id === input.dataset.teamName);
  if (!team) return;
  const newName = input.value.trim();
  if (!newName || newName === team.name) {
    input.value = team.name;
    return;
  }
  if (!window.confirm(`Renomear "${team.name}" para "${newName}"?`)) {
    input.value = team.name;
    return;
  }
  try {
    await renameTeam(team, newName);
    await refresh();
    showToast("Equipe renomeada");
  } catch (error) {
    input.value = team.name;
    showToast(`Erro: ${error.message}`, true);
  }
}

async function renameTeam(team, newName) {
  const created = await api("POST", `/api/events/${eventId}/teams`, {
    name: newName,
  });
  const affected = [];
  for (const heat of eventData.heats) {
    const lanes = heat.heat_lanes.filter((lane) => lane.team_id === team.id);
    if (lanes.length) affected.push({ heat, lanes });
  }
  const blocked = affected.filter((item) => !isEditableHeat(item.heat));
  if (blocked.length) {
    await api("DELETE", `/api/teams/${created.id}`);
    throw new Error(
      "prova já iniciada usa esta equipe — renomeie após encerrá-la"
    );
  }
  for (const { heat, lanes } of affected) {
    await api("POST", `/api/heats/${heat.id}/lanes`, {
      lanes: lanes.map((lane) => ({
        lane_number: lane.lane_number,
        participant_name: lane.participant_name,
        team_id: created.id,
      })),
    });
  }
  await api("DELETE", `/api/teams/${team.id}`);
}

async function createTeam(button) {
  const input = document.getElementById("team-name-input");
  const name = input.value.trim();
  if (!name) {
    setFieldError("team-error", "Informe o nome da equipe");
    return;
  }
  setFieldError("team-error", "");
  await withButton(button, async () => {
    await api("POST", `/api/events/${eventId}/teams`, { name });
    teamsFormOpen = false;
  });
}

async function deleteTeam(teamId) {
  const team = eventData.teams.find((item) => item.id === teamId);
  if (!window.confirm(`Excluir a equipe "${team ? team.name : ""}"?`)) return;
  try {
    await api("DELETE", `/api/teams/${teamId}`);
    await refresh();
    showToast("Equipe excluída");
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

function renderSettings() {
  if (!eventData) return;
  els.settings.innerHTML = `
    <div class="panel">
      <h2>Configurações do evento</h2>
      <div class="grid">
        <div>
          <label>Nome completo</label>
          <input id="set-name" type="text" value="${escapeHtml(eventData.name)}" />
        </div>
        <div>
          <label>Local</label>
          <input id="set-location" type="text" value="${escapeHtml(eventData.location || "")}" />
        </div>
        <div>
          <label>Data</label>
          <input id="set-date" type="date" value="${eventData.date || ""}" />
        </div>
        <div>
          <label>Tamanho da piscina</label>
          <div class="radio-row">
            <label><input type="radio" name="set-pool" value="25" ${eventData.pool_length_m === 25 ? "checked" : ""} /> 25m</label>
            <label><input type="radio" name="set-pool" value="50" ${eventData.pool_length_m === 50 ? "checked" : ""} /> 50m</label>
          </div>
        </div>
      </div>
      <button class="primary" data-action="save-settings">Salvar configurações</button>
      <div class="field-error" id="set-error" hidden></div>
    </div>
    <div class="panel">
      <h2>Zona de perigo</h2>
      <button class="danger" data-action="delete-event" ${eventData.status === "draft" ? "" : "disabled"}>🗑 Excluir evento</button>
      ${eventData.status === "draft" ? "" : '<p class="muted">Só é possível excluir eventos em rascunho.</p>'}
    </div>
  `;
}

async function saveSettings(button) {
  const pool = document.querySelector('input[name="set-pool"]:checked');
  const payload = {
    name: document.getElementById("set-name").value.trim(),
    location: document.getElementById("set-location").value.trim() || null,
    date: document.getElementById("set-date").value || null,
    pool_length_m: pool ? Number(pool.value) : eventData.pool_length_m,
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
  if (typed.trim() !== eventData.name) {
    showToast("Nome não confere — exclusão cancelada", true);
    return;
  }
  try {
    await api("DELETE", `/api/events/${eventId}`);
    window.location.href = "index.html";
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

function switchSection(section) {
  if (section === activeSection) return;
  if (dirty && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) {
    return;
  }
  setDirty(false);
  activeSection = section;
  for (const name of ["overview", "heats", "teams", "settings"]) {
    els[name].hidden = name !== section;
  }
  renderSidebar();
  els.sidebar.classList.remove("open");
}

els.main.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "new-heat") {
    heatForm = { mode: "create", laneCount: 3 };
    renderHeats();
  } else if (action === "edit-heat") {
    const heat = eventData.heats.find((item) => item.id === target.dataset.id);
    heatForm = {
      mode: "edit",
      heatId: target.dataset.id,
      laneCount: Math.max(
        1,
        heat.heat_lanes.reduce((max, lane) => Math.max(max, lane.lane_number), 0)
      ),
    };
    renderHeats();
  } else if (action === "cancel-heat-form") {
    heatForm = null;
    renderHeats();
  } else if (action === "save-heat-form") {
    saveHeatForm(target);
  } else if (action === "delete-heat") {
    deleteHeat(target.dataset.id);
  } else if (action === "toggle-heat") {
    const id = target.dataset.id;
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
    renderHeats();
  } else if (action === "save-lane") {
    saveLane(Number(target.dataset.heat), Number(target.dataset.lane), target);
  } else if (action === "save-all-lanes") {
    saveAllLanes(target.dataset.heat, target);
  } else if (action === "open-heat") {
    expanded.add(target.dataset.id);
    if (dirty && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) return;
    setDirty(false);
    activeSection = "heats";
    els.overview.hidden = true;
    els.heats.hidden = false;
    els.teams.hidden = true;
    els.settings.hidden = true;
    renderSidebar();
    renderHeats();
  } else if (action === "new-team") {
    teamsFormOpen = true;
    renderTeams();
  } else if (action === "cancel-team") {
    teamsFormOpen = false;
    renderTeams();
  } else if (action === "confirm-team") {
    createTeam(target);
  } else if (action === "delete-team") {
    deleteTeam(target.dataset.id);
  } else if (action === "save-settings") {
    saveSettings(target);
  } else if (action === "delete-event") {
    deleteEvent();
  }
});

els.main.addEventListener("input", () => setDirty(true));
els.eventName.addEventListener("input", () => setDirty(true));
els.eventName.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.eventName.blur();
});
els.eventName.addEventListener("change", async () => {
  const name = els.eventName.value.trim();
  if (!name || name === eventData.name) {
    els.eventName.value = eventData.name;
    return;
  }
  try {
    await api("PATCH", `/api/events/${eventId}`, { name });
    setDirty(false);
    await refresh();
    showToast("Nome atualizado");
  } catch (error) {
    els.eventName.value = eventData.name;
    showToast(`Erro: ${error.message}`, true);
  }
});

document.querySelectorAll(".sidebar-nav button").forEach((button) => {
  button.addEventListener("click", () => switchSection(button.dataset.section));
});

els.hamburger.addEventListener("click", () => {
  els.sidebar.classList.toggle("open");
});

window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "heat_state" && eventData) {
    const index = eventData.heats.findIndex((heat) => heat.id === message.payload.id);
    if (index >= 0) eventData.heats[index] = message.payload;
    else eventData.heats.push(message.payload);
    if (activeSection === "overview" && !dirty) renderOverview();
    renderSidebar();
  }
});

ws.onStatusChange = () => {};

loadEvent().catch((error) => {
  els.overview.innerHTML = `
    <div class="panel">
      <p class="muted">Erro ao carregar evento: ${escapeHtml(error.message)}</p>
      <a href="index.html">← Voltar para Home</a>
    </div>`;
});
ws.connect();
