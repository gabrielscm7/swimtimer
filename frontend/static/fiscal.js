import { api } from "./common/api.js";
import { escapeHtml, formatTenths, formatTime } from "./common/format.js";
import { heatTypeLabel, showToast } from "./common/ui.js";
import { serverNow } from "./common/clock.js";
import { WSClient, wsUrl } from "./common/ws.js";

const STORAGE_KEY = "swimtimer_fiscal";
const OUTBOX_KEY = "swimtimer_fiscal_outbox";
const REJECTED_KEY = "swimtimer_fiscal_rejeitados";
const UNDO_WINDOW_MS = 30000;
const ACK_TIMEOUT_MS = 3000;
const REGISTER_GUARD_MS = 12000;

const { isTerminalError, applyLaneUpdate } = window.FiscalLogic;
const { newOpId } = window.ClockLogic;
const { heatsSorted } = window.SequenceLogic;

const els = {
  offlineBanner: document.getElementById("offline-banner"),
  rejectedBanner: document.getElementById("rejected-banner"),
  rejectedList: document.getElementById("rejected-list"),
  rejectedClear: document.getElementById("rejected-clear"),
  hdrEvent: document.getElementById("hdr-event"),
  hdrDot: document.getElementById("hdr-dot"),
  // Tela 1
  fsEvent: document.getElementById("fs-event"),
  fsLaneCard: document.getElementById("fs-lane-card"),
  fsLaneGrid: document.getElementById("fs-lane-grid"),
  fsPreview: document.getElementById("fs-preview"),
  fsConfirm: document.getElementById("fs-confirm"),
  // Tela 2
  fwLane: document.getElementById("fw-lane"),
  fwParticipant: document.getElementById("fw-participant"),
  fwTeam: document.getElementById("fw-team"),
  fwHeatName: document.getElementById("fw-heat-name"),
  fwHeatInfo: document.getElementById("fw-heat-info"),
  fwReady: document.getElementById("fw-ready"),
  // Tela 3
  frParticipant: document.getElementById("fr-participant"),
  frLanes: document.getElementById("fr-lanes"),
  // Tela 4
  fcParticipant: document.getElementById("fc-participant"),
  fcTeam: document.getElementById("fc-team"),
  fcClock: document.getElementById("fc-clock"),
  fcLapInfo: document.getElementById("fc-lap-info"),
  fcRegister: document.getElementById("fc-register"),
  fcUndo: document.getElementById("fc-undo"),
  fcDq: document.getElementById("fc-dq"),
  // Tela 5
  ffIcon: document.getElementById("ff-icon"),
  ffTitle: document.getElementById("ff-title"),
  ffParticipant: document.getElementById("ff-participant"),
  ffTeam: document.getElementById("ff-team"),
  ffTime: document.getElementById("ff-time"),
  ffSpeed: document.getElementById("ff-speed"),
  ffLanes: document.getElementById("ff-lanes"),
  ffBanner: document.getElementById("ff-banner"),
  ffNext: document.getElementById("ff-next"),
  // Modal
  dqModal: document.getElementById("dq-modal"),
  dqText: document.getElementById("dq-text"),
  dqCancel: document.getElementById("dq-cancel"),
  dqConfirm: document.getElementById("dq-confirm"),
};

const SCREENS = ["config", "waiting", "ready", "racing", "finished"];

let events = [];
let eventDetail = null;
let configEvent = null;
let configHeat = null;
let configEventId = null;
let selectedLaneId = null;

let selection = null;
let currentHeat = null;
let readyInfo = null;
let currentScreen = null;
let offline = false;
let reconciling = false;
let racingTimer = null;
let audioCtx = null;
let wakeLock = null;
let registerPending = false;
let registerTimeout = null;

// --------------------------------------------------------------------------- //
// Persistência
// --------------------------------------------------------------------------- //
function loadSelection() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch (error) {
    return null;
  }
}

function saveSelection() {
  if (selection) localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
}

function clearSelection() {
  localStorage.removeItem(STORAGE_KEY);
}

