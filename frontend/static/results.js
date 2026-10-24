import { api } from "./common/api.js";
import { escapeHtml } from "./common/format.js";
import { renderHeatResult, renderProvaResult } from "./common/result_views.js";
import { showToast, statusLabel } from "./common/ui.js";
import { WSClient, wsUrl } from "./common/ws.js";

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");
if (!eventId) window.location.replace("index.html");

const els = {
  name: document.getElementById("res-event-name"),
  meta: document.getElementById("res-event-meta"),
  status: document.getElementById("res-event-status"),
  message: document.getElementById("res-status"),
  provas: document.getElementById("res-provas"),
  detail: document.getElementById("res-detail"),
  presentation: document.getElementById("res-presentation"),
  publicLink: document.getElementById("res-public-link"),
  exportLink: document.getElementById("res-export-link"),
  audit: document.getElementById("res-audit"),
  tvFrame: document.getElementById("res-tv-frame"),
  tvPreview: document.getElementById("res-tv-preview"),
  sendTv: document.getElementById("res-send-tv"),
  sendTvHint: document.getElementById("res-send-tv-hint"),
};

let tree = null;
let presentation = null;
let draft = null;
let selectedProvaId = null;
let selectedHeatId = null;
let dirty = false;
let refreshTimer = null;
const summaryCache = new Map();

const SNAPSHOT_LABELS = {
  official: "Oficial",
  provisional: "Provisório",
  corrected: "Retificado",
};

function refOf(slide) {
  return `${slide.kind}:${slide.target_id}`;
}

function findProva(provaId) {
  if (!tree) return null;
  return tree.provas.find((prova) => prova.id === provaId) || null;
}

function findHeat(heatId) {
  if (!tree) return null;
  for (const prova of tree.provas) {
    const heat = prova.heats.find((item) => item.id === heatId);
    if (heat) return { prova, heat };
  }
  return null;
}

function slideInfo(kind, targetId) {
  if (kind === "prova") {
    const prova = findProva(targetId);
    if (!prova) return null;
    return {
      label: Labels.provaLabel(prova),
      status: prova.status,
      eligible: prova.status === "finished",
    };
  }
  const found = findHeat(targetId);
  if (!found) return null;
  const { prova, heat } = found;
  return {
    label: `${Labels.bateriaLabel(heat, {
      index: heat.heat_index_in_prova,
      total: heat.heats_in_prova,
      provaOrder: prova.order_num,
      includeProva: true,
    })}`,
    status: heat.status,
    eligible: heat.status === "finished",
  };
}

function snapshotBadge(snapshot) {
  if (!snapshot) {
    return '<span class="res-badge">Sem revisão</span>';
  }
  const status = snapshot.status || "provisional";
  return `<span class="res-badge ${escapeHtml(status)}">${escapeHtml(
    SNAPSHOT_LABELS[status] || status
  )} · rev. ${escapeHtml(String(snapshot.revision ?? "—"))}</span>`;
}

function provaBadge(heats) {
  const statuses = heats
    .map((heat) => heat.result_snapshot && heat.result_snapshot.status)
    .filter(Boolean);
  if (!statuses.length) return '<span class="res-badge">Sem revisão</span>';
  if (statuses.every((status) => status === "official")) {
    return '<span class="res-badge official">Oficial</span>';
  }
  if (statuses.some((status) => status === "corrected")) {
    return '<span class="res-badge corrected">Retificado</span>';
  }
  return '<span class="res-badge provisional">Provisório</span>';
}

function classificationHTML(summary) {
  const data = summary.classification || {};
  const help = Labels.classificationHelp(true, summary.heat_count);
  const sections = renderProvaResult(summary, data, { variant: "table" });
  return `
    <div class="level-title prova"><span class="level-chip prova"><span class="level-icon">◆</span>PROVA</span> Resultado da PROVA</div>
    <p class="res-legend">${escapeHtml(help)}</p>
    ${sections || '<p class="res-empty">Nenhum resultado válido ainda.</p>'}
    <p class="res-legend">${
      data.is_provisional
        ? "Classificação provisória: há baterias pendentes ou em andamento."
        : "Classificação definitiva: todas as baterias foram finalizadas."
    }</p>`;
}

