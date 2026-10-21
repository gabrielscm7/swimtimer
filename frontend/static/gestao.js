const DISTANCES = [25, 50, 100, 200, 400, 800, 1500];
const DURATIONS = [1, 2, 3, 4, 5];
const LANE_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8];
const MAX_LOGO_BYTES = 1024 * 1024;

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
const expandedProvas = new Set();
let heatForm = null;
let provaForm = null;
let teamsFormOpen = false;
let dirty = false;
let dragProvaId = null;
let dragHeat = null;
const classificationByProva = {};
let classificationTimer = null;

function provasSorted() {
  return [...(eventData.provas || [])].sort(
    (a, b) => a.order_num - b.order_num
  );
}

function heatsOfProva(provaId) {
  return eventData.heats
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
  return heat.heat_lanes.filter((lane) => lane.participant_name);
}

function teamParticipantCount(teamId) {
  return eventData.heats.reduce(
    (sum, heat) =>
      sum + heat.heat_lanes.filter((lane) => lane.team_id === teamId).length,
    0
  );
}

function provaMeta(prova) {
  const parts = [];
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
  const provas = provasSorted();
  const heats = eventData.heats;
  const finished = heats.filter((heat) => heat.status === "finished").length;
  const teams = eventData.teams.length;
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
        <td>${heat.order_num}</td>
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
      <div class="summary-card"><div class="value">${participants}</div><div class="label">Participantes</div></div>
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
          ? `<table class="data-table"><thead><tr><th>Prova</th><th>Ordem</th><th>Nome</th><th>Tipo</th><th>Distância</th><th>Participantes</th><th>Status</th></tr></thead><tbody>${heatRows}</tbody></table>`
          : `<div class="empty-state"><p>Nenhuma bateria criada.</p></div>`
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
    heatForm &&
    heatForm.mode === "edit" &&
    heatForm.heatId === heat.id &&
    heatForm.provaId === heat.prova_id
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
    <div class="accordion ${collapsed ? "collapsed" : ""}" data-heat-acc="${heat.id}" data-prova="${heat.prova_id}">
      <div class="accordion-header" draggable="true" data-drag-heat="${heat.id}" data-prova="${heat.prova_id}">
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
  const prova = (eventData.provas || []).find(
    (item) => item.id === (heat ? heat.prova_id : heatForm.provaId)
  );
  const type = heat ? heat.heat_type : "bateria";
  const distance = heat ? heat.distance_m : 50;
  const duration = heat
    ? Math.round((heat.duration_s || 10800) / 3600)
    : 3;
  const laneCount = heatForm.laneCount || 3;
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

function provaFormHTML() {
  const editing = provaForm.mode === "edit";
  const prova = editing
    ? (eventData.provas || []).find((item) => item.id === provaForm.provaId)
    : null;
  const locked = prova ? !isEditableProva(prova) : false;
  const name = prova ? prova.name : "";
  const order = prova ? prova.order_num : "";
  const stroke = prova ? prova.stroke || "" : "";
  const distance = prova && prova.distance_m ? prova.distance_m : "";
  const category = prova ? prova.category || "" : "";
  const consolidate = prova ? prova.consolidate_results : true;
  return `
    <div class="form-card" id="prova-form">
      <h2>${editing ? "Editar prova" : "Nova prova"}</h2>
      <div class="grid">
        <div>
          <label>Nome da prova</label>
          <input id="pf-name" type="text" placeholder="Ex: 100m livres masculino"
            value="${escapeHtml(name)}" />
        </div>
        <div>
          <label>Ordem</label>
          <input id="pf-order" type="number" min="1" value="${escapeHtml(order)}"
            ${locked ? "disabled" : ""} />
        </div>
        <div>
          <label>Modalidade / estilo</label>
          <input id="pf-stroke" type="text" placeholder="Ex: livre, costas, peito"
            value="${escapeHtml(stroke)}" />
        </div>
        <div>
          <label>Distância (m)</label>
          <input id="pf-distance" type="number" min="1" placeholder="Ex: 100"
            value="${escapeHtml(distance)}" ${locked ? "disabled" : ""} />
        </div>
        <div>
          <label>Categoria / gênero</label>
          <input id="pf-category" type="text" placeholder="Ex: masculino, sub-12"
            value="${escapeHtml(category)}" />
        </div>
        <div>
          <label>Critério de classificação</label>
          <select id="pf-criterion" ${locked ? "disabled" : ""}>
            <option value="lowest_time">Menor tempo</option>
          </select>
        </div>
      </div>
      <label class="checkbox-row">
        <input type="checkbox" id="pf-consolidate" ${consolidate ? "checked" : ""} ${locked ? "disabled" : ""} />
        Gerar classificação consolidada da prova (menor tempo)
      </label>
      ${locked ? '<p class="muted">Prova já iniciada — configuração operacional bloqueada.</p>' : ""}
      <div class="row">
        <button class="primary" data-action="save-prova-form">Salvar</button>
        <button data-action="cancel-prova-form">Cancelar</button>
      </div>
      <div class="field-error" id="pf-error" hidden></div>
    </div>`;
}

function classificationStatusLabel(status) {
  return (
    {
      valid: "Válido",
      dq: "Desclassificado",
      no_time: "Sem tempo",
      pending: "Em andamento",
    }[status] || status
  );
}

function classificationHTML(prova, data) {
  const statusBadge = data.is_provisional
    ? '<span class="status-pill ready_check">Provisória</span>'
    : '<span class="status-pill finished">Definitiva</span>';
  const provaStatus = `<span class="status-pill ${data.status}">${statusLabel(
    data.status
  )}</span>`;

  function entryRow(entry, showPosition) {
    return `
      <tr>
        ${showPosition ? `<td class="pos">${entry.position ?? "—"}</td>` : ""}
        <td>${escapeHtml(entry.participant_name || "—")}</td>
        <td class="team-cell">
          ${teamLogoHTML(entry.team_logo_url, entry.team_name)}
          <span>${escapeHtml(entry.team_name || "—")}</span>
        </td>
        <td class="time">${entry.race_time_display || "—"}</td>
        <td>${classificationStatusLabel(entry.classification_status)}
          ${entry.tied ? '<span class="status-pill">empate</span>' : ""}</td>
      </tr>`;
  }

  let body;
  if (!data.consolidate_results) {
    body = (data.battery_results || [])
      .map(
        (battery) => `
        <div class="classification-battery">
          <h3>${escapeHtml(battery.heat_name)} · ${statusLabel(battery.status)}</h3>
          ${
            battery.entries.length
              ? `<table class="data-table"><thead><tr><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead><tbody>${battery.entries
                  .map((entry) => entryRow(entry, false))
                  .join("")}</tbody></table>`
              : '<p class="muted">Sem participantes nesta bateria.</p>'
          }
        </div>`
      )
      .join("");
    body += `<p class="muted">Classificação consolidada desativada para esta prova.</p>`;
  } else {
    const standings = data.standings || [];
    body = `
      <h3>Classificação geral</h3>
      ${
        standings.length
          ? `<table class="data-table"><thead><tr><th>Pos.</th><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead><tbody>${standings
              .map((entry) => entryRow(entry, true))
              .join("")}</tbody></table>`
          : '<p class="muted">Nenhum resultado válido ainda.</p>'
      }
      ${
        (data.excluded || []).length
          ? `<h3 style="margin-top:18px">Fora da classificação</h3>
             <table class="data-table"><thead><tr><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead><tbody>${data.excluded
               .map((entry) => entryRow(entry, false))
               .join("")}</tbody></table>`
          : ""
      }
      <p class="muted" style="margin-top:10px">${
        data.is_provisional
          ? "Classificação provisória: há baterias pendentes ou em andamento."
          : "Classificação definitiva: todas as baterias foram finalizadas."
      }</p>`;
  }

  return `
    <div class="classification-panel">
      <div class="row between">
        <div class="row">
          <h3>Classificação — ${escapeHtml(prova.name)}</h3>
          ${statusBadge}${provaStatus}
        </div>
        <button data-action="refresh-classification" data-id="${prova.id}">↻ Atualizar</button>
      </div>
      ${body}
    </div>`;
}

function provaCardHTML(prova) {
  const collapsed = !expandedProvas.has(prova.id);
  const editable = isEditableProva(prova);
  const heats = heatsOfProva(prova.id);
  const meta = provaMeta(prova);
  const classification = classificationByProva[prova.id];
  const isEditing = provaForm && provaForm.mode === "edit" && provaForm.provaId === prova.id;
  const isAddingHeat = heatForm && heatForm.provaId === prova.id;
  return `
    <div class="prova-card ${collapsed ? "collapsed" : ""}" data-prova-card="${prova.id}">
      <div class="prova-header">
        <span class="drag-handle" draggable="true" data-drag-prova="${prova.id}">⠿</span>
        <span class="prova-title" data-action="toggle-prova" data-id="${prova.id}">
          <strong>${prova.order_num}.</strong> ${escapeHtml(prova.name)}
          ${meta ? `<span class="muted"> · ${escapeHtml(meta)}</span>` : ""}
        </span>
        <span class="status-pill ${prova.status}">${statusLabel(prova.status)}</span>
        <span class="status-pill">${pluralize(heats.length, "bateria")}</span>
        ${prova.consolidate_results ? '<span class="status-pill">consolidada</span>' : '<span class="status-pill">por bateria</span>'}
        <span class="spacer"></span>
        <button data-action="classification" data-id="${prova.id}">Classificação</button>
        ${editable ? `<button data-action="edit-prova" data-id="${prova.id}">✏️</button>` : ""}
        ${editable ? `<button class="danger" data-action="delete-prova" data-id="${prova.id}">🗑</button>` : ""}
        <button class="primary" data-action="new-heat" data-prova="${prova.id}" ${editable ? "" : "disabled"}>+ Bateria</button>
      </div>
      <div class="prova-body">
        ${isEditing ? provaFormHTML() : ""}
        ${classification ? classificationHTML(prova, classification) : ""}
        ${isAddingHeat ? heatFormHTML() : ""}
        ${
          heats.length
            ? heats.map(accordionHTML).join("")
            : '<div class="empty-state"><p>Nenhuma bateria nesta prova.</p><p class="muted">Use "+ Bateria" para criar.</p></div>'
        }
      </div>
    </div>`;
}

function renderHeats() {
  if (!eventData) return;
  const provas = provasSorted();
  els.heats.innerHTML = `
    <div class="section-head">
      <h2>Provas e baterias</h2>
      <button class="primary" data-action="new-prova">+ Nova Prova</button>
    </div>
    ${provaForm && provaForm.mode === "create" ? provaFormHTML() : ""}
    ${
      provas.length
        ? provas.map(provaCardHTML).join("")
        : '<div class="empty-state"><p>Nenhuma prova criada.</p><p class="muted">Clique em "+ Nova Prova" para começar.</p></div>'
    }
  `;
  wireHeatForm();
  wireDragAndDrop();
}

function wireDragAndDrop() {
  els.heats.querySelectorAll("[data-drag-heat]").forEach((header) => {
    header.addEventListener("dragstart", (event) => {
      dragHeat = {
        id: header.dataset.dragHeat,
        provaId: header.dataset.prova,
      };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragHeat.id);
      header.closest(".accordion").classList.add("dragging");
    });
    header.addEventListener("dragend", () => {
      header.closest(".accordion").classList.remove("dragging");
      dragHeat = null;
    });
  });
  els.heats.querySelectorAll("[data-drag-prova]").forEach((handle) => {
    handle.addEventListener("dragstart", (event) => {
      dragProvaId = handle.dataset.dragProva;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragProvaId);
      handle.closest(".prova-card").classList.add("dragging");
    });
    handle.addEventListener("dragend", () => {
      handle.closest(".prova-card").classList.remove("dragging");
      dragProvaId = null;
    });
  });

  els.heats.querySelectorAll(".accordion").forEach((accordion) => {
    accordion.addEventListener("dragover", (event) => {
      if (dragHeat && dragHeat.provaId === accordion.dataset.prova) {
        event.preventDefault();
      }
    });
    accordion.addEventListener("drop", (event) => {
      event.preventDefault();
      handleHeatDrop(accordion.dataset.heatAcc, accordion.dataset.prova);
    });
  });
  els.heats.querySelectorAll(".prova-card").forEach((card) => {
    card.addEventListener("dragover", (event) => {
      if (dragProvaId) event.preventDefault();
    });
    card.addEventListener("drop", (event) => {
      if (!dragProvaId) return;
      event.preventDefault();
      handleProvaDrop(card.dataset.provaCard);
    });
  });
}

