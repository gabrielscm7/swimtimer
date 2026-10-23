import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { showToast } from "../common/ui.js";
import { els, state } from "./state.js";
import { renderAll, setFieldError, teamOptions, withButton } from "./ui.js";


async function fetchAllAthletes() {
  const pageSize = 200;
  const all = [];
  let offset = 0;
  for (;;) {
    const data = await api(
      "GET",
      `/api/events/${eventId}/athletes?limit=${pageSize}&offset=${offset}`
    );
    all.push(...data.items);
    offset += pageSize;
    if (offset >= data.total) break;
  }
  return all;
}


async function loadAthletePage() {
  const query = GestaoLogic.buildAthleteQuery(state.athletesState);
  const data = await api(
    "GET",
    `/api/events/${eventId}/athletes?${query}`
  );
  state.athletesState.items = data.items;
  state.athletesState.total = data.total;
  state.athletesState.limit = data.limit;
  state.athletesState.offset = data.offset;
}


async function loadAthleteData() {
  state.allAthletes = await fetchAllAthletes();
  await loadAthletePage();
}


function athleteFormHTML() {
  const editing = state.athleteForm.mode === "edit";
  const athlete = editing
    ? state.allAthletes.find((item) => item.id === state.athleteForm.id)
    : null;
  const naipe = athlete ? athlete.naipe : "F";
  return `
    <div class="form-card" id="athlete-form">
      <h2>${editing ? "Editar atleta" : "Novo atleta"}</h2>
      <div class="grid">
        <div>
          <label>Nome</label>
          <input id="af-name" type="text" maxlength="120" placeholder="Nome completo"
            value="${escapeHtml(athlete ? athlete.name : "")}" />
        </div>
        <div>
          <label>Equipe</label>
          <select id="af-team">${teamOptions(athlete ? athlete.team_id : null)}</select>
        </div>
        <div>
          <label>Naipe</label>
          <select id="af-naipe">
            <option value="F" ${naipe === "F" ? "selected" : ""}>Feminino</option>
            <option value="M" ${naipe === "M" ? "selected" : ""}>Masculino</option>
          </select>
        </div>
        <div>
          <label>Categoria</label>
          <input id="af-category" type="text" maxlength="60" placeholder="Ex: SUB-12"
            value="${escapeHtml(athlete ? athlete.category || "" : "")}" />
        </div>
      </div>
      <div class="actions">
        <button class="primary" data-action="confirm-athlete">${editing ? "Salvar" : "Cadastrar"}</button>
        <button data-action="cancel-athlete">Cancelar</button>
      </div>
      <div class="field-error" id="athlete-error" hidden></div>
    </div>`;
}


function athleteImportHTML() {
  if (!state.athleteImport) return "";
  let body = "";
  if (state.athleteImport.busy) {
    body = `<p class="muted">Importando ${escapeHtml(state.athleteImport.fileName)}...</p>`;
  } else if (state.athleteImport.error) {
    body = `<div class="field-error">${escapeHtml(state.athleteImport.error)}</div>`;
  } else if (state.athleteImport.result) {
    const result = state.athleteImport.result;
    body = `<p><strong>${escapeHtml(
      GestaoLogic.importResultSummary(result)
    )}</strong></p>`;
    if (result.errors.length) {
      const shown = result.errors.slice(0, 100);
      body += `
        <table class="data-table">
          <thead><tr><th>Linha</th><th>Campo</th><th>Motivo</th></tr></thead>
          <tbody>${shown
            .map(
              (error) => `<tr>
                <td>${error.line}</td>
                <td>${escapeHtml(error.field || "—")}</td>
                <td>${escapeHtml(GestaoLogic.gestaoErrorMessage(error.message))}</td>
              </tr>`
            )
            .join("")}</tbody>
        </table>`;
      if (result.errors.length > shown.length) {
        body += `<p class="muted">Exibindo os primeiros ${shown.length} erros de ${result.errors.length}.</p>`;
      }
    }
  }
  return `
    <div class="form-card" id="athlete-import">
      <div class="row between">
        <h2>Importar planilha</h2>
        <button class="danger" data-action="close-import" title="Fechar">✖</button>
      </div>
      <div class="import-drop" id="athlete-import-drop">
        <p>Arraste o arquivo aqui ou selecione abaixo.</p>
        <p class="muted">CSV ou XLSX · colunas NOME, EQUIPE, NAIPE, CATEGORIA · até 2 MB e 1000 linhas</p>
        <label class="file-btn">Selecionar arquivo
          <input id="athlete-import-input" type="file" accept=".csv,.xlsx" hidden />
        </label>
      </div>
      ${body}
    </div>`;
}


