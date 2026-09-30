const LANE_NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8];
const UNDO_WINDOW_MS = 30000;

const els = {
  badge: document.getElementById("conn-badge"),
  select: document.getElementById("lane-select"),
  title: document.getElementById("lane-title"),
  laps: document.getElementById("lane-laps"),
  detail: document.getElementById("lane-detail"),
  register: document.getElementById("btn-register"),
  undo: document.getElementById("btn-undo"),
  counters: document.getElementById("counters"),
};

let latestState = null;
let selectedNumber = Number(localStorage.getItem("fiscal_lane") || 1);
let previousStatus = null;
let clockAnchor = { at: Date.now(), elapsed: 0 };

for (const number of LANE_NUMBERS) {
  const option = document.createElement("option");
  option.value = String(number);
  option.textContent = `Raia ${number}`;
  els.select.appendChild(option);
}
els.select.value = String(selectedNumber);

function eventType() {
  if (!latestState || !latestState.competition) return "maratona";
  return latestState.competition.event_type || "maratona";
}

function findLane() {
  if (!latestState || !latestState.lanes) return null;
  return latestState.lanes.find((lane) => lane.number === selectedNumber) || null;
}

function currentElapsed() {
  const competition = latestState && latestState.competition;
  if (!competition) return 0;
  if (competition.status === "finished" && competition.finished_at && competition.started_at) {
    return competition.finished_at - competition.started_at;
  }
  if (competition.status !== "active") return 0;
  return clockAnchor.elapsed + (Date.now() - clockAnchor.at) / 1000;
}

function renderSelectOptions() {
  const lanes = (latestState && latestState.lanes) || [];
  const current = els.select.value;
  const battery = eventType() === "bateria";
  els.select.innerHTML = "";
  for (const number of LANE_NUMBERS) {
    const lane = lanes.find((item) => item.number === number);
    let label = `Raia ${number}`;
    if (lane && battery && lane.participant_name) {
      label += ` — ${lane.participant_name}`;
    } else if (lane && lane.team) {
      label += ` — ${lane.team}`;
    }
    const option = document.createElement("option");
    option.value = String(number);
    option.textContent = label;
    els.select.appendChild(option);
  }
  els.select.value = current || String(selectedNumber);
}

function renderMaratonaLane() {
  els.undo.style.display = "";
  els.register.textContent = "REGISTRAR";

  const lane = findLane();
  if (!latestState || !latestState.competition) {
    els.title.textContent = `Raia ${selectedNumber}`;
    els.laps.textContent = "0";
    els.detail.textContent = "Aguardando competição";
    els.register.disabled = true;
    els.undo.disabled = true;
    return;
  }
  if (!lane) {
    els.title.textContent = `Raia ${selectedNumber}`;
    els.laps.textContent = "0";
    els.detail.textContent = "Raia sem equipe";
    els.register.disabled = true;
    els.undo.disabled = true;
    return;
  }

  els.title.textContent = `Raia ${lane.number} · ${lane.team || "Sem equipe"}`;
  els.laps.textContent = `${lane.laps} voltas`;
  els.detail.textContent = `${lane.meters} m · status: ${lane.status}`;

  const last = lane.last_lap_at;
  const canUndo =
    last != null && Date.now() - last * 1000 < UNDO_WINDOW_MS && lane.laps > 0;
  els.undo.disabled = !canUndo;
  els.register.disabled = !lane.team;
}

function renderBateriaLane() {
  els.undo.style.display = "none";

  const competition = latestState && latestState.competition;
  const lane = findLane();

  if (!competition) {
    els.title.textContent = `Raia ${selectedNumber}`;
    els.laps.textContent = "00:00.0";
    els.detail.textContent = "Aguardando competição";
    els.register.disabled = true;
    els.register.textContent = "AGUARDANDO";
    return;
  }
  if (!lane || !lane.participant_name) {
    els.title.textContent = `Raia ${selectedNumber}`;
    els.laps.textContent = "00:00.0";
    els.detail.textContent = "Raia sem participante";
    els.register.disabled = true;
    els.register.textContent = "AGUARDANDO";
    return;
  }

  els.title.textContent = `Raia ${lane.number} · ${lane.participant_name}`;
  els.detail.textContent = lane.team || "Sem equipe";

  if (lane.finish_at) {
    els.laps.textContent = formatRaceTime(lane.race_time_ms);
    els.detail.textContent = `${lane.team || "Sem equipe"} · ${lane.speed_ms} m/s`;
    els.register.disabled = true;
    els.register.textContent = "✅ FINALIZADO";
    return;
  }

  if (competition.status !== "active") {
    els.laps.textContent = "00:00.0";
    els.register.disabled = true;
    els.register.textContent = "Aguardando disparo...";
    return;
  }

  els.laps.textContent = formatTenths(currentElapsed());
  els.register.disabled = false;
  els.register.textContent = "✋ REGISTRAR CHEGADA";
}

