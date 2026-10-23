import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { showToast } from "../common/ui.js";
import { WSClient, wsUrl } from "../common/ws.js";
import {
  changeAthletePage,
  clearAthleteFilters,
  deleteAthlete,
  downloadAthletes,
  loadAthleteData,
  renderAthletes,
  saveAthleteForm,
} from "./atletas.js";
import { deleteHeat, saveAllLanes, saveHeatForm, saveLane } from "./baterias.js";
import {
  createTeam,
  deleteTeam,
  removeTeamLogo,
  renderTeams,
} from "./equipes.js";
import {
  deleteEvent,
  renderOverview,
  renderSettings,
  saveSettings,
} from "./eventos.js";
import { renderAppearance } from "./aparencia.js";
import {
  deleteProva,
  loadClassification,
  renderHeats,
  saveProvaForm,
  scheduleClassificationReload,
  upsertProva,
} from "./provas.js";
import { els, eventId, state } from "./state.js";
import {
  openSection,
  refresh,
  registerRenderer,
  renderAll,
  renderSidebar,
  setDirty,
  setDiscardHandler,
  setLoadEventHandler,
  switchSection,
} from "./ui.js";

async function loadEvent() {
  state.eventData = await api("GET", `/api/events/${eventId}`);
  const resultsLink = document.getElementById("nav-resultados");
  if (resultsLink) {
    resultsLink.href = `resultados.html?event=${encodeURIComponent(eventId)}`;
  }
  const theme = await api("GET", `/api/events/${eventId}/theme`);
  state.theme = window.ThemeLogic.normalizeTheme(theme);
  if (!state.themeForm || !state.themeDirty) {
    state.themeForm = { ...state.theme };
  }
  await loadAthleteData();
  renderAll();
}

setLoadEventHandler(loadEvent);
setDiscardHandler(() => {
  state.themeDirty = false;
  state.themeForm = state.theme ? { ...state.theme } : null;
  renderAppearance();
});
registerRenderer(renderSidebar);
registerRenderer(renderOverview);
registerRenderer(renderHeats);
registerRenderer(renderTeams);
registerRenderer(renderAthletes);
registerRenderer(renderSettings);
registerRenderer(renderAppearance);


els.main.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "new-prova") {
    state.provaForm = { mode: "create" };
    renderHeats();
  } else if (action === "edit-prova") {
    state.provaForm = { mode: "edit", provaId: target.dataset.id };
    state.expandedProvas.add(target.dataset.id);
    renderHeats();
  } else if (action === "cancel-prova-form") {
    state.provaForm = null;
    renderHeats();
  } else if (action === "save-prova-form") {
    saveProvaForm(target);
  } else if (action === "delete-prova") {
    deleteProva(target.dataset.id);
  } else if (action === "toggle-prova") {
    const id = target.dataset.id;
    if (state.expandedProvas.has(id)) state.expandedProvas.delete(id);
    else state.expandedProvas.add(id);
    renderHeats();
  } else if (action === "new-heat") {
    state.heatForm = {
      mode: "create",
      laneCount: 3,
      provaId: target.dataset.prova,
    };
    state.expandedProvas.add(target.dataset.prova);
    renderHeats();
  } else if (action === "edit-heat") {
    const heat = state.eventData.heats.find((item) => item.id === target.dataset.id);
    state.heatForm = {
      mode: "edit",
      heatId: target.dataset.id,
      provaId: heat.prova_id,
      laneCount: Math.max(
        1,
        heat.heat_lanes.reduce((max, lane) => Math.max(max, lane.lane_number), 0)
      ),
    };
    state.expandedProvas.add(heat.prova_id);
    renderHeats();
  } else if (action === "cancel-heat-form") {
    state.heatForm = null;
    renderHeats();
  } else if (action === "save-heat-form") {
    saveHeatForm(target);
  } else if (action === "delete-heat") {
    deleteHeat(target.dataset.id);
  } else if (action === "toggle-heat") {
    const id = target.dataset.id;
    if (state.expanded.has(id)) state.expanded.delete(id);
    else state.expanded.add(id);
    renderHeats();
  } else if (action === "save-lane") {
    saveLane(target.dataset.heat, Number(target.dataset.lane), target);
  } else if (action === "save-all-lanes") {
    saveAllLanes(target.dataset.heat, target);
  } else if (action === "classification") {
    loadClassification(target.dataset.id);
  } else if (action === "refresh-classification") {
    loadClassification(target.dataset.id);
  } else if (action === "open-prova") {
    state.expandedProvas.add(target.dataset.id);
    if (openSection("heats")) renderHeats();
  } else if (action === "open-heat") {
    const heat = state.eventData.heats.find((item) => item.id === target.dataset.id);
    state.expanded.add(target.dataset.id);
    if (heat) state.expandedProvas.add(heat.prova_id);
    if (openSection("heats")) renderHeats();
  } else if (action === "new-team") {
    state.teamsFormOpen = true;
    renderTeams();
  } else if (action === "cancel-team") {
    state.teamsFormOpen = false;
    renderTeams();
  } else if (action === "confirm-team") {
    createTeam(target);
  } else if (action === "delete-team") {
    deleteTeam(target.dataset.id);
  } else if (action === "remove-logo") {
    removeTeamLogo(target.dataset.id);
  } else if (action === "new-athlete") {
    state.athleteForm = { mode: "create" };
    state.athleteImport = null;
    renderAthletes();
  } else if (action === "open-import") {
    state.athleteImport = {
      fileName: "",
      busy: false,
      result: null,
      error: null,
    };
    state.athleteForm = null;
    renderAthletes();
  } else if (action === "edit-athlete") {
    state.athleteForm = { mode: "edit", id: target.dataset.id };
    renderAthletes();
  } else if (action === "cancel-athlete") {
    state.athleteForm = null;
    renderAthletes();
  } else if (action === "confirm-athlete") {
    saveAthleteForm(target);
  } else if (action === "delete-athlete") {
    deleteAthlete(target.dataset.id);
  } else if (action === "athletes-prev") {
    changeAthletePage(-1);
  } else if (action === "athletes-next") {
    changeAthletePage(1);
  } else if (action === "clear-athlete-filters") {
    clearAthleteFilters();
  } else if (action === "download-template-csv") {
    downloadAthletes(
      `/api/events/${eventId}/athletes/import-template?format=csv`
    );
  } else if (action === "download-template-xlsx") {
    downloadAthletes(
      `/api/events/${eventId}/athletes/import-template?format=xlsx`
    );
  } else if (action === "export-athletes") {
    downloadAthletes(`/api/events/${eventId}/athletes/export`);
  } else if (action === "close-import") {
    state.athleteImport = null;
    renderAthletes();
  } else if (action === "save-settings") {
    saveSettings(target);
  } else if (action === "delete-event") {
    deleteEvent();
  }
});


