const els = {
  badge: document.getElementById("conn-badge"),
  dot: document.getElementById("server-dot"),
  state: document.getElementById("server-state"),
  uptime: document.getElementById("server-uptime"),
  terminalCount: document.getElementById("terminal-count"),
  terminalNote: document.getElementById("terminal-note"),
  running: document.getElementById("running-list"),
  eventList: document.getElementById("event-list"),
  newEvent: document.getElementById("btn-new-event"),
};

let events = [];
let serverStatus = { connected: 0, active_heats: 0, uptime: 0 };
let wsConnected = false;

function formatUptime(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total <= 0) return "iniciando...";
  if (total >= 3600) {
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    return `${hours}h ${minutes}min rodando`;
  }
  if (total >= 60) {
    return `${Math.floor(total / 60)}min rodando`;
  }
  return `${total}s rodando`;
}

function allHeats() {
  const heats = [];
  for (const event of events) {
    for (const heat of event.heats) heats.push({ event, heat });
  }
  return heats;
}

function elapsedSeconds(heat) {
  if (!heat || !heat.started_at) return 0;
  const end = heat.finished_at || Date.now() / 1000;
  return Math.max(0, end - heat.started_at);
}

function renderServer() {
  const online = wsConnected;
  els.dot.classList.toggle("online", online);
  els.dot.classList.toggle("offline", !online);
  els.state.textContent = online ? "online" : "offline";
  els.badge.classList.toggle("online", online);
  els.badge.classList.toggle("offline", !online);
  els.badge.textContent = online ? "online" : "offline";
  els.uptime.textContent = formatUptime(serverStatus.uptime);
}

function renderTerminals() {
  const count = serverStatus.connected || 0;
  els.terminalCount.textContent = String(count);
  els.terminalNote.textContent =
    count <= 0 ? "Nenhum terminal além deste" : pluralize(count, "terminal conectado", "terminais conectados");
}

function renderRunning() {
  const active = allHeats().filter((item) => item.heat.status === "active");
  if (!active.length) {
    els.running.innerHTML = '<p class="muted">Nenhuma bateria em andamento</p>';
    return;
  }
  els.running.innerHTML = "";
  for (const { event, heat } of active) {
    const seconds = elapsedSeconds(heat);
    const clock = heat.heat_type === "bateria" ? formatTenths(seconds) : formatClock(seconds);
    const item = document.createElement("div");
    item.className = "running-item";
    item.innerHTML = `
      <span>
        <strong>${escapeHtml(event.name)}</strong><br />
        <span class="muted">${escapeHtml(heat.name)}</span>
      </span>
      <span class="timer">${clock}</span>
    `;
    els.running.appendChild(item);
  }
}

function renderEvents() {
  els.eventList.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = `
      <p>Nenhum evento criado</p>
      <button class="primary" id="btn-first-event">Criar primeiro evento</button>
    `;
    els.eventList.appendChild(empty);
    document.getElementById("btn-first-event").addEventListener("click", createEvent);
    return;
  }

  for (const event of events) {
    const card = document.createElement("div");
    card.className = "event-card";
    const heatCount = event.heats.length;
    const info = `Piscina ${event.pool_length_m}m · ${pluralize(heatCount, "bateria")}`;
    const dateLine = event.date ? `<div class="event-card-info">📅 ${escapeHtml(event.date)}</div>` : "";
    const deleteButton =
      event.status === "draft"
        ? `<button class="danger" data-delete="${event.id}">🗑</button>`
        : "";
    card.innerHTML = `
      <div class="event-card-head">
        <h3>${escapeHtml(event.name)}</h3>
        <span class="status-pill ${event.status}">${statusLabel(event.status)}</span>
      </div>
      <div class="event-card-info">${info}</div>
      ${dateLine}
      <div class="event-actions">
        <a href="gestao.html?event=${event.id}">⚙️ Gestão</a>
        <a href="supervisor.html?event=${event.id}">👁 Supervisor</a>
        <a href="publico.html?event=${event.id}">📺 Público</a>
        ${deleteButton}
      </div>
    `;
    els.eventList.appendChild(card);
  }

  els.eventList.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteEvent(button.dataset.delete));
  });
}

function render() {
  renderServer();
  renderTerminals();
  renderRunning();
  renderEvents();
}

async function loadEvents() {
  events = await api("GET", "/api/events");
  render();
}

async function loadStatus() {
  try {
    const status = await api("GET", "/api/status");
    serverStatus.uptime = status.uptime;
    serverStatus.active_heats = status.active_heats;
    if (!wsConnected) serverStatus.connected = status.connected_clients;
    renderServer();
    renderTerminals();
  } catch (error) {
    /* silencioso no polling */
  }
}

async function createEvent() {
  try {
    const event = await api("POST", "/api/events", {
      name: "Novo Evento",
      pool_length_m: 25,
    });
    window.location.href = `gestao.html?event=${event.id}`;
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

async function deleteEvent(eventId) {
  const event = events.find((item) => item.id === eventId);
  const name = event ? event.name : "este evento";
  if (!window.confirm(`Excluir "${name}"? Esta ação não pode ser desfeita.`)) return;
  try {
    await api("DELETE", `/api/events/${eventId}`);
    await loadEvents();
    showToast("Evento excluído");
  } catch (error) {
    showToast(`Erro: ${error.message}`, true);
  }
}

function upsertHeat(heat) {
  const event = events.find((item) => item.id === heat.event_id);
  if (!event) {
    loadEvents().catch(() => {});
    return;
  }
  const index = event.heats.findIndex((item) => item.id === heat.id);
  if (index >= 0) event.heats[index] = heat;
  else event.heats.push(heat);
}

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "server_status") {
    serverStatus.connected = message.payload.connected;
    serverStatus.active_heats = message.payload.active_heats;
    renderTerminals();
  } else if (message.type === "heat_state") {
    upsertHeat(message.payload);
    renderRunning();
    renderEvents();
  }
});

ws.onStatusChange = (connected) => {
  wsConnected = connected;
  renderServer();
  if (connected) loadStatus();
};

els.newEvent.addEventListener("click", createEvent);

setInterval(renderRunning, 1000);
setInterval(loadStatus, 15000);

loadEvents().catch((error) => {
  els.eventList.innerHTML = `<p class="muted">Erro: ${escapeHtml(error.message)}</p>`;
});
loadStatus();
ws.connect();