function batteryCard(heat, details, forceOpen) {
  const snapshot = details ? details.result_snapshot : heat.result_snapshot;
  const open = forceOpen ? "open" : "";
  const lanes = details && details.heat_lanes ? details.heat_lanes : [];
  const participants = lanes.filter(
    (lane) => lane.participant_name || lane.athlete_id || lane.team_id
  );
  const finished = participants.filter(
    (lane) => lane.status === "finished" || lane.status === "dq"
  ).length;
  return `
    <details class="res-heat level-card bateria" data-heat="${heat.id}" ${open}>
      <summary>
        <span class="level-chip bateria"><span class="level-icon">▸</span>BATERIA</span>
        <span>${escapeHtml(
          Labels.bateriaLabel(heat, {
            index: heat.heat_index_in_prova,
            total: heat.heats_in_prova,
          })
        )}</span>
        <span class="res-badge">${escapeHtml(statusLabel(heat.status))}</span>
        ${snapshotBadge(snapshot)}
        <span class="muted">${finished}/${participants.length} finalizadas</span>
      </summary>
      <div style="margin-top:10px">${
        renderHeatResult(details || heat, { variant: "table" }) ||
        '<p class="res-empty">Sem participantes nesta bateria.</p>'
      }</div>
      <div class="res-actions">
        <button class="res-btn" data-action="add-bateria" data-id="${heat.id}">Adicionar ao telão</button>
        <button class="res-btn" data-action="pin-ref" data-kind="bateria" data-id="${heat.id}">Fixar agora</button>
        <button class="res-btn" data-action="history" data-id="${heat.id}">Histórico de revisões</button>
        <a class="res-btn" href="sumula.html?heat=${encodeURIComponent(heat.id)}" target="_blank" rel="noopener">Súmula ↗</a>
      </div>
      <div class="res-snap" data-history="${heat.id}"></div>
    </details>`;
}