function syncSubscription() {
  if (selection && selection.event_id) {
    ws.subscribe(selection.event_id);
  } else {
    ws.subscribe(null);
  }
}

function outboxLoad() {
  try {
    return JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]");
  } catch (error) {
    return [];
  }
}

function outboxSave(items) {
  localStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
}

function outboxAdd(item) {
  const queue = outboxLoad();
  queue.push({ ...item, ts: item.ts || Date.now() });
  outboxSave(queue);
}

function outboxRemove(opId) {
  if (!opId) return;
  outboxSave(outboxLoad().filter((item) => item.op_id !== opId));
}

function enqueue(item) {
  outboxAdd(item);
  setOffline(true);
  showToast("Sem conexão — registro em fila", true);
}

// --------------------------------------------------------------------------- //
// Registros rejeitados (4xx): visíveis, nunca descartados em silêncio
// --------------------------------------------------------------------------- //
function rejectedLoad() {
  try {
    return JSON.parse(localStorage.getItem(REJECTED_KEY) || "[]");
  } catch (error) {
    return [];
  }
}

function rejectedSave(items) {
  localStorage.setItem(REJECTED_KEY, JSON.stringify(items));
}

function recordRejected(item, motivo) {
  const items = rejectedLoad();
  items.push({
    op_id: item.op_id,
    action: item.action,
    lane_id: item.lane_id,
    motivo,
    ts: Date.now(),
  });
  rejectedSave(items);
  renderRejected();
}

function renderRejected() {
  if (!els.rejectedBanner || !els.rejectedList) return;
  const items = rejectedLoad();
  els.rejectedBanner.hidden = items.length === 0;
  els.rejectedList.innerHTML = "";
  for (const item of items.slice(-10)) {
    const line = document.createElement("li");
    const when = new Date(item.ts || Date.now()).toLocaleTimeString();
    line.textContent = `${when} · ${item.action || "registro"} · ${item.motivo}`;
    els.rejectedList.appendChild(line);
  }
}

function clearRejected() {
  rejectedSave([]);
  renderRejected();
}

let flushingOutbox = false;

async function flushOutbox() {
  if (flushingOutbox) return;
  flushingOutbox = true;
  try {
    const queue = outboxLoad();
    if (!queue.length) return;
    const remaining = [];
    for (const item of queue) {
      try {
        const result = await api(item.method, item.path, item.body);
        outboxRemove(item.op_id);
        const entry = item.op_id ? pendingOps.get(item.op_id) : null;
        if (entry) entry.finish(null, result);
      } catch (error) {
        if (isTerminalError(error)) {
          // 4xx definitivo: sai da fila, mas fica visível como rejeitado.
          outboxRemove(item.op_id);
          recordRejected(item, error.message);
          showToast(`Registro rejeitado: ${error.message}`, true);
          const entry = item.op_id ? pendingOps.get(item.op_id) : null;
          if (entry) entry.finish(error);
          continue;
        }
        remaining.push(item);
      }
    }
    outboxSave(remaining);
    setOffline(remaining.length > 0);
  } finally {
    flushingOutbox = false;
  }
}

function setOffline(value) {
  offline = value;
  const queued = outboxLoad().length;
  els.hdrDot.classList.toggle("online", !value);
  els.hdrDot.classList.toggle("offline", value);
  if (value) {
    els.offlineBanner.hidden = false;
    els.offlineBanner.textContent = queued
      ? `Sem conexão — ${queued} registro(s) em fila`
      : "Sem conexão — registros em fila";
  } else {
    els.offlineBanner.hidden = true;
  }
}

function isNetworkError(error) {
  return !error || !error.status;
}

// --------------------------------------------------------------------------- //
// Áudio / Wake Lock
// --------------------------------------------------------------------------- //
function ensureAudio() {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === "suspended") audioCtx.resume();
  } catch (error) {
    /* áudio indisponível */
  }
}

function tocarBuzzer() {
  try {
    ensureAudio();
    if (!audioCtx) return;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.9, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 1.5);
    osc.start(audioCtx.currentTime);
    osc.stop(audioCtx.currentTime + 1.5);
  } catch (error) {
    console.warn("Audio não disponível", error);
  }
}