function athleteResultsHTML() {
  const info = GestaoLogic.paginationInfo(
    state.athletesState.total,
    state.athletesState.limit,
    state.athletesState.offset
  );
  if (!state.athletesState.items.length) {
    return `
      <div class="empty-state">
        <p>Nenhum atleta encontrado.</p>
        <p class="muted">Cadastre manualmente ou importe uma planilha.</p>
      </div>
      <div class="pagination-row">
        <span class="muted">${state.athletesState.total} atleta(s)</span>
      </div>`;
  }
  const rows = state.athletesState.items
    .map(
      (athlete) => `
      <tr>
        <td>${escapeHtml(athlete.name)}</td>
        <td>${escapeHtml(athlete.team_name || "—")}</td>
        <td>${GestaoLogic.naipeLabel(athlete.naipe)}</td>
        <td>${escapeHtml(athlete.category || "—")}</td>
        <td class="row-actions">
          <button data-action="edit-athlete" data-id="${athlete.id}" title="Editar">✏️</button>
          <button class="danger" data-action="delete-athlete" data-id="${athlete.id}" title="Excluir">🗑</button>
        </td>
      </tr>`
    )
    .join("");
  return `
    <table class="data-table">
      <thead><tr><th>Nome</th><th>Equipe</th><th>Naipe</th><th>Categoria</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="pagination-row">
      <button data-action="athletes-prev" ${info.hasPrev ? "" : "disabled"}>← Anterior</button>
      <span class="muted">Página ${info.page} de ${info.pages} · ${state.athletesState.total} atleta(s)</span>
      <button data-action="athletes-next" ${info.hasNext ? "" : "disabled"}>Próxima →</button>
    </div>`;
}


function athletesFiltersHTML() {
  const categories = GestaoLogic.distinctCategories(state.allAthletes);
  return `
    <div class="filters-row">
      <input type="search" data-athlete-filter="q" placeholder="Buscar por nome"
        value="${escapeHtml(state.athletesState.q)}" />
      <select data-athlete-filter="teamId">
        <option value="">Todas as equipes</option>
        ${state.eventData.teams
          .map(
            (team) =>
              `<option value="${team.id}" ${
                team.id === state.athletesState.teamId ? "selected" : ""
              }>${escapeHtml(team.name)}</option>`
          )
          .join("")}
      </select>
      <select data-athlete-filter="naipe">
        <option value="">Todos os naipes</option>
        <option value="F" ${state.athletesState.naipe === "F" ? "selected" : ""}>Feminino</option>
        <option value="M" ${state.athletesState.naipe === "M" ? "selected" : ""}>Masculino</option>
      </select>
      <select data-athlete-filter="category">
        <option value="">Todas as categorias</option>
        ${categories
          .map(
            (category) =>
              `<option value="${escapeHtml(category)}" ${
                category === state.athletesState.category ? "selected" : ""
              }>${escapeHtml(category)}</option>`
          )
          .join("")}
      </select>
      <button data-action="clear-athlete-filters">Limpar</button>
    </div>`;
}


function renderAthletes() {
  if (!state.eventData) return;
  els.athletes.innerHTML = `
    <div class="section-head">
      <h2>Atletas</h2>
      <div class="actions">
        <button class="primary" data-action="new-athlete">+ Novo Atleta</button>
        <button data-action="open-import">📥 Importar planilha</button>
        <button data-action="download-template-csv">Modelo CSV</button>
        <button data-action="download-template-xlsx">Modelo XLSX</button>
        <button data-action="export-athletes">Exportar CSV</button>
      </div>
    </div>
    <p class="muted">Cadastre previamente toda a equipe ou importe uma planilha. Nas raias, os atletas cadastrados podem ser selecionados pelo nome.</p>
    ${state.athleteForm ? athleteFormHTML() : ""}
    ${athleteImportHTML()}
    ${athletesFiltersHTML()}
    <div id="athlete-results">${athleteResultsHTML()}</div>
  `;
  wireAthletes();
}