els.main.addEventListener("input", (event) => {
  if (event.target.closest("[data-athlete-filter]")) return;
  if (event.target.closest("[data-theme-upload]")) return;
  setDirty(true);
});


els.eventName.addEventListener("input", () => setDirty(true));


els.eventName.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.eventName.blur();
});


els.eventName.addEventListener("change", async () => {
  const name = els.eventName.value.trim();
  if (!name || name === state.eventData.name) {
    els.eventName.value = state.eventData.name;
    return;
  }
  try {
    await api("PATCH", `/api/events/${eventId}`, { name });
    await refresh();
    showToast("Nome atualizado");
  } catch (error) {
    els.eventName.value = state.eventData.name;
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
});


document.querySelectorAll(".sidebar-nav button").forEach((button) => {
  button.addEventListener("click", () => switchSection(button.dataset.section));
});


els.hamburger.addEventListener("click", () => {
  els.sidebar.classList.toggle("open");
});


window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});


const ws = new WSClient(wsUrl(), (message) => {
  if (!state.eventData) return;
  if (message.type === "heat_state") {
    const index = state.eventData.heats.findIndex(
      (heat) => heat.id === message.payload.id
    );
    if (index >= 0) state.eventData.heats[index] = message.payload;
    else state.eventData.heats.push(message.payload);
    scheduleClassificationReload(message.payload.prova_id);
    if (state.activeSection === "overview" && !state.dirty) renderOverview();
    renderSidebar();
  } else if (message.type === "prova_state") {
    upsertProva(message.payload);
    scheduleClassificationReload(message.payload.id);
    if (state.activeSection === "overview" && !state.dirty) renderOverview();
    if (
      state.activeSection === "heats" &&
      !state.dirty &&
      !state.heatForm &&
      !state.provaForm
    ) {
      renderHeats();
    }
  } else if (message.type === "theme_updated") {
    if (message.event_id && message.event_id !== eventId) return;
    state.theme = window.ThemeLogic.normalizeTheme(message.payload);
    if (!state.themeDirty) {
      state.themeForm = { ...state.theme };
      if (state.activeSection === "settings") renderAppearance();
    }
  } else if (message.type === "error") {
    showToast(message.message || "Erro na operação", true);
  } else if (message.type === "athletes_changed") {
    if (message.payload && message.payload.event_id === eventId) {
      clearTimeout(state.athleteRefreshTimer);
      state.athleteRefreshTimer = setTimeout(() => {
        loadEvent().catch((error) =>
          showToast(`Erro ao atualizar atletas: ${GestaoLogic.gestaoErrorMessage(error)}`, true)
        );
      }, 300);
    }
  }
});


ws.onStatusChange = (connected) => {
  if (connected && state.eventData) {
    loadEvent().catch((error) =>
      showToast(
        `Erro ao atualizar evento: ${GestaoLogic.gestaoErrorMessage(error)}`,
        true
      )
    );
  }
};


loadEvent().catch((error) => {
  els.overview.innerHTML = `
    <div class="panel">
      <p class="muted">Erro ao carregar evento: ${escapeHtml(GestaoLogic.gestaoErrorMessage(error))}</p>
      <a href="index.html">← Voltar para Home</a>
    </div>`;
});


ws.subscribe(eventId);
ws.connect();
