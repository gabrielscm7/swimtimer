import { api } from "./common/api.js";
import { escapeHtml, formatClock, formatTenths, formatTime } from "./common/format.js";
import { heatTypeLabel } from "./common/ui.js";
import { serverNow } from "./common/clock.js";
import { WSClient, wsUrl } from "./common/ws.js";
import {
  heatRowCount,
  provaRowCount,
  renderHeatResult,
  renderPodium,
  renderProvaResult,
} from "./common/result_views.js";

const {
  heatsSorted,
  nextScheduledAfter: nextScheduledAfterSeq,
  lastFinished: lastFinishedSeq,
  nextInProva,
  nextProvaAfter,
} = window.SequenceLogic;
const { displayName } = window.ResultsLogic;
const {
  configOf: presentationConfigOf,
  eligibleSlides: eligiblePresentationSlides,
  resolveRef: resolvePresentationRef,
  nextProva: nextProvaForDisplay,
  nextProvaLabel,
} = window.PublicPresentationLogic;
const { normalizeTheme, pickReadableColor } = window.ThemeLogic;
const { batteryColumns, clampPage, formatPageIndicator } =
  window.PaginationLogic;

const STATE = Object.freeze({
  SELECT: 0,
  WAITING: 1,
  READY: 2,
  RACING: 3,
  HEAT_RESULT: 4,
  INTERVAL: 5,
  ENDED: 6,
  PROVA_RESULT: 7,
  SLIDE: 8,
});

const STATE_NAMES = {
  [STATE.SELECT]: "select",
  [STATE.WAITING]: "waiting",
  [STATE.READY]: "ready",
  [STATE.RACING]: "racing",
  [STATE.HEAT_RESULT]: "heat_result",
  [STATE.INTERVAL]: "interval",
  [STATE.ENDED]: "ended",
  [STATE.PROVA_RESULT]: "prova_result",
  [STATE.SLIDE]: "slide",
};

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");
const preview = params.get("preview") === "1";
const fast = preview && params.get("fast") === "1";

const RESULT_MS = fast ? 3000 : 20000;
const PROVA_RESULT_MS = fast ? 6000 : 30000;
const PAGE_MS = fast ? 2000 : 8000;
const SLIDE_FAST_MS = 2000;
const FADE_MS = 150;

const els = {
  stage: document.getElementById("pub-stage"),
  bg: document.getElementById("pub-bg"),
  overlay: document.getElementById("pub-overlay"),
  dot: document.getElementById("pub-dot"),
  fullscreen: document.getElementById("pub-fullscreen"),
};

let eventData = null;
let theme = normalizeTheme(null);
let events = [];
let state = STATE.SELECT;
let currentHeatId = null;
let resultTimer = null;
let tickInterval = null;
let pageTimer = null;
let renderToken = 0;
let slideTimer = null;
let slideRef = null;
let slideIndex = 0;
const classifications = {};
let capacity = 40;
let capacityKey = "";
let page = 0;
let pages = 1;

function heats() {
  if (!eventData) return [];
  return heatsSorted(eventData.heats);
}

function currentHeat() {
  if (!eventData || !currentHeatId) return null;
  return eventData.heats.find((heat) => heat.id === currentHeatId) || null;
}

function participantLanes(heat) {
  return [...((heat && heat.heat_lanes) || [])]
    .filter((lane) => lane.participant_name || lane.team_id)
    .sort((a, b) => a.lane_number - b.lane_number);
}

function pubName(name) {
  return displayName(name, eventData ? eventData.public_name_mode : "full");
}

function nextScheduledAfter(eventSeq) {
  return nextScheduledAfterSeq(heats(), eventSeq);
}

function lastFinished() {
  return lastFinishedSeq(heats());
}

function provaOf(heat) {
  if (!heat || !eventData || !eventData.provas) return null;
  return eventData.provas.find((prova) => prova.id === heat.prova_id) || null;
}

function provasSorted() {
  if (!eventData || !eventData.provas) return [];
  return [...eventData.provas].sort((a, b) => a.order_num - b.order_num);
}

function heatLabel(heat) {
  return Labels.bateriaLabel(heat, {
    index: heat.heat_index_in_prova,
    total: heat.heats_in_prova,
    provaOrder: heat.prova_order_num,
    includeProva: true,
  });
}

function heatChipLabel(heat) {
  return Labels.bateriaLabel(heat, {
    index: heat.heat_index_in_prova,
    total: heat.heats_in_prova,
    includeProva: false,
  });
}

function snapshotLabel(status) {
  return (
    {
      official: "Oficial",
      provisional: "Provisório",
      corrected: "Retificado",
    }[status] || null
  );
}