async function handleProvaDrop(targetId) {
  if (!dragProvaId || dragProvaId === targetId) return;
  const ordered = provasSorted();
  if (ordered.some((prova) => !isEditableProva(prova))) {
    showToast("Não é possível reordenar com provas já iniciadas", true);
    return;
  }
  const from = ordered.findIndex((prova) => prova.id === dragProvaId);
  const to = ordered.findIndex((prova) => prova.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  try {
    for (let index = 0; index < ordered.length; index += 1) {
      const prova = ordered[index];
      if (prova.order_num !== index + 1) {
        await api("PATCH", `/api/provas/${prova.id}`, {
          order_num: index + 1,
        });
      }
    }
    await refresh();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

async function handleHeatDrop(targetId, provaId) {
  if (!dragHeat || dragHeat.provaId !== provaId || dragHeat.id === targetId) {
    return;
  }
  const ordered = heatsOfProva(provaId);
  if (ordered.some((heat) => !isEditableHeat(heat))) {
    showToast("Não é possível reordenar com baterias já iniciadas", true);
    return;
  }
  const from = ordered.findIndex((heat) => heat.id === dragHeat.id);
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

async function saveProvaForm(button) {
  const form = document.getElementById("prova-form");
  const name = form.querySelector("#pf-name").value.trim();
  if (!name) {
    setFieldError("pf-error", "Informe o nome da prova");
    return;
  }
  setFieldError("pf-error", "");
  const editing = provaForm.mode === "edit";
  const payload = {
    name,
    stroke: form.querySelector("#pf-stroke").value.trim() || null,
    category: form.querySelector("#pf-category").value.trim() || null,
  };
  const orderInput = form.querySelector("#pf-order");
  if (orderInput && !orderInput.disabled && orderInput.value) {
    payload.order_num = Number(orderInput.value);
  }
  const distanceInput = form.querySelector("#pf-distance");
  if (distanceInput && !distanceInput.disabled) {
    payload.distance_m = distanceInput.value
      ? Number(distanceInput.value)
      : null;
  }
  const criterion = form.querySelector("#pf-criterion");
  if (criterion && !criterion.disabled) {
    payload.classification_criterion = criterion.value;
  }
  const consolidate = form.querySelector("#pf-consolidate");
  if (consolidate && !consolidate.disabled) {
    payload.consolidate_results = consolidate.checked;
  }

  await withButton(button, async () => {
    if (editing) {
      await api("PATCH", `/api/provas/${provaForm.provaId}`, payload);
    } else {
      const created = await api(
        "POST",
        `/api/events/${eventId}/provas`,
        payload
      );
      expandedProvas.add(created.id);
    }
    provaForm = null;
  });
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
  const provaId = editing ? heat.prova_id : heatForm.provaId;
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
    expanded.add(heatId);
    expandedProvas.add(provaId);
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

async function deleteProva(provaId) {
  const prova = (eventData.provas || []).find((item) => item.id === provaId);
  const heatCount = heatsOfProva(provaId).length;
  if (
    !window.confirm(
      `Excluir a prova "${prova ? prova.name : ""}" e suas ${heatCount} bateria(s)?`
    )
  ) {
    return;
  }
  try {
    await api("DELETE", `/api/provas/${provaId}`);
    delete classificationByProva[provaId];
    expandedProvas.delete(provaId);
    await refresh();
    showToast("Prova excluída");
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
        <div class="list-item team-item">
          ${teamLogoHTML(team.logo_url, team.name, "medium")}
          <input type="text" data-team-name="${team.id}" value="${escapeHtml(team.name)}" style="max-width: 280px" />
          <span class="muted">${pluralize(count, "participante")}</span>
          <label class="file-btn" title="Enviar/substituir logo (PNG, JPEG, WebP até 1 MB)">
            🖼 Logo
            <input type="file" accept="image/png,image/jpeg,image/webp" data-logo-input="${team.id}" hidden />
          </label>
          ${
            team.logo_url
              ? `<button data-action="remove-logo" data-id="${team.id}" title="Remover logo">✖ Logo</button>`
              : ""
          }
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
  els.teams.querySelectorAll("[data-logo-input]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.files && input.files[0]) {
        uploadTeamLogo(input.dataset.logoInput, input.files[0]);
      }
    });
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
  try {
    await api("PATCH", `/api/teams/${team.id}`, { name: newName });
    await refresh();
    showToast("Equipe renomeada");
  } catch (error) {
    input.value = team.name;
    showToast(`Erro: ${error.message}`, true);
  }
}

async function uploadTeamLogo(teamId, file) {
  if (file.size > MAX_LOGO_BYTES) {
    showToast("Logo maior que 1 MB", true);
    return;
  }
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    showToast("Formato inválido: use PNG, JPEG ou WebP", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch(`/api/teams/${teamId}/logo`, {
      method: "POST",
      body,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (error) {
        /* resposta sem JSON */
      }
      throw new Error(detail);
    }
    await refresh();
    showToast("Logo atualizado");
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

async function removeTeamLogo(teamId) {
  try {
    await api("DELETE", `/api/teams/${teamId}/logo`);
    await refresh();
    showToast("Logo removido");
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
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

async function loadClassification(provaId) {
  try {
    classificationByProva[provaId] = await api(
      "GET",
      `/api/provas/${provaId}/classification`
    );
    expandedProvas.add(provaId);
    renderHeats();
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
          <input id="set-date" type="date" value="${escapeHtml(eventData.date || "")}" />
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

function openSection(section, callback) {
  if (dirty && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) {
    return false;
  }
  setDirty(false);
  activeSection = section;
  for (const name of ["overview", "heats", "teams", "settings"]) {
    els[name].hidden = name !== section;
  }
  renderSidebar();
  if (callback) callback();
  return true;
}

els.main.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "new-prova") {
    provaForm = { mode: "create" };
    renderHeats();
  } else if (action === "edit-prova") {
    provaForm = { mode: "edit", provaId: target.dataset.id };
    expandedProvas.add(target.dataset.id);
    renderHeats();
  } else if (action === "cancel-prova-form") {
    provaForm = null;
    renderHeats();
  } else if (action === "save-prova-form") {
    saveProvaForm(target);
  } else if (action === "delete-prova") {
    deleteProva(target.dataset.id);
  } else if (action === "toggle-prova") {
    const id = target.dataset.id;
    if (expandedProvas.has(id)) expandedProvas.delete(id);
    else expandedProvas.add(id);
    renderHeats();
  } else if (action === "new-heat") {
    heatForm = {
      mode: "create",
      laneCount: 3,
      provaId: target.dataset.prova,
    };
    expandedProvas.add(target.dataset.prova);
    renderHeats();
  } else if (action === "edit-heat") {
    const heat = eventData.heats.find((item) => item.id === target.dataset.id);
    heatForm = {
      mode: "edit",
      heatId: target.dataset.id,
      provaId: heat.prova_id,
      laneCount: Math.max(
        1,
        heat.heat_lanes.reduce((max, lane) => Math.max(max, lane.lane_number), 0)
      ),
    };
    expandedProvas.add(heat.prova_id);
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
  } else if (action === "classification") {
    loadClassification(target.dataset.id);
  } else if (action === "refresh-classification") {
    loadClassification(target.dataset.id);
  } else if (action === "open-prova") {
    expandedProvas.add(target.dataset.id);
    if (openSection("heats")) renderHeats();
  } else if (action === "open-heat") {
    const heat = eventData.heats.find((item) => item.id === target.dataset.id);
    expanded.add(target.dataset.id);
    if (heat) expandedProvas.add(heat.prova_id);
    if (openSection("heats")) renderHeats();
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
  } else if (action === "remove-logo") {
    removeTeamLogo(target.dataset.id);
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

function scheduleClassificationReload(provaId) {
  if (!classificationByProva[provaId]) return;
  clearTimeout(classificationTimer);
  classificationTimer = setTimeout(() => {
    api("GET", `/api/provas/${provaId}/classification`)
      .then((data) => {
        classificationByProva[provaId] = data;
        if (activeSection === "heats") renderHeats();
      })
      .catch(() => {});
  }, 300);
}

function upsertProva(payload) {
  if (!eventData) return;
  const provas = eventData.provas || (eventData.provas = []);
  const index = provas.findIndex((item) => item.id === payload.id);
  const summary = {
    id: payload.id,
    event_id: payload.event_id,
    name: payload.name,
    order_num: payload.order_num,
    stroke: payload.stroke,
    distance_m: payload.distance_m,
    category: payload.category,
    consolidate_results: payload.consolidate_results,
    classification_criterion: payload.classification_criterion,
    status: payload.status,
    heat_count: payload.heat_count,
  };
  if (index >= 0) provas[index] = summary;
  else provas.push(summary);

  if (Array.isArray(payload.heats)) {
    const ids = new Set(payload.heats.map((heat) => heat.id));
    eventData.heats = eventData.heats.filter(
      (heat) => heat.prova_id !== payload.id || ids.has(heat.id)
    );
    for (const heat of payload.heats) {
      const heatIndex = eventData.heats.findIndex(
        (item) => item.id === heat.id
      );
      if (heatIndex >= 0) eventData.heats[heatIndex] = heat;
      else eventData.heats.push(heat);
    }
  }
}

const ws = new WSClient(wsUrl(), (message) => {
  if (!eventData) return;
  if (message.type === "heat_state") {
    const index = eventData.heats.findIndex(
      (heat) => heat.id === message.payload.id
    );
    if (index >= 0) eventData.heats[index] = message.payload;
    else eventData.heats.push(message.payload);
    scheduleClassificationReload(message.payload.prova_id);
    if (activeSection === "overview" && !dirty) renderOverview();
    renderSidebar();
  } else if (message.type === "prova_state") {
    upsertProva(message.payload);
    scheduleClassificationReload(message.payload.id);
    if (activeSection === "overview" && !dirty) renderOverview();
    if (
      activeSection === "heats" &&
      !dirty &&
      !heatForm &&
      !provaForm
    ) {
      renderHeats();
    }
  } else if (message.type === "error") {
    showToast(message.message || "Erro na operação", true);
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