async function manterTelaAtiva() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (error) {
    /* silencioso */
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && currentScreen === "racing") {
    manterTelaAtiva();
  }
});

// --------------------------------------------------------------------------- //
// Estado / telas
// --------------------------------------------------------------------------- //
function currentLane() {
  if (!currentHeat || !selection) return null;
  return currentHeat.heat_lanes.find((lane) => lane.id === selection.lane_id) || null;
}

function resolveScreen(heat, lane) {
  if (!heat || !lane) return "config";
  if (lane.status === "finished" || lane.status === "dq") return "finished";
  if (heat.status === "finished") return "finished";
  if (heat.status === "active") return "racing";
  if (lane.status === "ready") return "ready";
  return "waiting";
}

function show(screen, options = {}) {
  const enteringRacing = screen === "racing" && currentScreen !== "racing";
  if (screen !== "racing") setRegisterPending(false);
  SCREENS.forEach((name) => {
    document.getElementById(`screen-${name}`).hidden = name !== screen;
  });
  currentScreen = screen;
  if (enteringRacing) {
    if (options.buzzer) tocarBuzzer();
    manterTelaAtiva();
  }
  if (screen === "racing") startTimer();
  else stopTimer();
  renderScreen();
}

function renderScreen() {
  if (selection) {
    els.hdrEvent.textContent = `${selection.event_name} · raia ${selection.lane_number}`;
  } else {
    els.hdrEvent.textContent = "Fiscal";
  }
  if (currentScreen === "config") renderConfig();
  else if (currentScreen === "waiting") renderWaiting();
  else if (currentScreen === "ready") renderReady();
  else if (currentScreen === "racing") renderRacing();
  else if (currentScreen === "finished") renderFinished();
}

function applyState(options = {}) {
  if (!selection) {
    show("config");
    return;
  }
  const lane = currentLane();
  if (!currentHeat || !lane) {
    clearSelection();
    selection = null;
    show("config");
    return;
  }
  show(resolveScreen(currentHeat, lane), options);
}

// --------------------------------------------------------------------------- //
// Tela 1 — Configuração
// --------------------------------------------------------------------------- //
async function loadEvents() {
  try {
    const all = await api("GET", "/api/events");
    events = all.filter((event) => event.status !== "finished");
    setOffline(false);
    renderConfig();
  } catch (error) {
    setOffline(true);
  }
}

function provaOfHeat(event, heat) {
  if (!event || !event.provas || !heat) return null;
  return event.provas.find((prova) => prova.id === heat.prova_id) || null;
}

function pickConfigHeat(event) {
  const heats = heatsSorted(event.heats);
  return (
    heats.find((heat) => heat.status === "active") ||
    heats.find((heat) => heat.status === "ready_check") ||
    heats.find((heat) => heat.status === "scheduled") ||
    null
  );
}

function renderConfig() {
  els.fsEvent.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Selecione o evento...";
  els.fsEvent.appendChild(placeholder);
  for (const event of events) {
    const option = document.createElement("option");
    option.value = event.id;
    option.textContent = event.name;
    els.fsEvent.appendChild(option);
  }
  els.fsEvent.value = configEventId || "";

  if (!configHeat) {
    els.fsLaneCard.hidden = true;
    els.fsConfirm.disabled = true;
    els.fsPreview.textContent = "";
    return;
  }

  const lanes = [...configHeat.heat_lanes].sort(
    (a, b) => a.lane_number - b.lane_number
  );
  els.fsLaneCard.hidden = false;
  els.fsLaneGrid.innerHTML = "";
  for (const lane of lanes) {
    const button = document.createElement("button");
    button.textContent = String(lane.lane_number);
    button.disabled = !lane.participant_name;
    button.classList.toggle("selected", lane.id === selectedLaneId);
    if (!lane.participant_name) {
      button.title = "Raia sem participante atribuído";
    }
    button.addEventListener("click", () => {
      selectedLaneId = lane.id;
      renderConfig();
    });
    els.fsLaneGrid.appendChild(button);
  }

  const chosen = lanes.find((lane) => lane.id === selectedLaneId);
  if (chosen && chosen.participant_name) {
    const prova = provaOfHeat(configEvent, configHeat);
    els.fsPreview.textContent = `${
      prova ? Labels.provaLabel(prova) + " · " : ""
    }${Labels.bateriaLabel(configHeat, {
      includeProva: !prova,
    })} · ${chosen.participant_name} · ${chosen.team || "sem equipe"}`;
  } else if (!lanes.length) {
    els.fsPreview.textContent = "Nenhuma raia configurada nesta bateria.";
  } else if (chosen) {
    els.fsPreview.textContent = "Raia sem participante atribuído";
  } else {
    els.fsPreview.textContent = "";
  }
  els.fsConfirm.disabled = !(configEventId && selectedLaneId);
}