function provaSnapshotLabel(prova) {
  if (!prova) return null;
  const statuses = heats()
    .filter((heat) => heat.prova_id === prova.id)
    .map((heat) => heat.result_snapshot && heat.result_snapshot.status)
    .filter(Boolean);
  if (!statuses.length) return null;
  if (statuses.every((status) => status === "official")) return "Oficial";
  if (statuses.some((status) => status === "corrected")) return "Retificado";
  return "Provisório";
}

function logoImg(url, name) {
  if (!url || !theme.show_team_logos) return "";
  return `<img class="team-logo small" src="${escapeHtml(url)}" alt="${escapeHtml(
    name || "Logo"
  )}" loading="lazy" />`;
}

function eventTitle() {
  return theme.title_override || (eventData ? eventData.name : "SwimTimer");
}

function eventLogo() {
  if (!theme.logo_url) return "";
  return `<img class="pub-event-logo" src="${escapeHtml(
    theme.logo_url
  )}" alt="${escapeHtml(eventTitle())}" />`;
}

function eventMeta() {
  const parts = [];
  if (eventData && eventData.location) parts.push(eventData.location);
  if (eventData && eventData.date) parts.push(eventData.date);
  return parts.join(" · ");
}

function presentationConfig() {
  return presentationConfigOf(eventData);
}

function nextFooterLabel() {
  if (!eventData || !presentationConfig().show_next_prova) return "";
  const reference = currentHeat() || lastFinished();
  if (!reference) return "";
  const sameProva = nextInProva(heats(), reference);
  if (sameProva) {
    return `A seguir: ${Labels.bateriaLabel(sameProva, {
      index: sameProva.heat_index_in_prova,
      total: sameProva.heats_in_prova,
      provaOrder: sameProva.prova_order_num,
      includeProva: true,
    })}`;
  }
  const next = nextProvaForDisplay(heats(), provasSorted(), reference);
  return next ? nextProvaLabel(next) : "";
}

function renderOptions() {
  return {
    nameMode: eventData ? eventData.public_name_mode : "full",
    showLogos: Boolean(theme.show_team_logos),
  };
}

function applyTheme(raw) {
  theme = normalizeTheme(raw);
  const root = document.documentElement;
  root.style.setProperty("--bg", theme.bg);
  root.style.setProperty("--bg-2", theme.bg2);
  root.style.setProperty("--panel", theme.panel);
  root.style.setProperty("--panel-2", theme.panel);
  root.style.setProperty("--row-bg", theme.bg2);
  root.style.setProperty("--input-bg", theme.bg2);
  root.style.setProperty("--cyan", theme.accent);
  root.style.setProperty("--cyan-strong", theme.accent_strong);
  root.style.setProperty("--lvl-evento", theme.text);
  root.style.setProperty("--lvl-prova", theme.lvl_prova);
  root.style.setProperty("--lvl-bateria", theme.lvl_bateria);
  root.style.setProperty("--text", theme.text);
  root.style.setProperty("--muted", theme.muted);
  root.style.setProperty("--pub-font-scale", String(theme.font_scale));
  const podiumBackgrounds = [theme.panel, theme.bg];
  root.style.setProperty(
    "--podium-gold",
    pickReadableColor(["#facc15", "#6b5200"], podiumBackgrounds)
  );
  root.style.setProperty(
    "--podium-silver",
    pickReadableColor(["#cbd5e1", "#475569"], podiumBackgrounds)
  );
  root.style.setProperty(
    "--podium-bronze",
    pickReadableColor(["#d97706", "#9a3412"], podiumBackgrounds)
  );
  if (els.bg) {
    els.bg.style.setProperty(
      "--pub-bg-image",
      theme.bg_image_url ? `url("${theme.bg_image_url}")` : "none"
    );
    els.bg.style.setProperty("--pub-bg-opacity", String(theme.bg_opacity));
    const size =
      theme.bg_fit === "contain"
        ? "contain"
        : theme.bg_fit === "center"
          ? "auto"
          : "cover";
    els.bg.style.setProperty("--pub-bg-size", size);
    els.bg.style.setProperty(
      "--pub-bg-position",
      theme.bg_position || "center"
    );
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme.bg);
}

async function loadTheme() {
  if (!eventId) return;
  try {
    applyTheme(await api("GET", `/api/events/${eventId}/theme`));
  } catch (error) {
    /* mantém o tema atual; o próximo reconnect tenta novamente */
  }
}

function currentProva() {
  if (state === STATE.SLIDE && slideRef) {
    const info = resolvePresentationRef(slideRef, eventData);
    if (info) return info.prova || null;
  }
  return provaOf(currentHeat());
}

function currentProvaId() {
  const prova = currentProva();
  return prova ? prova.id : "";
}

