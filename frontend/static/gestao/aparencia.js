import { api } from "../common/api.js";
import { escapeHtml } from "../common/format.js";
import { showFeedback, showToast } from "../common/ui.js";
import { els, eventId, state } from "./state.js";
import { setDirty, setFieldError, withButton } from "./ui.js";

const { DEFAULT_THEME, PRESETS, normalizeTheme, contrastReport } =
  window.ThemeLogic;

const COLOR_FIELDS = [
  ["bg", "Fundo"],
  ["bg2", "Fundo 2"],
  ["panel", "Painel"],
  ["text", "Texto"],
  ["muted", "Texto suave"],
  ["accent", "Destaque"],
  ["accent_strong", "Destaque forte"],
  ["lvl_prova", "Nível prova"],
  ["lvl_bateria", "Nível bateria"],
];

const POSITIONS = [
  ["center", "Centro"],
  ["top", "Topo"],
  ["bottom", "Base"],
  ["left", "Esquerda"],
  ["right", "Direita"],
  ["top left", "Topo esquerda"],
  ["top right", "Topo direita"],
  ["bottom left", "Base esquerda"],
  ["bottom right", "Base direita"],
];

let previewTimer = null;

function currentTheme() {
  return normalizeTheme(state.themeForm || state.theme || DEFAULT_THEME);
}

function previewImage(kind, theme) {
  const url = kind === "background" ? theme.bg_image_url : theme.logo_url;
  const opacity = kind === "background" ? theme.bg_opacity : 1;
  return `<img data-theme-preview="${kind}" src="${escapeHtml(
    url || ""
  )}" alt="" style="opacity:${opacity}" ${url ? "" : "hidden"} />${
    url ? "" : '<span class="muted">Sem imagem</span>'
  }`;
}

function renderAppearance() {
  const container = document.getElementById("appearance-panel");
  if (!container || !state.eventData) return;
  if (!state.themeForm) {
    state.themeForm = { ...(state.theme || DEFAULT_THEME) };
  }
  const theme = currentTheme();

  const colors = COLOR_FIELDS.map(
    ([key, label]) => `
      <label class="theme-color-field">
        <span>${label}</span>
        <input type="color" data-theme-color="${key}" value="${theme[key]}" />
      </label>`
  ).join("");

  const positionOptions = POSITIONS.map(
    ([value, label]) =>
      `<option value="${value}" ${theme.bg_position === value ? "selected" : ""}>${label}</option>`
  ).join("");

  container.innerHTML = `
    <h2>Aparência do público</h2>
    <div class="appearance-grid">
      <div class="appearance-controls">
        <div class="theme-colors">${colors}</div>

        <div class="theme-sliders">
          <label>
            Opacidade do fundo
            <span class="theme-value" data-theme-value="bg_opacity">${theme.bg_opacity.toFixed(2)}</span>
            <input type="range" data-theme-field="bg_opacity" min="0" max="1" step="0.05" value="${theme.bg_opacity}" />
          </label>
          <label>
            Escala da fonte
            <span class="theme-value" data-theme-value="font_scale">${theme.font_scale.toFixed(2)}</span>
            <input type="range" data-theme-field="font_scale" min="0.8" max="1.4" step="0.05" value="${theme.font_scale}" />
          </label>
        </div>

        <div class="grid">
          <div>
            <label>Encaixe da imagem de fundo</label>
            <select data-theme-field="bg_fit">
              <option value="cover" ${theme.bg_fit === "cover" ? "selected" : ""}>Cobrir (cover)</option>
              <option value="contain" ${theme.bg_fit === "contain" ? "selected" : ""}>Conter (contain)</option>
              <option value="center" ${theme.bg_fit === "center" ? "selected" : ""}>Tamanho original (center)</option>
            </select>
          </div>
          <div>
            <label>Posição da imagem de fundo</label>
            <select data-theme-field="bg_position">${positionOptions}</select>
          </div>
          <div>
            <label>Título no público</label>
            <input type="text" maxlength="200" data-theme-field="title_override"
              placeholder="${escapeHtml(state.eventData.name)}"
              value="${escapeHtml(theme.title_override || "")}" />
          </div>
          <div>
            <label>Rodapé</label>
            <input type="text" maxlength="300" data-theme-field="footer_text"
              value="${escapeHtml(theme.footer_text || "")}" />
          </div>
        </div>

        <label class="checkbox-row">
          <input type="checkbox" data-theme-field="show_team_logos" ${theme.show_team_logos ? "checked" : ""} />
          Exibir logos das equipes
        </label>

        <div class="theme-uploads">
          <div class="theme-upload">
            <label>Imagem de fundo</label>
            <div class="theme-checker theme-image-preview">${previewImage("background", theme)}</div>
            <div class="row">
              <label class="file-btn">
                Escolher imagem
                <input type="file" data-theme-upload="background"
                  accept="image/png,image/jpeg,image/webp" hidden />
              </label>
              <button data-action="remove-theme-image" data-kind="background"
                ${theme.bg_image_url ? "" : "disabled"}>Remover</button>
            </div>
            <p class="muted">PNG com transparência é preservado. Até 2 MB e 3840 px.</p>
          </div>
          <div class="theme-upload">
            <label>Logo do evento</label>
            <div class="theme-checker theme-image-preview logo">${previewImage("logo", theme)}</div>
            <div class="row">
              <label class="file-btn">
                Escolher logo
                <input type="file" data-theme-upload="logo"
                  accept="image/png,image/jpeg,image/webp" hidden />
              </label>
              <button data-action="remove-theme-image" data-kind="logo"
                ${theme.logo_url ? "" : "disabled"}>Remover</button>
            </div>
          </div>
        </div>

        <div class="theme-contrast" id="theme-contrast"></div>

        <div class="row theme-buttons">
          <button class="primary" id="theme-save" data-action="save-theme">Salvar aparência</button>
          <button data-action="reset-theme">Restaurar padrão</button>
        </div>
        <div class="row theme-presets">
          <button data-action="apply-preset" data-preset="padrao_azul">Padrão azul</button>
          <button data-action="apply-preset" data-preset="claro_alto_contraste">Claro / alto contraste</button>
          <button data-action="apply-preset" data-preset="escuro_neutro">Escuro neutro</button>
        </div>
        <div class="field-error" id="theme-error" hidden></div>
      </div>

      <div class="appearance-preview">
        <label>Prévia ao vivo</label>
        <iframe id="theme-preview-frame"
          src="publico.html?event=${encodeURIComponent(eventId)}&preview=1"
          title="Prévia do público"></iframe>
      </div>
    </div>`;

  updateContrast();
  watchPreviewLoad();
}

