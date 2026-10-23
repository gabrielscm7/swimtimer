import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { pluralize, showToast, statusLabel } from "../common/ui.js";
import {
  accordionHTML,
  heatFormHTML,
  wireAthleteDatalist,
  wireHeatDragAndDrop,
  wireHeatForm,
} from "./baterias.js";
import { els, state } from "./state.js";
import {
  heatsOfProva,
  isEditableProva,
  provaMeta,
  provasSorted,
  refresh,
  setFieldError,
  teamLogoHTML,
  withButton,
} from "./ui.js";


function provaFormHTML() {
  const editing = state.provaForm.mode === "edit";
  const prova = editing
    ? (state.eventData.provas || []).find((item) => item.id === state.provaForm.provaId)
    : null;
  const locked = prova ? !isEditableProva(prova) : false;
  const name = prova ? prova.name : "";
  const order = prova ? prova.order_num : "";
  const stroke = prova ? prova.stroke || "" : "";
  const distance = prova && prova.distance_m ? prova.distance_m : "";
  const category = prova ? prova.category || "" : "";
  const naipe = prova ? prova.naipe || "" : "";
  const mixedRanking = prova ? prova.mixed_ranking || "both" : "both";
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
          <label>Ordem no programa do evento</label>
          <input id="pf-order" type="number" min="1" value="${escapeHtml(order)}"
            ${locked ? "disabled" : ""} />
          <p class="muted" style="margin:4px 0 0">Única entre as provas do evento; vazio = próxima.</p>
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
          <label>Naipe</label>
          <select id="pf-naipe" ${locked ? "disabled" : ""}>
            <option value="" ${naipe === "" ? "selected" : ""}>Não definido</option>
            <option value="F" ${naipe === "F" ? "selected" : ""}>Feminino</option>
            <option value="M" ${naipe === "M" ? "selected" : ""}>Masculino</option>
            <option value="MISTO" ${naipe === "MISTO" ? "selected" : ""}>Misto (M e F)</option>
          </select>
        </div>
        <div>
          <label>Ranking da prova</label>
          <select id="pf-mixed-ranking">
            <option value="both" ${mixedRanking === "both" ? "selected" : ""}>Geral + por naipe</option>
            <option value="overall" ${mixedRanking === "overall" ? "selected" : ""}>Geral</option>
            <option value="by_naipe" ${mixedRanking === "by_naipe" ? "selected" : ""}>Por naipe</option>
          </select>
          <p class="muted" style="margin:4px 0 0">Aplicado a provas mistas (M e F).</p>
        </div>
        <div>
          <label>Categoria (idade)</label>
          <input id="pf-category" type="text" maxlength="60" placeholder="Ex: SUB-12"
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
    const mode = data.mixed_ranking || "both";
    const standingsTable = (entries) =>
      entries.length
        ? `<table class="data-table"><thead><tr><th>Pos.</th><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead><tbody>${entries
            .map((entry) => entryRow(entry, true))
            .join("")}</tbody></table>`
        : '<p class="muted">Nenhum resultado válido ainda.</p>';

    const sections = [];
    if (mode !== "by_naipe") {
      sections.push(`
        <h3>Classificação geral</h3>
        ${standingsTable(data.standings || [])}`);
    }
    if (mode !== "overall" && data.standings_by_naipe) {
      for (const naipe of ["M", "F"]) {
        sections.push(`
          <h3 style="margin-top:18px">Classificação ${GestaoLogic.naipeLabel(naipe)}</h3>
          ${standingsTable(data.standings_by_naipe[naipe] || [])}`);
      }
    }
    body = `
      ${sections.join("")}
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
  const collapsed = !state.expandedProvas.has(prova.id);
  const editable = isEditableProva(prova);
  const heats = heatsOfProva(prova.id);
  const meta = provaMeta(prova);
  const classification = state.classificationByProva[prova.id];
  const isEditing = state.provaForm && state.provaForm.mode === "edit" && state.provaForm.provaId === prova.id;
  const isAddingHeat = state.heatForm && state.heatForm.provaId === prova.id;
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
  if (!state.eventData) return;
  const provas = provasSorted();
  const datalist = `<datalist id="athlete-datalist">${state.allAthletes
    .map(
      (athlete) =>
        `<option value="${escapeHtml(GestaoLogic.athleteOptionLabel(athlete))}">${escapeHtml(
          [GestaoLogic.naipeLabel(athlete.naipe), athlete.category]
            .filter(Boolean)
            .join(" · ")
        )}</option>`
    )
    .join("")}</datalist>`;
  els.heats.innerHTML = `
    ${datalist}
    <div class="section-head">
      <h2>Provas e baterias</h2>
      <button class="primary" data-action="new-prova">+ Nova Prova</button>
    </div>
    <p class="muted">Nas raias, digite para buscar um atleta cadastrado ou informe um nome manual.</p>
    ${state.provaForm && state.provaForm.mode === "create" ? provaFormHTML() : ""}
    ${
      provas.length
        ? provas.map(provaCardHTML).join("")
        : '<div class="empty-state"><p>Nenhuma prova criada.</p><p class="muted">Clique em "+ Nova Prova" para começar.</p></div>'
    }
  `;
  wireHeatForm();
  wireProvaDragAndDrop();
  wireHeatDragAndDrop();
  wireAthleteDatalist();
}


async function handleProvaDrop(targetId) {
  if (!state.dragProvaId || state.dragProvaId === targetId) return;
  const ordered = provasSorted();
  if (ordered.some((prova) => !isEditableProva(prova))) {
    showToast("Não é possível reordenar com provas já iniciadas", true);
    return;
  }
  const from = ordered.findIndex((prova) => prova.id === state.dragProvaId);
  const to = ordered.findIndex((prova) => prova.id === targetId);
  if (from < 0 || to < 0) return;
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  try {
    await api("PUT", `/api/events/${eventId}/provas/order`, {
      ids: ordered.map((prova) => prova.id),
    });
    await refresh();
  } catch (error) {
    showToast(gestaoErrorMessage(error), true);
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
  const editing = state.provaForm.mode === "edit";
  const payload = {
    name,
    stroke: form.querySelector("#pf-stroke").value.trim() || null,
    category: form.querySelector("#pf-category").value.trim() || null,
    naipe: form.querySelector("#pf-naipe").value || null,
    mixed_ranking: form.querySelector("#pf-mixed-ranking").value,
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
      await api("PATCH", `/api/provas/${state.provaForm.provaId}`, payload);
    } else {
      const created = await api(
        "POST",
        `/api/events/${eventId}/provas`,
        payload
      );
      state.expandedProvas.add(created.id);
    }
    state.provaForm = null;
  });
}


async function deleteProva(provaId) {
  const prova = (state.eventData.provas || []).find((item) => item.id === provaId);
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
    delete state.classificationByProva[provaId];
    state.expandedProvas.delete(provaId);
    await refresh();
    showToast("Prova excluída");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


async function loadClassification(provaId) {
  try {
    state.classificationByProva[provaId] = await api(
      "GET",
      `/api/provas/${provaId}/classification`
    );
    state.expandedProvas.add(provaId);
    renderHeats();
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


function scheduleClassificationReload(provaId) {
  if (!state.classificationByProva[provaId]) return;
  clearTimeout(state.classificationTimer);
  state.classificationTimer = setTimeout(() => {
    api("GET", `/api/provas/${provaId}/classification`)
      .then((data) => {
        state.classificationByProva[provaId] = data;
        if (state.activeSection === "heats") renderHeats();
      })
      .catch(() => {});
  }, 300);
}


function upsertProva(payload) {
  if (!state.eventData) return;
  const provas = state.eventData.provas || (state.eventData.provas = []);
  const index = provas.findIndex((item) => item.id === payload.id);
  const summary = {
    id: payload.id,
    event_id: payload.event_id,
    name: payload.name,
    order_num: payload.order_num,
    stroke: payload.stroke,
    distance_m: payload.distance_m,
    category: payload.category,
    naipe: payload.naipe,
    mixed_ranking: payload.mixed_ranking,
    consolidate_results: payload.consolidate_results,
    classification_criterion: payload.classification_criterion,
    status: payload.status,
    heat_count: payload.heat_count,
  };
  if (index >= 0) provas[index] = summary;
  else provas.push(summary);

  if (Array.isArray(payload.heats)) {
    const ids = new Set(payload.heats.map((heat) => heat.id));
    state.eventData.heats = state.eventData.heats.filter(
      (heat) => heat.prova_id !== payload.id || ids.has(heat.id)
    );
    for (const heat of payload.heats) {
      const heatIndex = state.eventData.heats.findIndex(
        (item) => item.id === heat.id
      );
      if (heatIndex >= 0) state.eventData.heats[heatIndex] = heat;
      else state.eventData.heats.push(heat);
    }
  }
}

function wireProvaDragAndDrop() {
  els.heats.querySelectorAll("[data-drag-prova]").forEach((handle) => {
    handle.addEventListener("dragstart", (event) => {
      state.dragProvaId = handle.dataset.dragProva;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", state.dragProvaId);
      handle.closest(".prova-card").classList.add("dragging");
    });
    handle.addEventListener("dragend", () => {
      handle.closest(".prova-card").classList.remove("dragging");
      state.dragProvaId = null;
    });
  });

  els.heats.querySelectorAll(".prova-card").forEach((card) => {
    card.addEventListener("dragover", (event) => {
      if (state.dragProvaId) event.preventDefault();
    });
    card.addEventListener("drop", (event) => {
      if (!state.dragProvaId) return;
      event.preventDefault();
      handleProvaDrop(card.dataset.provaCard);
    });
  });
}


export {
  classificationHTML,
  classificationStatusLabel,
  deleteProva,
  handleProvaDrop,
  loadClassification,
  provaCardHTML,
  provaFormHTML,
  renderHeats,
  saveProvaForm,
  scheduleClassificationReload,
  upsertProva,
  wireProvaDragAndDrop,
};