async function onConfigEventChange() {
  configEventId = els.fsEvent.value;
  selectedLaneId = null;
  configEvent = null;
  configHeat = null;
  if (!configEventId) {
    renderConfig();
    return;
  }
  try {
    configEvent = await api("GET", `/api/events/${configEventId}`);
    configHeat = pickConfigHeat(configEvent);
  } catch (error) {
    setOffline(true);
  }
  renderConfig();
}

function confirmPosition() {
  if (!configEvent || !configHeat || !selectedLaneId) return;
  const lane = configHeat.heat_lanes.find((item) => item.id === selectedLaneId);
  if (!lane) return;
  selection = {
    event_id: configEvent.id,
    lane_id: lane.id,
    lane_number: lane.lane_number,
    event_name: configEvent.name,
    participant_name: lane.participant_name,
  };
  saveSelection();
  syncSubscription();
  currentHeat = configHeat;
  eventDetail = configEvent;
  readyInfo = null;
  ensureAudio();
  applyState({ buzzer: false });
}

function changeLane() {
  clearSelection();
  selection = null;
  currentHeat = null;
  eventDetail = null;
  readyInfo = null;
  configEvent = null;
  configHeat = null;
  configEventId = null;
  selectedLaneId = null;
  syncSubscription();
  show("config");
  loadEvents();
}

// --------------------------------------------------------------------------- //
// Tela 2 — Aguardando bateria
// --------------------------------------------------------------------------- //
function renderWaiting() {
  const lane = currentLane();
  if (!lane) return;
  els.fwLane.textContent = `RAIA ${lane.lane_number}`;
  els.fwParticipant.textContent = lane.participant_name || "Sem participante";
  els.fwTeam.textContent = lane.team || "Sem equipe";
  const prova = provaOfHeat(eventDetail, currentHeat);
  els.fwHeatName.innerHTML = `${
    prova
      ? `<div class="muted"><span class="level-chip prova"><span class="level-icon">◆</span>PROVA</span> ${escapeHtml(
          Labels.provaLabel(prova)
        )}</div>`
      : ""
  }<div><span class="level-chip bateria"><span class="level-icon">▸</span>BATERIA</span> <strong>${escapeHtml(
    Labels.bateriaLabel(currentHeat, { includeProva: !prova })
  )}</strong></div>`;
  els.fwHeatInfo.textContent = heatTypeLabel(currentHeat);
  const canReady = currentHeat.status === "ready_check";
  els.fwReady.disabled = !canReady;
  els.fwReady.textContent = canReady ? "✅ ESTOU PRONTO" : "AGUARDANDO CHAMADA";
}

async function actionReady(button) {
  const lane = currentLane();
  if (!lane) return;
  ensureAudio();
  button.disabled = true;
  button.textContent = "REGISTRANDO...";
  try {
    await api("POST", `/api/lanes/${lane.id}/ready`);
    lane.status = "ready";
    show("ready");
  } catch (error) {
    if (isNetworkError(error)) {
      enqueue({ method: "POST", path: `/api/lanes/${lane.id}/ready` });
      lane.status = "ready";
      show("ready");
      return;
    }
    showToast(`Erro: ${error.message}`, true);
    renderWaiting();
  }
}

