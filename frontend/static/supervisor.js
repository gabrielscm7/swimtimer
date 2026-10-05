const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");
if (!eventId) {
  window.location.replace("index.html");
}

const els = {
  eventName: document.getElementById("sup-event-name"),
  eventStatus: document.getElementById("sup-event-status"),
  dot: document.getElementById("sup-dot"),
  terminals: document.getElementById("sup-terminals"),
  left: document.getElementById("sup-left"),
  right: document.getElementById("sup-right"),
  heats: document.getElementById("sup-heats"),
  rightToggle: document.getElementById("sup-right-toggle"),
};

let eventData = null;
let currentHeatId = null;
let readyInfo = null;
let connected = 0;
let timerInterval = null;
let audioCtx = null;
let emergencyOpen = false;
const expandedHeats = new Set();
const marathonFinished = new Set();

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
function sortedHeats() {
  if (!eventData) return [];
  return [...eventData.heats].sort((a, b) => a.order_num - b.order_num);
}

function currentHeat() {
  if (!eventData || !currentHeatId) return null;
  return eventData.heats.find((heat) => heat.id === currentHeatId) || null;
}

function participantLanes(heat) {
  return heat.heat_lanes
    .filter((lane) => lane.participant_name || lane.team_id)
    .sort((a, b) => a.lane_number - b.lane_number);
}

function modeOf(heat) {
  if (!heat) return 5;
  if (heat.status === "finished") return 4;
  if (heat.status === "active") return 3;
  if (heat.status === "ready_check") return 2;
  return 1;
}