function contentKey() {
  const heat = state === STATE.SLIDE && slideRef
    ? (resolvePresentationRef(slideRef, eventData) || {}).heat
    : currentHeat();
  return [
    state,
    heat ? heat.id : "",
    currentProvaId(),
    state === STATE.SLIDE ? String(slideIndex) : "",
  ].join("|");
}

function stateHeat() {
  if (state === STATE.SLIDE && slideRef) {
    const info = resolvePresentationRef(slideRef, eventData);
    return info ? info.heat : null;
  }
  return currentHeat();
}

// --------------------------------------------------------------------------- //
// Cabeçalho / rodapé (identidade EVENTO → PROVA → BATERIA)
// --------------------------------------------------------------------------- //
function stageHeader() {
  const heat = stateHeat();
  const prova = currentProva();
  const chips = [];
  if (prova) {
    chips.push(
      `<span class="level-chip prova"><span class="level-icon">◆</span>${escapeHtml(
        Labels.provaLabel(prova)
      )}</span>`
    );
  }
  if (heat) {
    chips.push(
      `<span class="level-chip bateria"><span class="level-icon">▸</span>${escapeHtml(
        heatChipLabel(heat)
      )}</span>`
    );
  }
  if (state === STATE.RACING && currentHeat()) {
    const battery = currentHeat().heat_type !== "maratona";
    chips.push(
      `<div class="pub-clock" id="pub-clock">${
        battery
          ? "00:00.0"
          : formatClock(marathonRemaining(currentHeat()))
      }</div>`
    );
    if (!battery) chips.push('<span class="pub-clock-small">restante</span>');
  }
  return `<header class="pub-head">
    <div class="pub-head-event">
      ${eventLogo()}
      <div class="pub-head-text">
        <div class="pub-head-name">${escapeHtml(eventTitle())}</div>
        <div class="pub-head-meta">${escapeHtml(eventMeta())}</div>
      </div>
    </div>
    <div class="pub-head-chips">${chips.join("")}</div>
  </header>`;
}

function footer() {
  const text = theme.footer_text || "";
  const nextText = nextFooterLabel();
  const indicator = formatPageIndicator(page, pages);
  return `<footer class="pub-foot">
    <span class="pub-foot-page">${escapeHtml(indicator)}</span>
    <span class="pub-foot-text">${escapeHtml(text)}</span>
    <span class="pub-foot-next">${escapeHtml(nextText)}</span>
  </footer>`;
}

// --------------------------------------------------------------------------- //
// Paginação
// --------------------------------------------------------------------------- //
function paginate(totalRows, perPage) {
  const total = Math.max(0, Number(totalRows) || 0);
  const size = Math.max(1, Number(perPage) || 1);
  const count = Math.max(1, Math.ceil(total / size));
  return Array.from({ length: count }, (_, index) => ({
    index,
    offset: index * size,
    limit: size,
  }));
}

function windowOpts(win) {
  return { ...renderOptions(), window: { offset: win.offset, limit: win.limit } };
}

function bodyPage(html, className = "") {
  return { html, className };
}

function messagePage(text, className = "pub-body-center") {
  return bodyPage(`<div class="pub-subtitle">${escapeHtml(text)}</div>`, className);
}

function resultMetaBlock(label, title, subtitle) {
  return `<div class="pub-section-title">${escapeHtml(label)}</div>
    <div class="pub-result-meta">
      <div class="pub-title">${escapeHtml(title)}</div>
      <div class="pub-subtitle">${escapeHtml(subtitle || "")}</div>
    </div>`;
}

function heatResultBody(heat, win) {
  const snapshot =
    heat.result_snapshot && snapshotLabel(heat.result_snapshot.status);
  return `${resultMetaBlock(
    "RESULTADO DA BATERIA",
    heatTypeLabel(heat),
    snapshot ? snapshot : ""
  )}
  ${renderPodium(heat, renderOptions())}
  ${renderHeatResult(heat, {
    ...windowOpts(win),
    live: false,
  })}`;
}

function heatResultPages(heat) {
  if (!heat) return [messagePage("Aguardando resultado.")];
  const wins = paginate(heatRowCount(heat), capacity);
  return wins.map((win) => bodyPage(heatResultBody(heat, win)));
}