function renderLaneCard() {
  if (eventType() === "bateria") {
    renderBateriaLane();
  } else {
    renderMaratonaLane();
  }
}

function renderCounters() {
  els.counters.innerHTML = "";
  if (!latestState || !latestState.competition) {
    els.counters.innerHTML = '<p class="muted">Sem competição ativa.</p>';
    return;
  }

  if (eventType() === "bateria") {
    const participants = latestState.lanes.filter((lane) => lane.participant_name);
    if (!participants.length) {
      els.counters.innerHTML = '<p class="muted">Nenhum participante.</p>';
      return;
    }
    const finished = participants
      .filter((lane) => lane.finish_at)
      .sort((a, b) => a.race_time_ms - b.race_time_ms);
    const running = participants.filter((lane) => !lane.finish_at);
    for (const lane of [...finished, ...running]) {
      const item = document.createElement("div");
      item.className = "list-item";
      const time = lane.finish_at ? formatRaceTime(lane.race_time_ms) : "⏱ em prova";
      item.innerHTML = `
        <span>${lane.participant_name} <span class="rank-lane">· raia ${lane.number}</span></span>
        <span><strong>${time}</strong></span>
      `;
      els.counters.appendChild(item);
    }
    return;
  }

  const ordered = [...latestState.lanes].sort((a, b) => b.laps - a.laps);
  for (const lane of ordered) {
    const item = document.createElement("div");
    item.className = "list-item";
    item.innerHTML = `
      <span>${lane.team || "Sem equipe"} <span class="rank-lane">· raia ${lane.number}</span></span>
      <span><strong>${lane.laps}</strong> <span class="muted">(${lane.meters} m)</span></span>
    `;
    els.counters.appendChild(item);
  }
}

function applyState(state) {
  const newStatus = state.competition ? state.competition.status : null;
  if (
    previousStatus === "draft" &&
    newStatus === "active" &&
    state.competition &&
    state.competition.event_type === "bateria"
  ) {
    tocarBuzzer();
  }
  previousStatus = newStatus;

  latestState = state;
  if (state.timer) {
    clockAnchor = { at: Date.now(), elapsed: state.timer.elapsed_s || 0 };
  }
  renderSelectOptions();
  renderLaneCard();
  renderCounters();
}

function registerLap() {
  const lane = findLane();
  if (!lane) {
    showToast("Raia sem equipe vinculada", true);
    return;
  }
  if (!ws.send({ type: "lap", lane_id: lane.id })) {
    showToast("Sem conexão com o servidor", true);
    return;
  }
  els.register.classList.remove("flash");
  void els.register.offsetWidth;
  els.register.classList.add("flash");
}

function registerFinish() {
  const lane = findLane();
  if (!lane) {
    showToast("Raia sem participante", true);
    return;
  }
  if (!ws.send({ type: "finish", lane_id: lane.id })) {
    showToast("Sem conexão com o servidor", true);
    return;
  }
  els.register.disabled = true;
  els.register.textContent = "✅ FINALIZADO";
}

function onRegister() {
  if (eventType() === "bateria") {
    registerFinish();
  } else {
    registerLap();
  }
}

function undoLap() {
  const lane = findLane();
  if (!lane) return;
  if (!ws.send({ type: "undo", lane_id: lane.id })) {
    showToast("Sem conexão com o servidor", true);
  }
}

function tocarBuzzer() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.8, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 1.2);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 1.2);
  } catch (error) {
    /* áudio indisponível */
  }
}

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "state") {
    applyState(message);
  } else if (message.type === "lap") {
    showToast(`Chegada registrada na raia ${message.lane_number}`);
  } else if (message.type === "error") {
    showToast(`Erro: ${message.message}`, true);
  }
});

ws.onStatusChange = (connected) => {
  els.badge.classList.toggle("online", connected);
  els.badge.classList.toggle("offline", !connected);
  els.badge.textContent = connected ? "online" : "offline";
  renderLaneCard();
};

els.select.addEventListener("change", () => {
  selectedNumber = Number(els.select.value);
  localStorage.setItem("fiscal_lane", String(selectedNumber));
  renderLaneCard();
});

els.register.addEventListener("click", onRegister);
els.undo.addEventListener("click", undoLap);

setInterval(renderLaneCard, 100);
ws.connect();