function wireAthletes() {
  els.athletes
    .querySelectorAll("[data-athlete-filter]")
    .forEach((field) => {
      const name = field.dataset.athleteFilter;
      const apply = () => {
        if (name === "q") {
          clearTimeout(state.athleteSearchTimer);
          state.athleteSearchTimer = setTimeout(() => {
            applyAthleteFilter(name, field.value);
          }, 300);
        } else {
          applyAthleteFilter(name, field.value);
        }
      };
      field.addEventListener(
        field.tagName === "SELECT" ? "change" : "input",
        apply
      );
    });

  const fileInput = document.getElementById("athlete-import-input");
  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) {
        startAthleteImport(fileInput.files[0]);
      }
    });
  }

  const drop = document.getElementById("athlete-import-drop");
  if (drop) {
    drop.addEventListener("dragover", (event) => {
      event.preventDefault();
      drop.classList.add("over");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      drop.classList.remove("over");
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) startAthleteImport(file);
    });
  }

  if (state.athleteForm) {
    const nameInput = document.getElementById("af-name");
    if (nameInput) nameInput.focus();
  }
}


async function applyAthleteFilter(name, value) {
  state.athletesState[name] = value;
  state.athletesState.offset = 0;
  await reloadAthleteResults();
}


async function reloadAthleteResults() {
  try {
    await loadAthletePage();
    const container = document.getElementById("athlete-results");
    if (container) container.innerHTML = athleteResultsHTML();
  } catch (error) {
    showToast(`Erro ao carregar atletas: ${GestaoLogic.gestaoErrorMessage(error)}`, true);
  }
}


async function changeAthletePage(delta) {
  const next = state.athletesState.offset + delta * state.athletesState.limit;
  if (next < 0) return;
  state.athletesState.offset = next;
  await reloadAthleteResults();
}


async function clearAthleteFilters() {
  state.athletesState.q = "";
  state.athletesState.teamId = "";
  state.athletesState.naipe = "";
  state.athletesState.category = "";
  state.athletesState.offset = 0;
  await reloadAthleteResults();
  renderAthletes();
}


async function saveAthleteForm(button) {
  const name = document.getElementById("af-name").value.trim();
  if (!name) {
    setFieldError("athlete-error", "Informe o nome do atleta");
    return;
  }
  setFieldError("athlete-error", "");
  const payload = {
    name,
    naipe: document.getElementById("af-naipe").value,
    category:
      document.getElementById("af-category").value.trim() || null,
    team_id: document.getElementById("af-team").value || null,
  };
  await withButton(button, async () => {
    if (state.athleteForm.mode === "edit") {
      await api("PATCH", `/api/athletes/${state.athleteForm.id}`, payload);
    } else {
      await api("POST", `/api/events/${eventId}/athletes`, payload);
    }
    state.athleteForm = null;
  });
}


async function deleteAthlete(athleteId) {
  const athlete = state.allAthletes.find((item) => item.id === athleteId);
  if (
    !window.confirm(
      `Excluir o atleta "${athlete ? athlete.name : ""}"?`
    )
  ) {
    return;
  }
  try {
    await api("DELETE", `/api/athletes/${athleteId}`);
    await loadAthleteData();
    renderAll();
    showToast("Atleta excluído");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


async function startAthleteImport(file) {
  if (!/\.(csv|xlsx)$/i.test(file.name)) {
    showToast("Formato inválido: use CSV ou XLSX", true);
    return;
  }
  state.athleteImport = {
    fileName: file.name,
    busy: true,
    result: null,
    error: null,
  };
  renderAthletes();

  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch(
      `/api/events/${eventId}/athletes/import`,
      { method: "POST", body }
    );
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      /* resposta sem JSON */
    }
    if (!response.ok) {
      throw new Error(
        payload && payload.detail ? payload.detail : response.statusText
      );
    }
    state.athleteImport = {
      fileName: file.name,
      busy: false,
      result: payload,
      error: null,
    };
    await loadAthleteData();
    renderAll();
    showToast("Importação concluída");
  } catch (error) {
    state.athleteImport = {
      fileName: file.name,
      busy: false,
      result: null,
      error: GestaoLogic.gestaoErrorMessage(error),
    };
    renderAthletes();
    showToast(`Erro na importação: ${GestaoLogic.gestaoErrorMessage(error)}`, true);
  }
}


function downloadAthletes(path) {
  const link = document.createElement("a");
  link.href = path;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export {
  applyAthleteFilter,
  athleteFormHTML,
  athleteImportHTML,
  athleteResultsHTML,
  athletesFiltersHTML,
  changeAthletePage,
  clearAthleteFilters,
  deleteAthlete,
  downloadAthletes,
  fetchAllAthletes,
  loadAthleteData,
  loadAthletePage,
  reloadAthleteResults,
  renderAthletes,
  saveAthleteForm,
  startAthleteImport,
  wireAthletes,
};