// --------------------------------------------------------------------------- //
// Tela 3 — Aguardando outros fiscais
// --------------------------------------------------------------------------- //
function renderReady() {
  const lane = currentLane();
  if (!lane) return;
  els.frParticipant.textContent = lane.participant_name || "";
  const lanes = currentHeat.heat_lanes.filter(
    (item) => item.participant_name || item.team_id
  );
  const readySet = new Set(
    eventDetail && readyInfo && readyInfo.heat_id === currentHeat.id
      ? readyInfo.lanes_ready
      : lanes
          .filter((item) => item.status === "ready")
          .map((item) => item.lane_number)
  );
  els.frLanes.innerHTML = "";
  for (const item of lanes) {
    const ready = readySet.has(item.lane_number);
    const line = document.createElement("div");
    line.className = "lane-line";
    line.innerHTML = `<span>${ready ? "🟢" : "🔴"}</span><span>Raia ${item.lane_number} · ${escapeHtml(item.participant_name || "Aguardando...")}</span>`;
    els.frLanes.appendChild(line);
  }
}

// --------------------------------------------------------------------------- //
// Tela 4 — Em prova
// --------------------------------------------------------------------------- //
function renderRacing() {
  const lane = currentLane();
  if (!lane) return;
  const battery = currentHeat.heat_type === "bateria";
  els.fcParticipant.innerHTML = `<strong>${escapeHtml(lane.participant_name || "Sem participante")}</strong>`;
  els.fcTeam.textContent = lane.team || "Sem equipe";
  const idleLabel = battery
    ? "✋ REGISTRAR CHEGADA"
    : "✋ REGISTRAR CHEGADA/VOLTA";
  els.fcRegister.disabled = registerPending;
  els.fcRegister.textContent = registerPending ? "REGISTRANDO..." : idleLabel;
  els.fcUndo.hidden = battery;
  els.fcLapInfo.textContent = battery
    ? ""
    : lane.laps
      ? `Volta ${lane.laps} registrada`
      : "Nenhuma volta registrada";
  if (!battery) {
    els.fcUndo.disabled = !canUndoLap(lane);
  }
}

function canUndoLap(lane) {
  return (
    lane.last_lap_at != null &&
    serverNow() - lane.last_lap_at < UNDO_WINDOW_MS / 1000 &&
    lane.laps > 0
  );
}

function startTimer() {
  if (racingTimer) return;
  racingTimer = setInterval(tick, 100);
  tick();
}

function stopTimer() {
  if (racingTimer) {
    clearInterval(racingTimer);
    racingTimer = null;
  }
}

function tick() {
  const lane = currentLane();
  if (!lane || !currentHeat || currentScreen !== "racing") return;
  const elapsed = currentHeat.started_at
    ? Math.max(0, serverNow() - currentHeat.started_at)
    : 0;
  els.fcClock.textContent = formatTenths(elapsed);
  if (currentHeat.heat_type === "maratona") {
    els.fcUndo.disabled = !canUndoLap(lane);
  }
}

function wsSend(payload) {
  try {
    if (ws.ws && ws.ws.readyState === WebSocket.OPEN) {
      return ws.send(payload);
    }
  } catch (error) {
    /* noop */
  }
  return false;
}

function setRegisterPending(value) {
  registerPending = value;
  if (registerTimeout) {
    clearTimeout(registerTimeout);
    registerTimeout = null;
  }
  if (value) {
    registerTimeout = setTimeout(() => {
      registerPending = false;
      if (currentScreen === "racing") renderRacing();
    }, REGISTER_GUARD_MS);
  }
}

// op_id em voo -> { item, finish } (resolve/reject uma única vez).
const pendingOps = new Map();

function buildRegisterItem(type, lane) {
  const opId = newOpId();
  const clientTs = serverNow();
  const verb = type === "finish" ? "finish" : "lap";
  return {
    op_id: opId,
    action: type,
    lane_id: lane.id,
    method: "POST",
    path: `/api/lanes/${lane.id}/${verb}`,
    body: { op_id: opId, client_ts: clientTs },
    client_ts: clientTs,
    ts: Date.now(),
  };
}