function updateContrast() {
  const report = contrastReport(currentTheme());
  const box = document.getElementById("theme-contrast");
  const save = document.getElementById("theme-save");
  if (save) save.disabled = report.blocked;
  setFieldError(
    "theme-error",
    report.blocked
      ? "Contraste abaixo de 3:1 em texto, destaque, níveis ou texto suave. Ajuste as cores para salvar."
      : ""
  );
  if (!box) return;
  const values = `texto ${report.textMin.toFixed(
    2
  )}:1 · níveis ${report.levelMin.toFixed(
    2
  )}:1 · menor contraste ${report.min.toFixed(2)}:1`;
  box.classList.toggle("blocked", report.blocked);
  box.classList.toggle("warning", !report.blocked && report.warning);
  if (report.blocked) {
    box.textContent = `Contraste insuficiente — ${values}. Salvamento bloqueado (mínimo 3:1).`;
  } else if (report.warning) {
    box.textContent = `Atenção: contraste de texto abaixo de 4,5:1 — ${values}.`;
  } else {
    box.textContent = `Contraste adequado — ${values}.`;
  }
}

function updatePreviewImage(kind, theme) {
  const image = document.querySelector(`[data-theme-preview="${kind}"]`);
  if (!image) return;
  if (kind === "background") image.style.opacity = theme.bg_opacity;
}

function postPreviewNow() {
  const frame = document.getElementById("theme-preview-frame");
  if (!frame || !frame.contentWindow) return;
  frame.contentWindow.postMessage(
    { type: "theme_preview", theme: currentTheme() },
    window.location.origin
  );
}

function schedulePreview() {
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(postPreviewNow, 80);
}

function watchPreviewLoad() {
  const frame = document.getElementById("theme-preview-frame");
  if (!frame) return;
  frame.addEventListener("load", postPreviewNow, { once: true });
  postPreviewNow();
}