function renderDetail(cache) {
  const { summary, heatDetails } = cache;
  const heats = summary.heats || [];
  const meta = [
    summary.naipe === "MISTO" ? "Misto" : summary.naipe || "",
    summary.category || "",
    summary.distance_m ? `${summary.distance_m}m` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  els.detail.innerHTML = `
    <article class="res-card level-card prova">
      <div class="res-card-head">
        <span class="level-chip prova"><span class="level-icon">◆</span>PROVA</span>
        <h2>${escapeHtml(Labels.provaLabel(summary))}</h2>
        <span class="res-badge">${escapeHtml(statusLabel(summary.status))}</span>
        ${provaBadge(heats)}
      </div>
      <div class="res-meta">${escapeHtml(meta || "—")} · ${summary.heats_finished} de ${summary.heat_count} baterias finalizadas</div>
      <div class="res-actions">
        <button class="res-btn" data-action="add-prova" data-id="${summary.id}">Adicionar prova ao telão</button>
        <button class="res-btn" data-action="pin-ref" data-kind="prova" data-id="${summary.id}">Fixar prova agora</button>
      </div>
    </article>
    <article class="res-card level-card prova">${classificationHTML(summary)}</article>
    <article class="res-card level-card bateria">
      <div class="res-card-head">
        <span class="level-chip bateria"><span class="level-icon">▸</span>BATERIA</span>
        <h2>Resultados por BATERIA</h2>
      </div>
      ${
        heats.length
          ? heats
              .map((heat) =>
                batteryCard(
                  heat,
                  heatDetails.get(heat.id),
                  selectedHeatId === heat.id
                )
              )
              .join("")
          : '<p class="res-empty">Nenhuma bateria cadastrada.</p>'
      }
    </article>`;
}

function renderSidebar() {
  if (!tree) return;
  if (!tree.provas.length) {
    els.provas.innerHTML = '<p class="res-empty">Nenhuma prova cadastrada.</p>';
    return;
  }
  els.provas.innerHTML = tree.provas
    .map(
      (prova) => `
      <button class="res-prova-btn ${prova.id === selectedProvaId ? "active" : ""}"
        data-prova="${prova.id}">
        ${escapeHtml(Labels.provaLabel(prova))}
        <small>${escapeHtml(statusLabel(prova.status))} · ${prova.heats_finished}/${prova.heat_count} baterias</small>
      </button>`
    )
    .join("");
}

function draftFromPresentation(config) {
  return {
    enabled: Boolean(config.enabled),
    rotation: Boolean(config.rotation),
    slide_duration_s: Number(config.slide_duration_s) || 15,
    show_next_prova: Boolean(config.show_next_prova),
    pinned_ref: config.pinned_ref || null,
    slides: (config.slides || []).map((slide) => ({
      kind: slide.kind,
      target_id: slide.target_id,
    })),
  };
}

function markDirty() {
  dirty = true;
}

function slideRow(slide, index) {
  const info = slideInfo(slide.kind, slide.target_id);
  const ref = refOf(slide);
  const pinned = draft.pinned_ref === ref;
  const label = info
    ? info.label
    : `Item removido (${slide.kind})`;
  const status = info ? statusLabel(info.status) : "indisponível";
  const eligible = info && info.eligible;
  return `
    <div class="res-slide ${pinned ? "pinned" : ""}">
      <div class="res-slide-title">${escapeHtml(label)}</div>
      <div class="res-slide-actions">
        <span class="res-badge ${eligible ? "" : "provisional"}">${escapeHtml(
          eligible ? "pronto" : status
        )}</span>
        <button class="res-btn" data-pres-action="up" data-index="${index}" ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="res-btn" data-pres-action="down" data-index="${index}" ${index === draft.slides.length - 1 ? "disabled" : ""}>↓</button>
        <button class="res-btn" data-pres-action="pin" data-index="${index}">${pinned ? "Desafixar" : "Fixar"}</button>
        <button class="res-btn danger" data-pres-action="remove" data-index="${index}">✕</button>
      </div>
    </div>`;
}

function renderPresentation() {
  if (!draft) return;
  els.presentation.innerHTML = `
    <label class="res-form-row"><input type="checkbox" data-pres="enabled" ${draft.enabled ? "checked" : ""}/> Ativar curadoria no telão</label>
    <label class="res-form-row"><input type="checkbox" data-pres="rotation" ${draft.rotation ? "checked" : ""}/> Rotação automática</label>
    <label class="res-form-row"><input type="checkbox" data-pres="show_next_prova" ${draft.show_next_prova ? "checked" : ""}/> Mostrar próxima prova no rodapé</label>
    <label class="res-form-row">Duração do slide
      <input type="number" data-pres="slide_duration_s" min="5" max="60" value="${draft.slide_duration_s}" /> s
    </label>
    <div class="res-section-title">Slides</div>
    <div id="res-slides">
      ${draft.slides.length ? draft.slides.map(slideRow).join("") : '<p class="res-empty">Nenhum resultado na apresentação.</p>'}
    </div>
    <div class="res-actions">
      <button class="res-btn primary" data-pres-action="save">Salvar apresentação</button>
    </div>
    <p class="res-legend">A prova ao vivo sempre tem prioridade. Slides sem resultado ficam aguardando a finalização.</p>`;
}

async function loadPresentation() {
  presentation = await api("GET", `/api/events/${eventId}/presentation`);
  draft = draftFromPresentation(presentation);
  dirty = false;
  renderPresentation();
}

async function loadTree() {
  tree = await api("GET", `/api/events/${eventId}/results`);
  els.name.textContent = tree.event.name;
  els.meta.textContent = [
    tree.event.date,
    tree.event.location,
    `Piscina ${tree.event.pool_length_m}m`,
  ]
    .filter(Boolean)
    .join(" · ");
  els.status.textContent = `Status do evento: ${statusLabel(tree.event.status)}`;
  els.publicLink.href = `publico.html?event=${encodeURIComponent(eventId)}`;
  els.exportLink.href = `/api/events/${encodedId()}/export/results.csv`;
  renderSidebar();
}

function encodedId() {
  return encodeURIComponent(eventId);
}

async function loadSummary(provaId) {
  if (summaryCache.has(provaId)) return summaryCache.get(provaId);
  const summary = await api("GET", `/api/provas/${provaId}/summary`);
  const heatDetails = new Map();
  await Promise.all(
    (summary.heats || []).map(async (heat) => {
      try {
        heatDetails.set(
          heat.id,
          await api("GET", `/api/heats/${heat.id}`)
        );
      } catch (error) {
        /* mantém o resumo da bateria */
      }
    })
  );
  const cache = { summary, heatDetails };
  summaryCache.set(provaId, cache);
  return cache;
}

function updateUrl() {
  const url = new URL(window.location.href);
  if (selectedProvaId) url.searchParams.set("prova", selectedProvaId);
  else url.searchParams.delete("prova");
  if (selectedHeatId) url.searchParams.set("heat", selectedHeatId);
  else url.searchParams.delete("heat");
  window.history.replaceState(null, "", url);
}

async function selectProva(provaId, heatId = null, update = true) {
  const prova = findProva(provaId);
  if (!prova) return;
  selectedProvaId = provaId;
  selectedHeatId = heatId;
  renderSidebar();
  updateSendHint();
  if (update) updateUrl();
  els.detail.innerHTML = '<div class="res-message">Carregando prova…</div>';
  try {
    const cache = await loadSummary(provaId);
    renderDetail(cache);
    if (heatId) {
      const target = els.detail.querySelector(`details[data-heat="${heatId}"]`);
      if (target) {
        target.open = true;
        target.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  } catch (error) {
    els.detail.innerHTML = `<div class="res-message">Erro ao carregar prova: ${escapeHtml(error.message)}</div>`;
  }
}

function addSlide(kind, targetId, pin = false) {
  if (!draft) return;
  const ref = `${kind}:${targetId}`;
  if (!draft.slides.some((slide) => refOf(slide) === ref)) {
    draft.slides.push({ kind, target_id: targetId });
  }
  if (pin) draft.pinned_ref = ref;
  markDirty();
  renderPresentation();
  showToast("Slide adicionado; lembre de salvar.");
}

async function savePresentation() {
  if (!draft) return;
  try {
    presentation = await api(
      "PUT",
      `/api/events/${encodedId()}/presentation`,
      draft
    );
    draft = draftFromPresentation(presentation);
    dirty = false;
    renderPresentation();
    showToast("Apresentação salva");
  } catch (error) {
    showToast(`Erro ao salvar: ${error.message}`, true);
  }
}

function setupPreview() {
  if (!els.tvPreview || !els.tvFrame) return;
  els.tvPreview.src = `publico.html?event=${encodedId()}&preview=1`;
  const resize = () => {
    const width = els.tvFrame.clientWidth;
    if (!width) return;
    els.tvPreview.style.transform = `scale(${width / 1920})`;
  };
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(resize).observe(els.tvFrame);
  }
  window.addEventListener("resize", resize);
  resize();
}

function updateSendHint() {
  if (!els.sendTvHint) return;
  if (selectedHeatId) {
    const found = findHeat(selectedHeatId);
    els.sendTvHint.textContent = found
      ? `Slide: ${Labels.bateriaLabel(found.heat, {
          index: found.heat.heat_index_in_prova,
          total: found.heat.heats_in_prova,
          provaOrder: found.prova.order_num,
          includeProva: true,
        })}`
      : "Selecione uma prova ou bateria.";
    return;
  }
  if (selectedProvaId) {
    const prova = findProva(selectedProvaId);
    els.sendTvHint.textContent = prova
      ? `Slide: ${Labels.provaLabel(prova)}`
      : "Selecione uma prova ou bateria.";
    return;
  }
  els.sendTvHint.textContent = "Selecione uma prova ou bateria.";
}

async function sendToScreenNow() {
  const kind = selectedHeatId ? "bateria" : "prova";
  const targetId = selectedHeatId || selectedProvaId;
  if (!targetId) {
    showToast("Selecione uma prova ou bateria.", true);
    return;
  }
  try {
    if (!draft) await loadPresentation();
    if (!draft) return;
    const ref = `${kind}:${targetId}`;
    if (!draft.slides.some((slide) => refOf(slide) === ref)) {
      draft.slides.push({ kind, target_id: targetId });
    }
    draft.enabled = true;
    draft.pinned_ref = ref;
    presentation = await api(
      "PUT",
      `/api/events/${encodedId()}/presentation`,
      draft
    );
    draft = draftFromPresentation(presentation);
    dirty = false;
    renderPresentation();
    updateSendHint();
    showToast("Enviado ao telão agora");
  } catch (error) {
    showToast(`Erro ao enviar ao telão: ${error.message}`, true);
  }
}

async function showHistory(heatId, container) {
  if (!container) return;
  container.textContent = "Carregando…";
  try {
    const rows = await api("GET", `/api/heats/${heatId}/snapshots`);
    if (!rows.length) {
      container.textContent = "Nenhuma revisão registrada.";
      return;
    }
    container.innerHTML = rows
      .map(
        (row) => `<div>rev. ${row.revision} · ${escapeHtml(
          SNAPSHOT_LABELS[row.status] || row.status
        )} · ${escapeHtml(row.reason || "")} · ${escapeHtml(
          new Date((row.created_at || 0) * 1000).toLocaleString("pt-BR")
        )} · ${escapeHtml(row.created_by || "")}</div>`
      )
      .join("");
  } catch (error) {
    container.textContent = `Erro ao carregar histórico: ${error.message}`;
  }
}

function debounceRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 350);
}