function sendRegister(item) {
  // Grava na outbox ANTES de enviar; só sai com ack ou resposta 2xx.
  outboxAdd(item);
  return new Promise((resolve, reject) => {
    const entry = { item, settled: false, timer: null };
    entry.finish = (error, result) => {
      if (entry.settled) return;
      entry.settled = true;
      if (entry.timer) clearTimeout(entry.timer);
      pendingOps.delete(item.op_id);
      if (error) reject(error);
      else resolve(result);
    };
    pendingOps.set(item.op_id, entry);

    const restFallback = () => {
      if (entry.settled) return;
      api(item.method, item.path, item.body)
        .then((result) => {
          outboxRemove(item.op_id);
          entry.finish(null, result);
        })
        .catch((error) => {
          if (isTerminalError(error)) {
            outboxRemove(item.op_id);
            recordRejected(item, error.message);
          }
          entry.finish(error);
        });
    };

    // Sem ack em 3 s: reenvia via REST com o MESMO op_id.
    entry.timer = setTimeout(restFallback, ACK_TIMEOUT_MS);
    const sent = wsSend({
      type: item.action,
      lane_id: item.lane_id,
      op_id: item.op_id,
      client_ts: item.client_ts,
    });
    if (!sent) {
      clearTimeout(entry.timer);
      restFallback();
    }
  });
}

function onWsAck(message) {
  const entry = pendingOps.get(message.op_id);
  if (!entry) return;
  outboxRemove(message.op_id);
  entry.finish(null, message.result);
}

function onWsError(message) {
  const entry = message.op_id ? pendingOps.get(message.op_id) : null;
  if (!entry) {
    onActionError(message.message);
    return;
  }
  if (isTerminalError({ message: message.message })) {
    outboxRemove(message.op_id);
    recordRejected(entry.item, message.message);
  }
  entry.finish(new Error(message.message));
}

async function registerFinish() {
  const lane = currentLane();
  if (!lane || registerPending) return;
  setRegisterPending(true);
  els.fcRegister.textContent = "REGISTRANDO...";
  try {
    const result = await sendRegister(buildRegisterItem("finish", lane));
    applyLaneUpdate(lane, {
      status: "finished",
      finish_at: result.received_at || serverNow(),
      race_time_ms: result.race_time_ms,
      race_time_display: result.race_time_display,
      speed_ms: result.speed_ms,
      team: result.team_name || lane.team,
    });
    setRegisterPending(false);
    applyState({ buzzer: false });
  } catch (error) {
    if (String(error.message).includes("ja_finalizou")) {
      setRegisterPending(false);
      reconcile().catch(() => {});
      return;
    }
    if (isNetworkError(error)) setOffline(true);
    onActionError(error.message);
  }
}

async function registerLap() {
  const lane = currentLane();
  if (!lane || registerPending) return;
  setRegisterPending(true);
  els.fcRegister.textContent = "REGISTRANDO...";
  try {
    const result = await sendRegister(buildRegisterItem("lap", lane));
    const poolLength = eventDetail ? eventDetail.pool_length_m : 0;
    const laps = (lane.laps || 0) + 1;
    applyLaneUpdate(lane, {
      laps,
      meters: laps * poolLength,
      last_lap_at: result.recorded_at,
      status: lane.status === "assigned" || lane.status === "ready" ? "active" : lane.status,
    });
    setRegisterPending(false);
    if (currentScreen === "racing") renderRacing();
  } catch (error) {
    if (isNetworkError(error)) setOffline(true);
    onActionError(error.message);
  }
}

async function undoLap() {
  const lane = currentLane();
  if (!lane) return;
  els.fcUndo.disabled = true;
  try {
    await api("DELETE", `/api/lanes/${lane.id}/lap/last`);
    const poolLength = eventDetail ? eventDetail.pool_length_m : 0;
    const laps = Math.max(0, (lane.laps || 0) - 1);
    applyLaneUpdate(lane, {
      laps,
      meters: laps * poolLength,
      last_lap_at: null,
    });
    renderRacing();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
    renderRacing();
  }
}