function applyField(target) {
  if (!state.themeForm) state.themeForm = currentTheme();
  if (target.dataset.themeColor) {
    state.themeForm[target.dataset.themeColor] = target.value;
  } else if (target.dataset.themeField) {
    const key = target.dataset.themeField;
    let value = target.value;
    if (target.type === "checkbox") value = target.checked;
    else if (target.type === "range") value = Number(value);
    state.themeForm[key] = value;
    const label = document.querySelector(`[data-theme-value="${key}"]`);
    if (label) label.textContent = Number(value).toFixed(2);
  } else {
    return false;
  }
  const theme = currentTheme();
  updatePreviewImage("background", theme);
  updateContrast();
  schedulePreview();
  state.themeDirty = true;
  setDirty(true);
  return true;
}

function parseError(response) {
  return response
    .json()
    .then((body) => new Error(body.detail || response.statusText))
    .catch(() => new Error(response.statusText));
}

async function uploadThemeImage(kind, file) {
  if (!state.themeForm) state.themeForm = currentTheme();
  const field = kind === "background" ? "bg_image_url" : "logo_url";
  const previous = state.themeForm[field];
  const objectUrl = URL.createObjectURL(file);
  const image = document.querySelector(`[data-theme-preview="${kind}"]`);
  if (image) {
    image.src = objectUrl;
    image.hidden = false;
    const placeholder = image.parentElement.querySelector(".muted");
    if (placeholder) placeholder.remove();
  }

  const data = new FormData();
  data.append("file", file);
  try {
    const response = await fetch(
      `/api/events/${eventId}/theme/image?kind=${kind}`,
      { method: "POST", body: data }
    );
    if (!response.ok) throw await parseError(response);
    const saved = await response.json();
    state.theme = saved;
    state.themeForm = { ...currentTheme(), [field]: saved[field] };
    renderAppearance();
    showToast("Imagem atualizada");
  } catch (error) {
    state.themeForm[field] = previous;
    renderAppearance();
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function saveTheme(button) {
  const theme = currentTheme();
  if (contrastReport(theme).blocked) {
    showToast("Contraste abaixo de 3:1: ajuste as cores antes de salvar.", true);
    return;
  }
  await withButton(button, async () => {
    const saved = await api("PUT", `/api/events/${eventId}/theme`, theme);
    state.theme = saved;
    state.themeForm = { ...saved };
    state.themeDirty = false;
    setDirty(false);
  });
}

async function resetTheme(button) {
  if (!window.confirm("Restaurar o tema padrão do público?")) return;
  await withButton(button, async () => {
    const saved = await api("PUT", `/api/events/${eventId}/theme`, {
      ...DEFAULT_THEME,
    });
    state.theme = saved;
    state.themeForm = { ...saved };
    state.themeDirty = false;
    setDirty(false);
  });
}

function applyPreset(button) {
  const preset = PRESETS[button.dataset.preset];
  if (!preset) return;
  const current = currentTheme();
  state.themeForm = normalizeTheme({
    ...preset,
    bg_image_url: current.bg_image_url,
    logo_url: current.logo_url,
    bg_opacity: current.bg_opacity,
    bg_fit: current.bg_fit,
    bg_position: current.bg_position,
    title_override: current.title_override,
    footer_text: current.footer_text,
    show_team_logos: current.show_team_logos,
    font_scale: current.font_scale,
  });
  renderAppearance();
  state.themeDirty = true;
  setDirty(true);
}

async function removeThemeImage(button) {
  const kind = button.dataset.kind;
  const field = kind === "background" ? "bg_image_url" : "logo_url";
  const current = currentTheme();
  showFeedback(button, "loading");
  try {
    const saved = await api(
      "DELETE",
      `/api/events/${eventId}/theme/image?kind=${kind}`
    );
    state.theme = saved;
    state.themeForm = { ...current, [field]: null };
    renderAppearance();
    showToast("Imagem removida");
  } catch (error) {
    showFeedback(button, "error");
    showToast(GestaoLogic.gestaoErrorMessage(error), true);
  }
}

els.main.addEventListener("input", (event) => {
  applyField(event.target);
});

els.main.addEventListener("change", (event) => {
  const upload = event.target.closest("[data-theme-upload]");
  if (upload) {
    const file = upload.files && upload.files[0];
    if (file) uploadThemeImage(upload.dataset.themeUpload, file);
    return;
  }
  if (event.target.matches("select, input[type=checkbox]")) {
    applyField(event.target);
  }
});

els.main.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  if (target.dataset.action === "save-theme") saveTheme(target);
  else if (target.dataset.action === "reset-theme") resetTheme(target);
  else if (target.dataset.action === "apply-preset") applyPreset(target);
  else if (target.dataset.action === "remove-theme-image") {
    removeThemeImage(target);
  }
});

export { renderAppearance };