function formatMMSS(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function heatDistance(heat) {
  if (heat.heat_type === "bateria") return `${heat.distance_m}m`;
  return formatDuration(heat.duration_s || 0);
}

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

async function loadEvent() {
  eventData = await api("GET", `/api/events/${eventId}`);
  pickCurrentHeat();
  renderAll();
}

function pickCurrentHeat() {
  const heats = sortedHeats();
  const chosen =
    heats.find((heat) => heat.status === "active") ||
    heats.find((heat) => heat.status === "ready_check") ||
    heats.find((heat) => heat.status === "scheduled") ||
    null;
  currentHeatId = chosen ? chosen.id : null;
}

function applyHeatPayload(heat) {
  if (!eventData) return;
  const index = eventData.heats.findIndex((item) => item.id === heat.id);
  if (index >= 0) eventData.heats[index] = heat;
}

async function refreshEvent() {
  try {
    eventData = await api("GET", `/api/events/${eventId}`);
    if (currentHeatId && !eventData.heats.some((h) => h.id === currentHeatId)) {
      currentHeatId = null;
    }
    renderAll();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

// --------------------------------------------------------------------------- //
// Render
// --------------------------------------------------------------------------- //
function renderAll() {
  renderHeader();
  renderLeft();
  renderRight();
}

function renderHeader() {
  if (eventData) {
    els.eventName.textContent = eventData.name;
    els.eventStatus.textContent = statusLabel(eventData.status);
    els.eventStatus.className = `status-pill ${eventData.status}`;
  }
  els.terminals.textContent = pluralize(
    connected,
    "terminal online",
    "terminais online"
  );
}

function renderLeft() {
  stopTimer();
  const heat = currentHeat();
  const mode = modeOf(heat);
  if (mode === 1) els.left.innerHTML = modeScheduled(heat);
  else if (mode === 2) els.left.innerHTML = modeReady(heat);
  else if (mode === 3) els.left.innerHTML = modeActive(heat);
  else if (mode === 4) els.left.innerHTML = modeFinished(heat);
  else els.left.innerHTML = modeEventEnded();
  if (mode === 3) startTimer();
  if (mode === 3) updateClock();
}

function modeScheduled(heat) {
  const lanes = participantLanes(heat);
  const button =
    heat.heat_type === "maratona"
      ? `<button class="sup-btn sup-btn-green sup-btn-start" data-act="start">🚀 INICIAR PROVA</button>`
      : `<button class="sup-btn sup-btn-blue" data-act="open-ready-check">▶ ABRIR READY CHECK</button>`;
  return `
    <div class="sup-card">
      <h2>Próxima bateria</h2>
      <div style="font-size:1.2rem;font-weight:700">${escapeHtml(heat.name)}</div>
      <div class="muted" style="margin-top:4px">${heatTypeLabel(heat)}</div>
      <div class="muted" style="margin-top:4px">${pluralize(lanes.length, "participante")} em ${pluralize(lanes.length, "raia")}</div>
    </div>
    ${button}
  `;
}

function readySet(heat) {
  if (readyInfo && readyInfo.heat_id === heat.id) {
    return new Set(readyInfo.lanes_ready);
  }
  return new Set(
    participantLanes(heat)
      .filter((lane) => lane.status === "ready")
      .map((lane) => lane.lane_number)
  );
}

function modeReady(heat) {
  const lanes = participantLanes(heat);
  const ready = readySet(heat);
  const pending = lanes.filter((lane) => !ready.has(lane.lane_number));
  const allReady = lanes.length > 0 && pending.length === 0;
  const lines = lanes
    .map((lane) => {
      const isReady = ready.has(lane.lane_number);
      return `
        <div class="sup-lane-line">
          <span>${isReady ? "🟢" : "🔴"}</span>
          <span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")} · ${escapeHtml(lane.team || "sem equipe")}</span>
        </div>`;
    })
    .join("");
  const title = pending.length
    ? `Aguardando: ${pending.map((lane) => `Raia ${lane.lane_number}`).join(", ")}`
    : "";
  return `
    <div class="sup-card">
      <h2>Verificação de fiscais</h2>
      <div class="muted" style="margin-bottom:8px">Aguardando confirmação</div>
      ${lines || '<p class="muted">Nenhuma raia configurada.</p>'}
      <div class="muted" style="margin-top:8px">${ready.size} de ${lanes.length} confirmados</div>
    </div>
    <button class="sup-btn sup-btn-green sup-btn-start" data-act="start"
      ${allReady ? "" : "disabled"} title="${escapeHtml(title)}">
      🚀 INICIAR PROVA
    </button>
    <button class="sup-btn sup-btn-ghost" data-act="abort">← Cancelar ready check</button>
  `;
}

function laneLineActive(heat, lane) {
  if (heat.heat_type === "maratona") {
    if (lane.status === "dq") return `<div class="sup-lane-line"><span>🚫</span><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")} · DQ</span></div>`;
    return `<div class="sup-lane-line"><span>⏱</span><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")} · ${lane.laps} voltas · ${lane.meters}m</span></div>`;
  }
  if (lane.finish_at != null) {
    return `<div class="sup-lane-line"><span>✅</span><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")}</span><span class="time">${lane.race_time_display || formatTime(lane.race_time_ms)} · ${lane.speed_ms != null ? lane.speed_ms + " m/s" : "—"}</span></div>`;
  }
  if (lane.status === "dq") {
    return `<div class="sup-lane-line"><span>🚫</span><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")} · DQ</span></div>`;
  }
  return `<div class="sup-lane-line"><span>⏱</span><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")} · em prova...</span></div>`;
}

function modeActive(heat) {
  const lanes = participantLanes(heat);
  const ended = lanes.filter(
    (lane) => lane.finish_at != null || lane.status === "dq"
  );
  const acting = lanes.filter(
    (lane) => lane.finish_at == null && lane.status !== "dq"
  );
  const dqButtons = acting
    .map(
      (lane) =>
        `<button class="sup-btn sup-btn-ghost" data-act="dq" data-lane="${lane.id}" data-number="${lane.lane_number}">🚫 DQ Raia ${lane.lane_number}</button>`
    )
    .join("");
  return `
    <div class="sup-card">
      <h2>Em andamento</h2>
      <div style="font-size:1.25rem;font-weight:700">${escapeHtml(heat.name)}</div>
      <div class="sup-clock" id="sup-clock">00:00.0</div>
    </div>
    <div class="sup-card">
      ${lanes.map((lane) => laneLineActive(heat, lane)).join("") || '<p class="muted">Nenhuma raia.</p>'}
    </div>
    <button class="sup-btn sup-btn-ghost" data-act="emergency-toggle">
      ⚠️ Ações de emergência ${emergencyOpen ? "▲" : "▼"}
    </button>
    <div id="sup-emergency" ${emergencyOpen ? "" : "hidden"}>
      ${dqButtons}
      <button class="sup-btn sup-btn-ghost" data-act="finish-heat" style="color:#f87171;border-color:rgba(239,68,68,.6)">
        ⏹ Encerrar bateria manualmente
      </button>
    </div>
  `;
}

function modeFinished(heat) {
  const lanes = participantLanes(heat);
  const finished = lanes
    .filter((lane) => lane.finish_at != null)
    .sort((a, b) => a.race_time_ms - b.race_time_ms);
  const others = lanes.filter((lane) => lane.finish_at == null);
  const rows = [...finished, ...others]
    .map((lane, index) => {
      const position = lane.finish_at != null ? `${index + 1}º` : "—";
      const time =
        lane.finish_at != null
          ? lane.race_time_display || formatTime(lane.race_time_ms)
          : lane.status === "dq"
            ? "DQ"
            : "—";
      const speed =
        lane.finish_at != null && lane.speed_ms != null
          ? `${lane.speed_ms} m/s`
          : "—";
      return `<tr><td>${position}</td><td>${escapeHtml(lane.participant_name || "—")}</td><td class="muted">${escapeHtml(lane.team || "—")}</td><td class="time">${time}</td><td class="muted">${speed}</td></tr>`;
    })
    .join("");
  const duration =
    heat.finished_at && heat.started_at
      ? formatMMSS(heat.finished_at - heat.started_at)
      : "—";
  const next = nextHeat();
  return `
    <div class="sup-card">
      <h2>🏁 Bateria encerrada</h2>
      <table class="sup-table">
        <thead><tr><th>Pos</th><th>Nome</th><th>Equipe</th><th>Tempo</th><th>Velocidade</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="muted">Sem participantes.</td></tr>'}</tbody>
      </table>
      <div class="muted" style="margin-top:10px">Bateria concluída em ${duration}</div>
    </div>
    <button class="sup-btn sup-btn-green" data-act="next-heat">
      ${next ? "▶ Próxima bateria" : "🏆 Ver evento encerrado"}
    </button>
  `;
}

function nextHeat() {
  const heat = currentHeat();
  if (!heat) return null;
  return (
    sortedHeats().find(
      (item) => item.order_num > heat.order_num && item.status !== "finished"
    ) || null
  );
}

function modeEventEnded() {
  const finished = sortedHeats().filter((heat) => heat.status === "finished");
  const summary = finished
    .map((heat) => {
      const lanes = participantLanes(heat);
      let winner = null;
      if (heat.heat_type === "maratona") {
        winner = [...lanes].sort((a, b) => b.laps - a.laps)[0] || null;
      } else {
        winner =
          lanes
            .filter((lane) => lane.finish_at != null)
            .sort((a, b) => a.race_time_ms - b.race_time_ms)[0] || null;
      }
      if (!winner) return "";
      const result =
        heat.heat_type === "maratona"
          ? `${winner.laps} voltas`
          : winner.race_time_display || formatTime(winner.race_time_ms);
      return `<div class="sup-lane-mini"><span class="spacer">${heat.order_num}. ${escapeHtml(heat.name)}</span><span>${escapeHtml(winner.participant_name || "—")} · ${result}</span></div>`;
    })
    .join("");
  return `
    <div class="sup-card center">
      <div style="font-size:3rem">🏆</div>
      <h2 style="color:var(--text)">Evento encerrado</h2>
      ${
        finished.length
          ? `<div style="text-align:left;margin-top:12px">${summary}</div>`
          : '<p class="muted">Nenhuma bateria finalizada.</p>'
      }
    </div>
    <a class="sup-btn sup-btn-ghost" style="display:block;text-align:center;text-decoration:none;padding:16px" href="index.html">← Voltar para Home</a>
  `;
}

function renderRight() {
  if (!eventData) {
    els.heats.innerHTML = "";
    return;
  }
  els.heats.innerHTML = sortedHeats()
    .map(heatCard)
    .join("");
}

function heatCard(heat) {
  const isCurrent = heat.id === currentHeatId;
  const expanded = isCurrent || expandedHeats.has(heat.id);
  let body = "";
  if (heat.status === "finished") {
    const finished = participantLanes(heat)
      .filter((lane) => lane.finish_at != null)
      .sort((a, b) => a.race_time_ms - b.race_time_ms);
    const rows = finished
      .map(
        (lane, index) =>
          `<tr><td>${index + 1}º</td><td>${escapeHtml(lane.participant_name || "—")}</td><td class="time">${lane.race_time_display || formatTime(lane.race_time_ms)}</td></tr>`
      )
      .join("");
    body = `<table class="sup-table"><thead><tr><th>Pos</th><th>Nome</th><th>Tempo</th></tr></thead><tbody>${rows || '<tr><td colspan="3" class="muted">—</td></tr>'}</tbody></table>`;
  } else if (heat.status === "active") {
    const lanes = participantLanes(heat);
    body = `<p class="muted">Em andamento...</p>${lanes
      .map((lane) => {
        const detail =
          heat.heat_type === "maratona"
            ? `${lane.laps} voltas · ${lane.meters}m`
            : lane.finish_at != null
              ? `${lane.race_time_display || formatTime(lane.race_time_ms)}`
              : lane.status === "dq"
                ? "DQ"
                : "em prova...";
        return `<div class="sup-lane-mini"><span class="spacer">Raia ${lane.lane_number} · ${escapeHtml(lane.participant_name || "—")}</span><span>${detail}</span></div>`;
      })
      .join("")}`;
  } else {
    const lanes = participantLanes(heat);
    body = lanes.length
      ? lanes
          .map(
            (lane) =>
              `<div class="sup-lane-mini"><span class="spacer">Raia ${lane.lane_number}: ${escapeHtml(lane.participant_name || "—")}</span><span class="muted">${escapeHtml(lane.team || "sem equipe")}</span></div>`
          )
          .join("")
      : '<p class="muted">Sem participantes.</p>';
  }
  const activeClass = heat.status === "active" ? "active" : "";
  return `
    <div class="sup-heat-card ${activeClass} ${expanded ? "" : "collapsed"}" data-heat-card="${heat.id}">
      <div class="sup-heat-header" data-heat="${heat.id}">
        <span>${heat.order_num}. ${escapeHtml(heat.name)}</span>
        <span class="spacer"></span>
        <span class="status-pill ${heat.status}">${statusLabel(heat.status)}</span>
        <span class="muted">${expanded ? "▾" : "▸"}</span>
      </div>
      <div class="sup-heat-body">${body}</div>
    </div>`;
}

// --------------------------------------------------------------------------- //
// Timer
// --------------------------------------------------------------------------- //
function startTimer() {
  if (timerInterval) return;
  timerInterval = setInterval(updateClock, 100);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function updateClock() {
  const heat = currentHeat();
  if (!heat || heat.status !== "active") return;
  const clock = document.getElementById("sup-clock");
  if (!clock) return;
  if (!heat.started_at) {
    clock.textContent = "00:00.0";
    return;
  }
  const elapsed = Math.max(0, Date.now() / 1000 - heat.started_at);
  if (heat.heat_type === "maratona") {
    const remaining = Math.max(0, (heat.duration_s || 0) - elapsed);
    clock.textContent = formatClock(remaining);
    if (remaining <= 0 && !marathonFinished.has(heat.id)) {
      marathonFinished.add(heat.id);
      finishHeat(heat.id);
    }
  } else {
    clock.textContent = formatTenths(elapsed);
  }
}

// --------------------------------------------------------------------------- //
// Ações
// --------------------------------------------------------------------------- //
async function withButton(button, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Aguarde...";
  try {
    await fn();
    button.textContent = original;
    button.disabled = false;
  } catch (error) {
    button.textContent = original;
    button.disabled = false;
    showToast(`Erro: ${error.message}`, true);
  }
}

async function openReadyCheck() {
  const heat = currentHeat();
  const result = await api("POST", `/api/heats/${heat.id}/open-ready-check`);
  applyHeatPayload(result);
  renderAll();
}

async function startHeat() {
  const heat = currentHeat();
  tocarBuzzer();
  const result = await api("POST", `/api/heats/${heat.id}/start`);
  applyHeatPayload(result);
  renderAll();
}

async function abortHeat() {
  const heat = currentHeat();
  const result = await api("POST", `/api/heats/${heat.id}/abort`);
  applyHeatPayload(result);
  renderAll();
}

async function finishHeat(heatId) {
  try {
    const result = await api("POST", `/api/heats/${heatId}/finish`);
    applyHeatPayload(result);
    if (heatId === currentHeatId) renderAll();
    else renderRight();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

async function dqLane(laneId, laneNumber) {
  if (!window.confirm(`Confirmar desclassificação da Raia ${laneNumber}?`)) return;
  try {
    await api("POST", `/api/lanes/${laneId}/dq`);
    await refreshEvent();
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

function nextBattery() {
  const next = nextHeat();
  if (!next) {
    currentHeatId = null;
    emergencyOpen = false;
    renderAll();
    return;
  }
  currentHeatId = next.id;
  readyInfo = null;
  emergencyOpen = false;
  renderAll();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// --------------------------------------------------------------------------- //
// Delegação de eventos
// --------------------------------------------------------------------------- //
els.left.addEventListener("click", (event) => {
  const target = event.target.closest("[data-act]");
  if (!target) return;
  const action = target.dataset.act;
  if (action === "open-ready-check") withButton(target, openReadyCheck);
  else if (action === "start") withButton(target, startHeat);
  else if (action === "abort") withButton(target, abortHeat);
  else if (action === "finish-heat") {
    if (window.confirm("Encerrar a bateria antes de todos finalizarem?")) {
      withButton(target, () => finishHeat(currentHeatId));
    }
  } else if (action === "dq") {
    dqLane(target.dataset.lane, target.dataset.number);
  } else if (action === "emergency-toggle") {
    emergencyOpen = !emergencyOpen;
    renderLeft();
  } else if (action === "next-heat") {
    nextBattery();
  }
});

els.heats.addEventListener("click", (event) => {
  const header = event.target.closest("[data-heat]");
  if (!header) return;
  const heatId = header.dataset.heat;
  if (heatId === currentHeatId) return;
  if (expandedHeats.has(heatId)) expandedHeats.delete(heatId);
  else expandedHeats.add(heatId);
  renderRight();
});

els.rightToggle.addEventListener("click", () => {
  els.right.classList.toggle("collapsed");
  els.rightToggle.textContent = els.right.classList.contains("collapsed")
    ? "Ver todas as baterias ▼"
    : "Ocultar baterias ▲";
});

// --------------------------------------------------------------------------- //
// WebSocket
// --------------------------------------------------------------------------- //
const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "ready_update") {
    if (message.heat_id === currentHeatId) {
      readyInfo = { ...message.payload, heat_id: message.heat_id };
      if (modeOf(currentHeat()) === 2) renderLeft();
    }
  } else if (message.type === "heat_state") {
    if (message.payload.status !== "active") {
      marathonFinished.delete(message.payload.id);
    }
    applyHeatPayload(message.payload);
    if (message.payload.id === currentHeatId) renderLeft();
    renderRight();
  } else if (message.type === "server_status") {
    connected = message.payload.connected;
    renderHeader();
  }
});

ws.onStatusChange = (isConnected) => {
  els.dot.classList.toggle("online", isConnected);
  els.dot.classList.toggle("offline", !isConnected);
  if (isConnected) {
    refreshEvent().catch(() => {});
  }
};

async function init() {
  try {
    const status = await api("GET", "/api/status");
    connected = status.connected_clients;
    renderHeader();
  } catch (error) {
    /* ignora */
  }
  try {
    await loadEvent();
  } catch (error) {
    window.location.replace("index.html");
    return;
  }
  ws.connect();
}

init();