function openDqModal() {
  const lane = currentLane();
  els.dqText.textContent = `Confirmar desclassificação de ${lane ? lane.participant_name || "participante" : "participante"}?`;
  els.dqModal.classList.add("open");
}

async function confirmDq() {
  els.dqModal.classList.remove("open");
  const lane = currentLane();
  if (!lane) return;
  try {
    await api("POST", `/api/lanes/${lane.id}/dq`);
    applyLaneUpdate(lane, { status: "dq" });
    applyState({ buzzer: false });
  } catch (error) {
    if (isNetworkError(error)) {
      enqueue({ method: "POST", path: `/api/lanes/${lane.id}/dq` });
    } else {
      showToast(`Erro: ${error.message}`, true);
    }
  }
}

function onActionError(message) {
  setRegisterPending(false);
  if (currentScreen === "racing") renderRacing();
  showToast(`Erro: ${message}`, true);
}

// --------------------------------------------------------------------------- //
// Tela 5 — Finalizado
// --------------------------------------------------------------------------- //
function renderFinished() {
  const lane = currentLane();
  if (!lane) return;
  const dq = lane.status === "dq";
  const maratonaEnd = !dq && lane.finish_at == null;
  els.ffIcon.textContent = dq ? "🚫" : "✅";
  els.ffTitle.innerHTML = dq
    ? "<strong>DESCLASSIFICADO</strong>"
    : "<strong>FINALIZADO</strong>";
  els.ffParticipant.textContent = lane.participant_name || "";
  els.ffTeam.textContent = lane.team || "Sem equipe";
  if (dq) {
    els.ffTime.textContent = "—";
    els.ffSpeed.textContent = "Aguardando encerramento da bateria...";
  } else if (maratonaEnd) {
    els.ffTime.textContent = `${lane.laps} voltas`;
    els.ffSpeed.textContent = `${lane.meters} m`;
  } else {
    els.ffTime.textContent =
      lane.race_time_display || formatTime(lane.race_time_ms);
    els.ffSpeed.textContent =
      lane.speed_ms != null ? `${lane.speed_ms} m/s` : "";
  }

  els.ffLanes.innerHTML = "";
  const lanes = currentHeat.heat_lanes.filter(
    (item) => item.participant_name || item.team_id
  );
  for (const item of lanes) {
    const icon =
      item.status === "finished" ? "✅" : item.status === "dq" ? "🚫" : "⏱";
    const time =
      item.finish_at != null
        ? item.race_time_display || formatTime(item.race_time_ms)
        : item.status === "dq"
          ? "DQ"
          : "em prova...";
    const line = document.createElement("div");
    line.className = "lane-line";
    line.innerHTML = `<span>${icon}</span><span>Raia ${item.lane_number} · ${escapeHtml(item.participant_name || "—")} · ${time}</span>`;
    els.ffLanes.appendChild(line);
  }

  const heatFinished = currentHeat.status === "finished";
  els.ffBanner.hidden = !heatFinished;
  els.ffNext.hidden = !(heatFinished && hasNextBattery());
}

function hasNextBattery() {
  if (!eventDetail || !selection) return false;
  return eventDetail.heats.some(
    (heat) =>
      heat.event_seq > currentHeat.event_seq &&
      heat.status !== "finished" &&
      heat.heat_lanes.some(
        (lane) => lane.lane_number === selection.lane_number && lane.participant_name
      )
  );
}

function nextBattery() {
  if (!eventDetail || !selection) return;
  const heats = heatsSorted(eventDetail.heats);
  const next = heats.find(
    (heat) =>
      heat.event_seq > currentHeat.event_seq && heat.status !== "finished"
  );
  if (!next) return;
  const lane = next.heat_lanes.find(
    (item) => item.lane_number === selection.lane_number && item.participant_name
  );
  if (!lane) {
    showToast("Sem raia correspondente na próxima bateria", true);
    return;
  }
  selection.lane_id = lane.id;
  selection.lane_number = lane.lane_number;
  selection.participant_name = lane.participant_name;
  saveSelection();
  syncSubscription();
  currentHeat = next;
  readyInfo = null;
  applyState({ buzzer: false });
}