function provaResultBody(prova, data, win) {
  const meta = [
    prova && prova.naipe === "MISTO" ? "Misto" : "",
    prova ? prova.category || "" : "",
    prova && prova.distance_m ? `${prova.distance_m}m` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const snapshot = provaSnapshotLabel(prova);
  const help = Labels.classificationHelp(
    true,
    heats().filter((heat) => heat.prova_id === (prova ? prova.id : null))
      .length
  );
  const subtitle = [meta, snapshot, help].filter(Boolean).join(" · ");
  return `${resultMetaBlock(
    "RESULTADO FINAL DA PROVA",
    prova ? Labels.provaDescriptor(prova) : currentHeat() ? currentHeat().name : "",
    subtitle
  )}
  <div class="pub-result">
    ${renderProvaResult(prova, data, windowOpts(win))}
  </div>`;
}

function provaFallbackPages(prova) {
  const provaHeats = heats().filter(
    (heat) => heat.prova_id === prova.id && heat.status === "finished"
  );
  if (!provaHeats.length) {
    return [messagePage("Classificação em processamento…")];
  }
  const columns = Math.max(
    1,
    batteryColumns(els.stage.clientWidth || window.innerWidth)
  );
  const pages = [];
  for (let index = 0; index < provaHeats.length; index += columns) {
    pages.push(
      bodyPage(`${resultMetaBlock(
        "RESULTADO FINAL DA PROVA",
        Labels.provaDescriptor(prova),
        ""
      )}${heatsGrid(provaHeats.slice(index, index + columns), columns)}`)
    );
  }
  return pages;
}

function provaResultPages(prova, data) {
  if (!prova) return [messagePage("Aguardando classificação.")];
  if (!data) return provaFallbackPages(prova);
  const wins = paginate(provaRowCount(data, prova), capacity);
  return wins.map((win) => bodyPage(provaResultBody(prova, data, win)));
}

function racingPages(heat) {
  if (!heat) return [messagePage("Aguardando bateria.")];
  const wins = paginate(heatRowCount(heat), capacity);
  return wins.map((win) =>
    bodyPage(renderHeatResult(heat, { ...windowOpts(win), live: true }))
  );
}

function nextUpInfo(heat) {
  if (!heat) return '<div class="pub-subtitle">Nenhuma próxima bateria</div>';
  const lanes = participantLanes(heat);
  return `<div class="pub-section-title">A seguir</div>
    <div class="pub-title">${escapeHtml(heatLabel(heat))}</div>
    <div class="pub-subtitle">${escapeHtml(heatTypeLabel(heat))}</div>
    <div style="margin-top:0.6em">
      ${
        lanes
          .slice(0, 8)
          .map(
            (lane) =>
              `<div class="pub-up-item"><span class="pub-up-num">R${lane.lane_number}</span><span class="pub-up-name">${escapeHtml(
                pubName(lane.participant_name) || "—"
              )}</span><span class="pub-up-team">${escapeHtml(
                lane.team || "sem equipe"
              )}</span></div>`
          )
          .join("") || '<div class="muted">Sem participantes</div>'
      }
    </div>`;
}

function intervalPages(heat) {
  const inProva = heat ? nextInProva(heats(), heat) : null;
  const nextProva =
    heat && !inProva ? nextProvaAfter(heats(), provasSorted(), heat) : null;
  let nextHtml;
  if (inProva) {
    nextHtml = nextUpInfo(inProva);
  } else if (nextProva) {
    nextHtml = `<div class="pub-section-title">Próxima prova</div>
      <div class="pub-title">${escapeHtml(
        Labels.provaDescriptor(nextProva.prova)
      )}</div>
      ${nextUpInfo(nextProva.heat)}`;
  } else {
    nextHtml = '<div class="pub-subtitle">Nenhuma próxima bateria</div>';
  }
  const wins = paginate(heatRowCount(heat), capacity);
  return wins.map((win) =>
    bodyPage(`<div class="pub-interval">
      <div class="pub-interval-col">
        <div class="pub-section-title">Resultado — ${escapeHtml(
          heat ? heatChipLabel(heat) : ""
        )}</div>
        ${
          heat
            ? renderHeatResult(heat, {
                ...windowOpts(win),
                compact: true,
              }) || '<div class="pub-subtitle">Sem resultados</div>'
            : ""
        }
      </div>
      <div class="pub-interval-col">${nextHtml}</div>
    </div>`)
  );
}

function heatsGrid(heatsList, columns) {
  const cards = heatsList
    .map(
      (heat) => `<div class="pub-heat-card">
        <div class="pub-heat-name">${escapeHtml(heatChipLabel(heat))}</div>
        ${renderHeatResult(heat, { ...renderOptions(), variant: "compact" })}
      </div>`
    )
    .join("");
  return `<div class="pub-heat-cards" data-cols="${columns}">${cards}</div>`;
}

function endedPages() {
  const finishedProvas = provasSorted().filter((prova) =>
    heats().some(
      (heat) => heat.prova_id === prova.id && heat.status === "finished"
    )
  );
  if (!finishedProvas.length) {
    return [messagePage("Nenhuma bateria finalizada.")];
  }
  const result = [];
  const columns = Math.max(
    1,
    batteryColumns(els.stage.clientWidth || window.innerWidth)
  );
  for (const prova of finishedProvas) {
    const data = classifications[prova.id];
    if (data) {
      const wins = paginate(provaRowCount(data, prova), capacity);
      for (const win of wins) {
        result.push(bodyPage(provaResultBody(prova, data, win)));
      }
    } else {
      result.push(...provaFallbackPages(prova));
    }
    const provaHeats = heats().filter(
      (heat) => heat.prova_id === prova.id && heat.status === "finished"
    );
    for (let index = 0; index < provaHeats.length; index += columns) {
      result.push(
        bodyPage(`${resultMetaBlock(
          "RESULTADO POR BATERIA",
          Labels.provaDescriptor(prova),
          ""
        )}${heatsGrid(provaHeats.slice(index, index + columns), columns)}`)
      );
    }
  }
  return result;
}

function slidePages() {
  const info = slideRef
    ? resolvePresentationRef(slideRef, eventData)
    : null;
  if (!info) {
    return [messagePage("Apresentação sem conteúdo disponível.")];
  }
  if (info.kind === "prova") {
    return provaResultPages(info.prova, classifications[info.prova.id]);
  }
  const data = classifications[info.prova ? info.prova.id : ""];
  if (info.heat) {
    const snapshot =
      info.heat.result_snapshot &&
      snapshotLabel(info.heat.result_snapshot.status);
    const wins = paginate(heatRowCount(info.heat), capacity);
    return wins.map((win) =>
      bodyPage(`${resultMetaBlock(
        "RESULTADO DA BATERIA",
        heatTypeLabel(info.heat),
        snapshot ? snapshot : ""
      )}
      ${renderPodium(info.heat, renderOptions())}
      ${renderHeatResult(info.heat, windowOpts(win))}`)
    );
  }
  if (data) return provaResultPages(info.prova, data);
  return [messagePage("Classificação em processamento…")];
}

function waitingPage() {
  const upcoming = heats()
    .filter((heat) => heat.status === "scheduled")
    .slice(0, 4)
    .map(
      (heat) =>
        `<div class="pub-up-item"><span class="pub-up-num">${heat.event_seq}</span><span class="pub-up-name">${escapeHtml(
          heatLabel(heat)
        )}</span><span class="pub-up-team">${escapeHtml(
          heatTypeLabel(heat)
        )}</span></div>`
    )
    .join("");
  return bodyPage(
    `<div class="pub-upcoming">
      <div class="pub-section-title">A seguir</div>
      ${
        upcoming ||
        '<div class="pub-subtitle">Nenhuma bateria agendada</div>'
      }
    </div>
    <div class="pub-waiting"><span class="dot online"></span> Aguardando início</div>`,
    "pub-body-center"
  );
}

function readyPage() {
  const heat = currentHeat();
  if (!heat) return waitingPage();
  const cards = participantLanes(heat)
    .map(
      (lane) => `<div class="pub-lane-card">
        <div class="pub-lane-num">RAIA ${lane.lane_number}</div>
        <div class="pub-lane-name">${escapeHtml(
          pubName(lane.participant_name) || "—"
        )}</div>
        <div class="pub-lane-team">${logoImg(
          lane.team_logo_url,
          lane.team
        )} ${escapeHtml(lane.team || "sem equipe")}</div>
      </div>`
    )
    .join("");
  return bodyPage(
    `${resultMetaBlock("A SEGUIR", heatLabel(heat), heatTypeLabel(heat))}
    <div class="pub-lane-grid">${
      cards || '<div class="pub-subtitle">Sem participantes</div>'
    }</div>`,
    "pub-body-center"
  );
}

function buildPages() {
  switch (state) {
    case STATE.HEAT_RESULT:
      return heatResultPages(currentHeat());
    case STATE.PROVA_RESULT:
      return provaResultPages(currentProva(), classifications[currentProvaId()]);
    case STATE.RACING:
      return racingPages(currentHeat());
    case STATE.INTERVAL:
      return intervalPages(currentHeat());
    case STATE.ENDED:
      return endedPages();
    case STATE.SLIDE:
      return slidePages();
    case STATE.READY:
      return [readyPage()];
    case STATE.WAITING:
      return [waitingPage()];
    case STATE.SELECT:
      return [bodyPage("")];
    default:
      return [waitingPage()];
  }
}

function selectionHTML() {
  const cards = events
    .map((event) => {
      const info = [
        event.location || null,
        `${event.heats.length} bateria(s)`,
      ]
        .filter(Boolean)
        .join(" · ");
      return `<a class="pub-select-card" href="publico.html?event=${event.id}">${escapeHtml(
        event.name
      )}<small>${escapeHtml(info)}</small></a>`;
    })
    .join("");
  return `<div class="pub-body pub-body-center">
    <div class="pub-selection">
      <h1 class="pub-title">Swim<span style="color:var(--cyan)">Timer</span></h1>
      <div class="pub-subtitle">Selecione o evento para exibir</div>
      ${cards || '<div class="pub-subtitle">Nenhum evento ativo no momento</div>'}
    </div>
  </div>`;
}

function stageHTML() {
  const list = buildPages();
  pages = list.length;
  page = clampPage(page, pages);
  const body = list[page] || list[0] || bodyPage("");
  if (state === STATE.SELECT) return selectionHTML();
  return `${stageHeader()}<div class="pub-body ${
    body.className || ""
  }">${body.html}</div>${footer()}`;
}

function fit() {
  let guard = 0;
  while (guard < 12) {
    const body = els.stage.querySelector(".pub-body");
    if (!body) return;
    if (body.scrollHeight <= body.clientHeight + 1) return;
    if (capacity <= 1) return;
    const ratio = body.clientHeight / Math.max(1, body.scrollHeight);
    const next = Math.max(
      1,
      Math.min(capacity - 1, Math.floor(capacity * ratio))
    );
    if (next >= capacity) return;
    capacity = next;
    els.stage.innerHTML = stageHTML();
    guard += 1;
  }
}

function managePager() {
  if (pageTimer) {
    window.clearInterval(pageTimer);
    pageTimer = null;
  }
  if (pages > 1 && state !== STATE.SELECT) {
    pageTimer = window.setInterval(() => {
      page = (page + 1) % pages;
      els.stage.innerHTML = stageHTML();
      fit();
    }, PAGE_MS);
  }
}

function render(html, fade = true) {
  els.stage.classList.toggle("pub-select", state === STATE.SELECT);
  els.stage.dataset.state = STATE_NAMES[state] || "unknown";
  const token = ++renderToken;
  if (!fade) {
    els.stage.style.opacity = "1";
    els.stage.innerHTML = html;
    fit();
    managePager();
    return;
  }
  els.stage.style.opacity = "0";
  window.setTimeout(() => {
    if (token !== renderToken) return;
    els.stage.innerHTML = html;
    els.stage.style.opacity = "1";
    fit();
    managePager();
  }, FADE_MS);
}

function renderCurrent(fade = true) {
  const key = contentKey();
  if (key !== capacityKey) {
    capacityKey = key;
    capacity = 40;
    page = 0;
  }
  pages = buildPages().length;
  page = clampPage(page, pages);
  render(stageHTML(), fade);
}

function rerender(fade = false) {
  renderCurrent(fade);
  manageTick();
}

// --------------------------------------------------------------------------- //
// Estado / transições
// --------------------------------------------------------------------------- //
function setState(next, options = {}) {
  if (next !== STATE.SLIDE) stopSlideTimer();
  const heatId = options.heatId !== undefined ? options.heatId : currentHeatId;
  const same = next === state && heatId === currentHeatId;
  currentHeatId = heatId;
  state = next;
  if (resultTimer) {
    window.clearTimeout(resultTimer);
    resultTimer = null;
  }
  if (next === STATE.HEAT_RESULT || next === STATE.PROVA_RESULT) {
    renderCurrent(true);
    resultTimer = window.setTimeout(() => {
      resultTimer = null;
      if (next === STATE.PROVA_RESULT) goAfterProvaResult();
      else goAfterResult();
    }, next === STATE.PROVA_RESULT ? PROVA_RESULT_MS : RESULT_MS);
    if (next === STATE.PROVA_RESULT) {
      refreshClassifications().then(() => {
        if (state === STATE.PROVA_RESULT) rerender(false);
      });
    }
  } else {
    renderCurrent(!same);
  }
  manageTick();
}

function goAfterResult() {
  const heat = currentHeat();
  if (!heat) return setState(STATE.WAITING, { heatId: null });
  if (!nextInProva(heats(), heat)) {
    return setState(STATE.PROVA_RESULT, { heatId: heat.id });
  }
  if (
    presentationConfig().enabled &&
    eligiblePresentationSlides(eventData).length
  ) {
    return resumeIdle();
  }
  setState(STATE.INTERVAL, { heatId: heat.id });
}

function goAfterProvaResult() {
  if (
    presentationConfig().enabled &&
    eligiblePresentationSlides(eventData).length
  ) {
    return resumeIdle();
  }
  const heat = currentHeat();
  const next = heat ? nextScheduledAfter(heat.event_seq) : null;
  if (next) setState(STATE.INTERVAL, { heatId: heat.id });
  else if (allFinished()) setState(STATE.ENDED, { heatId: null });
  else setState(STATE.WAITING, { heatId: null });
}

function manageTick() {
  if (state === STATE.RACING && !tickInterval) {
    tickInterval = window.setInterval(updateTick, 100);
  } else if (state !== STATE.RACING && tickInterval) {
    window.clearInterval(tickInterval);
    tickInterval = null;
  }
  if (state === STATE.RACING) updateTick();
}

function marathonRemaining(heat) {
  if (!heat.started_at) return heat.duration_s || 0;
  return Math.max(0, (heat.duration_s || 0) - (serverNow() - heat.started_at));
}

function updateTick() {
  const heat = currentHeat();
  if (!heat || heat.status !== "active") return;
  const clock = document.getElementById("pub-clock");
  if (clock) {
    if (heat.heat_type === "maratona") {
      clock.textContent = formatClock(marathonRemaining(heat));
    } else {
      const elapsed = heat.started_at
        ? Math.max(0, serverNow() - heat.started_at)
        : 0;
      clock.textContent = formatTenths(elapsed);
    }
  }
  if (heat.heat_type === "bateria" && heat.started_at) {
    const text = formatTime((serverNow() - heat.started_at) * 1000);
    document.querySelectorAll("[data-lane-time]").forEach((el) => {
      el.textContent = text;
    });
  }
}

// --------------------------------------------------------------------------- //
// Apresentação curada
// --------------------------------------------------------------------------- //
function stopSlideTimer() {
  if (slideTimer) {
    window.clearTimeout(slideTimer);
    slideTimer = null;
  }
}

function slideDurationMs() {
  if (fast) return SLIDE_FAST_MS;
  return presentationConfig().slide_duration_s * 1000;
}

function showSlide(ref) {
  stopSlideTimer();
  if (resultTimer) {
    window.clearTimeout(resultTimer);
    resultTimer = null;
  }
  slideRef = ref;
  state = STATE.SLIDE;
  renderCurrent(true);
  manageTick();
}

function advanceSlide() {
  stopSlideTimer();
  const slides = eligiblePresentationSlides(eventData);
  if (!slides.length) {
    slideRef = null;
    return resumeIdle();
  }
  const config = presentationConfig();
  if (config.pinned_ref) {
    const pinned = slides.find((slide) => slide.ref === config.pinned_ref);
    if (pinned) {
      slideIndex = slides.indexOf(pinned);
      return showSlide(pinned.ref);
    }
  }
  if (!config.rotation) {
    slideIndex = 0;
    return showSlide(slides[0].ref);
  }
  if (slideIndex >= slides.length) slideIndex = 0;
  showSlide(slides[slideIndex].ref);
  if (slides.length > 1) {
    slideTimer = window.setTimeout(() => {
      slideIndex += 1;
      advanceSlide();
    }, slideDurationMs());
  }
}

function resumeIdle() {
  stopSlideTimer();
  if (
    presentationConfig().enabled &&
    eligiblePresentationSlides(eventData).length
  ) {
    slideIndex = 0;
    return advanceSlide();
  }
  if (allFinished()) return setState(STATE.ENDED, { heatId: null });
  const last = lastFinished();
  if (last && nextScheduledAfter(last.event_seq)) {
    return setState(STATE.INTERVAL, { heatId: last.id });
  }
  return setState(STATE.WAITING, { heatId: null });
}

// --------------------------------------------------------------------------- //
// Reconciliação / WebSocket
// --------------------------------------------------------------------------- //
function allFinished() {
  const list = heats();
  return list.length > 0 && list.every((heat) => heat.status === "finished");
}

function reconcile() {
  const active = heats().find((heat) => heat.status === "active");
  if (active) return setState(STATE.RACING, { heatId: active.id });
  const ready = heats().find((heat) => heat.status === "ready_check");
  if (ready) return setState(STATE.READY, { heatId: ready.id });
  if (
    presentationConfig().enabled &&
    eligiblePresentationSlides(eventData).length
  ) {
    return resumeIdle();
  }
  if (allFinished()) return setState(STATE.ENDED, { heatId: null });
  const last = lastFinished();
  if (last && nextScheduledAfter(last.event_seq)) {
    if (!nextInProva(heats(), last)) {
      return setState(STATE.PROVA_RESULT, { heatId: last.id });
    }
    return setState(STATE.INTERVAL, { heatId: last.id });
  }
  return setState(STATE.WAITING, { heatId: null });
}

async function refreshClassifications() {
  if (!eventData || !eventData.provas) return;
  const targets = eventData.provas.filter(
    (prova) =>
      eventData.heats.some(
        (heat) => heat.prova_id === prova.id && heat.status === "finished"
      )
  );
  await Promise.all(
    targets.map(async (prova) => {
      try {
        classifications[prova.id] = await api(
          "GET",
          `/api/provas/${prova.id}/classification`
        );
      } catch (error) {
        /* mantém classificação anterior */
      }
    })
  );
}

async function refreshEvent() {
  try {
    eventData = await api("GET", `/api/events/${eventId}`);
    await loadTheme();
    await refreshClassifications();
    reconcile();
  } catch (error) {
    /* mantém estado atual */
  }
}

function upsertProva(payload) {
  if (!eventData) return;
  const provas = eventData.provas || (eventData.provas = []);
  const index = provas.findIndex((prova) => prova.id === payload.id);
  const summary = {
    id: payload.id,
    event_id: payload.event_id,
    name: payload.name,
    order_num: payload.order_num,
    format: payload.format,
    stroke: payload.stroke,
    distance_m: payload.distance_m,
    naipe: payload.naipe,
    mixed_ranking: payload.mixed_ranking,
    category: payload.category,
    classification_criterion: payload.classification_criterion,
    status: payload.status,
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

function onHeatState(heat) {
  if (!eventData) return;
  const index = eventData.heats.findIndex((item) => item.id === heat.id);
  if (index < 0) {
    refreshEvent();
    return;
  }
  const previousStatus = eventData.heats[index].status;
  eventData.heats[index] = heat;
  if (heat.status === "ready_check") {
    setState(STATE.READY, { heatId: heat.id });
  } else if (heat.status === "active") {
    setState(STATE.RACING, { heatId: heat.id });
  } else if (heat.status === "finished") {
    if (previousStatus === "active" && heat.id === currentHeatId) {
      setState(STATE.HEAT_RESULT, { heatId: heat.id });
    }
    refreshClassifications().then(() => rerender(false));
  } else {
    rerender(false);
  }
}

function onPresentationUpdated(payload) {
  if (!eventData) return;
  eventData.presentation = payload;
  const config = presentationConfig();
  const slides = eligiblePresentationSlides(eventData);
  if (state === STATE.SLIDE) {
    if (!slides.length) return resumeIdle();
    if (config.pinned_ref) {
      const pinned = slides.find((slide) => slide.ref === config.pinned_ref);
      if (pinned) {
        slideIndex = slides.indexOf(pinned);
        return showSlide(pinned.ref);
      }
    }
    slideIndex = Math.min(slideIndex, slides.length - 1);
    return showSlide(slides[slideIndex].ref);
  }
  if (
    [STATE.WAITING, STATE.INTERVAL, STATE.ENDED, STATE.PROVA_RESULT].includes(
      state
    ) &&
    config.enabled &&
    slides.length
  ) {
    slideIndex = 0;
    return advanceSlide();
  }
  rerender(false);
}

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "heat_state") onHeatState(message.payload);
  else if (message.type === "prova_state") {
    upsertProva(message.payload);
    api("GET", `/api/provas/${message.payload.id}/classification`)
      .then((data) => {
        classifications[message.payload.id] = data;
        rerender(false);
      })
      .catch(() => rerender(false));
  } else if (message.type === "theme_updated") {
    if (eventId && (!message.event_id || message.event_id === eventId)) {
      applyTheme(message.payload);
      rerender(false);
    }
  } else if (message.type === "presentation_updated") {
    onPresentationUpdated(message.payload);
  } else if (message.type === "settings_updated") {
    if (eventData && message.payload.public_name_mode) {
      eventData.public_name_mode = message.payload.public_name_mode;
    }
    rerender(false);
  } else if (message.type === "error") {
    console.warn("WS:", message.message);
  }
});

