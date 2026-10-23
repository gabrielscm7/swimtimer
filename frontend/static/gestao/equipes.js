import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { pluralize, showToast } from "../common/ui.js";
import { MAX_LOGO_BYTES, els, eventId, state } from "./state.js";
import { refresh, setFieldError, teamLogoHTML, withButton } from "./ui.js";


function teamLaneCount(teamId) {
  return state.eventData.heats.reduce(
    (sum, heat) =>
      sum + heat.heat_lanes.filter((lane) => lane.team_id === teamId).length,
    0
  );
}


function renderTeams() {
  if (!state.eventData) return;
  let html = `
    <div class="section-head">
      <h2>Equipes</h2>
      <button class="primary" data-action="new-team">+ Nova Equipe</button>
    </div>`;
  if (state.teamsFormOpen) {
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
  if (!state.eventData.teams.length) {
    html += `
      <div class="empty-state">
        <p>Nenhuma equipe cadastrada.</p>
        <p class="muted">Crie as equipes antes de configurar as raias.</p>
      </div>`;
  } else {
    html += '<div class="list">';
    for (const team of state.eventData.teams) {
      const registered = team.athlete_count || 0;
      const inLanes = teamLaneCount(team.id);
      const blockDelete = registered + inLanes > 0;
      html += `
        <div class="list-item team-item">
          ${teamLogoHTML(team.logo_url, team.name, "medium")}
          <input type="text" data-team-name="${team.id}" value="${escapeHtml(team.name)}" style="max-width: 280px" />
          <span class="muted">${pluralize(registered, "atleta")}${
            inLanes ? ` · ${pluralize(inLanes, "em raia", "em raias")}` : ""
          }</span>
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
            ${blockDelete ? 'disabled title="Equipe com atletas ou raias vinculadas"' : ""}>🗑</button>
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
  if (state.teamsFormOpen) {
    const nameInput = document.getElementById("team-name-input");
    if (nameInput) nameInput.focus();
  }
}


async function commitTeamRename(input) {
  const team = state.eventData.teams.find((item) => item.id === input.dataset.teamName);
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
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
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
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}


async function removeTeamLogo(teamId) {
  try {
    await api("DELETE", `/api/teams/${teamId}/logo`);
    await refresh();
    showToast("Logo removido");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
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
    state.teamsFormOpen = false;
  });
}


async function deleteTeam(teamId) {
  const team = state.eventData.teams.find((item) => item.id === teamId);
  if (!window.confirm(`Excluir a equipe "${team ? team.name : ""}"?`)) return;
  try {
    await api("DELETE", `/api/teams/${teamId}`);
    await refresh();
    showToast("Equipe excluída");
  } catch (error) {
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

export {
  commitTeamRename,
  createTeam,
  deleteTeam,
  removeTeamLogo,
  renderTeams,
  teamLaneCount,
  uploadTeamLogo,
};