// --------------------------------------------------------------------------- //
// WebSocket / reconciliação
// --------------------------------------------------------------------------- //
function onHeatState(heat) {
  if (!selection) return;
  const lane = heat.heat_lanes.find((item) => item.id === selection.lane_id);
  if (!lane) return;
  const previous = currentScreen;
  if (eventDetail) {
    const index = eventDetail.heats.findIndex((item) => item.id === heat.id);
    if (index >= 0) eventDetail.heats[index] = heat;
    else eventDetail.heats.push(heat);
  }
  currentHeat = heat;
  selection.participant_name = lane.participant_name;
  saveSelection();
  // Não libera o botão antes do ack: há um registro em voo.
  if (pendingOps.size === 0) setRegisterPending(false);
  const target = resolveScreen(heat, lane);
  show(target, { buzzer: target === "racing" && previous !== "racing" });
}

async function reconcile(options = {}) {
  const saved = loadSelection();
  if (!saved || !saved.event_id || !saved.lane_id) {
    selection = null;
    syncSubscription();
    show("config");
    await loadEvents();
    return;
  }
  if (reconciling) return;
  reconciling = true;
  try {
    const event = await api("GET", `/api/events/${saved.event_id}`);
    const heat = event.heats.find((item) =>
      item.heat_lanes.some((lane) => lane.id === saved.lane_id)
    );
    if (!heat) {
      clearSelection();
      selection = null;
      syncSubscription();
      currentHeat = null;
      eventDetail = null;
      show("config");
      await loadEvents();
      return;
    }
    const lane = heat.heat_lanes.find((item) => item.id === saved.lane_id);
    selection = {
      event_id: event.id,
      lane_id: lane.id,
      lane_number: lane.lane_number,
      event_name: event.name,
      participant_name: lane.participant_name,
    };
    saveSelection();
    syncSubscription();
    eventDetail = event;
    currentHeat = heat;
    ensureAudio();
    setOffline(false);
    applyState({ buzzer: options.buzzer === true });
  } catch (error) {
    setOffline(true);
    if (!selection) selection = saved;
    syncSubscription();
    show("config");
    await loadEvents();
  } finally {
    reconciling = false;
  }
}

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "ready_update") {
    if (currentHeat && message.heat_id === currentHeat.id) {
      readyInfo = { ...message.payload, heat_id: message.heat_id };
      if (currentScreen === "ready") renderReady();
    }
  } else if (message.type === "heat_state") {
    onHeatState(message.payload);
  } else if (message.type === "ack") {
    onWsAck(message);
  } else if (message.type === "error") {
    onWsError(message);
  }
});

ws.onStatusChange = (connected) => {
  setOffline(!connected);
  if (connected) {
    flushOutbox()
      .then(() => reconcile({ buzzer: false }))
      .catch(() => {});
  }
};

// --------------------------------------------------------------------------- //
// Eventos de UI
// --------------------------------------------------------------------------- //
document.querySelectorAll('[data-action="change-lane"]').forEach((button) => {
  button.addEventListener("click", changeLane);
});

els.fsEvent.addEventListener("change", onConfigEventChange);
els.fsConfirm.addEventListener("click", confirmPosition);
els.fwReady.addEventListener("click", () => actionReady(els.fwReady));
els.fcRegister.addEventListener("click", () => {
  if (!currentHeat) return;
  if (currentHeat.heat_type === "bateria") registerFinish();
  else registerLap();
});
els.fcUndo.addEventListener("click", undoLap);
els.fcDq.addEventListener("click", openDqModal);
els.dqCancel.addEventListener("click", () =>
  els.dqModal.classList.remove("open")
);
els.dqConfirm.addEventListener("click", confirmDq);
els.ffNext.addEventListener("click", nextBattery);
if (els.rejectedClear) {
  els.rejectedClear.addEventListener("click", clearRejected);
}

renderRejected();
const savedSelection = loadSelection();
if (savedSelection && savedSelection.event_id) {
  ws.subscribe(savedSelection.event_id);
}
reconcile().catch(() => {});
ws.connect();