async function refresh() {
  try {
    await loadTree();
    if (!dirty) await loadPresentation();
    summaryCache.clear();
    if (selectedProvaId) {
      await selectProva(selectedProvaId, selectedHeatId, false);
    }
  } catch (error) {
    showToast(`Erro ao atualizar: ${error.message}`, true);
  }
}

// --------------------------------------------------------------------------- //
// Eventos de UI
// --------------------------------------------------------------------------- //
els.provas.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prova]");
  if (!button) return;
  selectProva(button.dataset.prova);
});

els.detail.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  if (action === "add-prova") addSlide("prova", id);
  else if (action === "add-bateria") addSlide("bateria", id);
  else if (action === "pin-ref") {
    addSlide(target.dataset.kind, id, true);
  } else if (action === "history") {
    showHistory(id, els.detail.querySelector(`[data-history="${id}"]`));
  }
});

els.detail.addEventListener("toggle", (event) => {
  const details = event.target.closest("details[data-heat]");
  if (!details) return;
  selectedHeatId = details.open ? details.dataset.heat : null;
  updateSendHint();
  updateUrl();
}, true);

if (els.sendTv) {
  els.sendTv.addEventListener("click", sendToScreenNow);
}

els.presentation.addEventListener("change", (event) => {
  const field = event.target.dataset.pres;
  if (!field || !draft) return;
  if (event.target.type === "checkbox") {
    draft[field] = event.target.checked;
  } else if (field === "slide_duration_s") {
    draft[field] = Number(event.target.value);
  }
  markDirty();
});