ws.onStatusChange = (connected) => {
  els.dot.classList.toggle("online", connected);
  els.dot.classList.toggle("offline", !connected);
  if (connected && eventData) refreshEvent();
};

// --------------------------------------------------------------------------- //
// Fullscreen / init
// --------------------------------------------------------------------------- //
els.fullscreen.addEventListener("click", () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
});

document.addEventListener("fullscreenchange", () => {
  els.fullscreen.textContent = document.fullscreenElement ? "🗗" : "⛶";
});

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  if (!event.data || event.data.type !== "theme_preview") return;
  applyTheme(event.data.theme);
  if (eventData) rerender(false);
});

async function loadSelection() {
  els.overlay.hidden = true;
  try {
    const all = await api("GET", "/api/events");
    events = all.filter((event) => event.status !== "finished");
  } catch (error) {
    events = [];
  }
  setState(STATE.SELECT, { heatId: null });
}

async function init() {
  if (!eventId) {
    await loadSelection();
    return;
  }
  els.overlay.hidden = preview;
  try {
    eventData = await api("GET", `/api/events/${eventId}`);
  } catch (error) {
    window.location.replace("publico.html");
    return;
  }
  await loadTheme();
  await refreshClassifications();
  reconcile();
  ws.subscribe(eventId, { public: true });
  ws.connect();
}

init();