els.presentation.addEventListener("click", (event) => {
  const target = event.target.closest("[data-pres-action]");
  if (!target || !draft) return;
  const action = target.dataset.presAction;
  if (action === "save") {
    savePresentation();
    return;
  }
  const index = Number(target.dataset.index);
  if (!Number.isInteger(index) || !draft.slides[index]) return;
  if (action === "up" && index > 0) {
    [draft.slides[index - 1], draft.slides[index]] = [
      draft.slides[index],
      draft.slides[index - 1],
    ];
  } else if (action === "down" && index < draft.slides.length - 1) {
    [draft.slides[index + 1], draft.slides[index]] = [
      draft.slides[index],
      draft.slides[index + 1],
    ];
  } else if (action === "remove") {
    const removed = draft.slides[index];
    draft.slides.splice(index, 1);
    if (draft.pinned_ref === refOf(removed)) draft.pinned_ref = null;
  } else if (action === "pin") {
    const ref = refOf(draft.slides[index]);
    draft.pinned_ref = draft.pinned_ref === ref ? null : ref;
  }
  markDirty();
  renderPresentation();
});

els.audit.addEventListener("click", async () => {
  try {
    const body = await api("GET", `/api/events/${encodedId()}/audit/verify`);
    showToast(
      body.ok
        ? `Auditoria OK (${body.count} revisões verificadas)`
        : `Auditoria falhou: ${body.reason || "cadeia quebrada"}`,
      !body.ok
    );
  } catch (error) {
    showToast(`Erro na auditoria: ${error.message}`, true);
  }
});

const ws = new WSClient(wsUrl(), (message) => {
  if (!eventId) return;
  if (message.event_id && message.event_id !== eventId) return;
  if (message.type === "presentation_updated") {
    if (!dirty) {
      draft = draftFromPresentation(message.payload);
      presentation = message.payload;
      renderPresentation();
    }
    return;
  }
  if (
    message.type === "heat_state" ||
    message.type === "prova_state" ||
    message.type === "settings_updated" ||
    message.type === "athletes_changed"
  ) {
    debounceRefresh();
  }
});

ws.onStatusChange = (connected) => {
  if (connected) refresh();
};

async function init() {
  els.message.hidden = false;
  try {
    await loadTree();
    await loadPresentation();
    setupPreview();
    els.message.hidden = true;
    const urlProva = params.get("prova");
    const urlHeat = params.get("heat");
    let provaId = urlProva;
    if (!provaId && urlHeat) {
      const found = findHeat(urlHeat);
      provaId = found ? found.prova.id : null;
    }
    if (!provaId) provaId = tree.provas[0] ? tree.provas[0].id : null;
    if (provaId) {
      await selectProva(provaId, urlHeat);
    } else {
      els.detail.innerHTML =
        '<div class="res-message">Nenhuma prova cadastrada neste evento.</div>';
    }
    ws.subscribe(eventId);
    ws.connect();
  } catch (error) {
    els.message.hidden = false;
    els.message.textContent = `Não foi possível carregar os resultados: ${error.message}`;
  }
}

init();
