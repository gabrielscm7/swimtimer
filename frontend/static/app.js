class WSClient {
  constructor(url, onMessage) {
    this.url = url;
    this.onMessage = onMessage;
    this.ws = null;
    this.attempts = 0;
    this.onStatusChange = null;
    this._delays = [1000, 2000, 4000, 8000, 30000];
    this._reconnectTimer = null;
  }

  connect() {
    // Evita empilhar sockets/timers quando connect() é chamado várias vezes.
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    try {
      this.ws = new WebSocket(this.url);
    } catch (error) {
      this._status(false);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.attempts = 0;
      this._status(true);
    };

    this.ws.onmessage = (event) => {
      try {
        this.onMessage(JSON.parse(event.data));
      } catch (error) {
        console.error("Mensagem inválida", error);
      }
    };

    this.ws.onclose = () => {
      this._status(false);
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      try {
        this.ws.close();
      } catch (error) {
        /* noop */
      }
    };
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    const delay = this._delays[Math.min(this.attempts, this._delays.length - 1)];
    this.attempts += 1;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, delay);
  }

  _status(connected) {
    if (typeof this.onStatusChange === "function") {
      this.onStatusChange(connected);
    }
  }
}

function formatClock(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${secs}`;
}

function formatRaceTime(ms) {
  const value = Math.max(0, Math.floor(ms || 0));
  const minutes = String(Math.floor(value / 60000)).padStart(2, "0");
  const seconds = String(Math.floor((value % 60000) / 1000)).padStart(2, "0");
  const centis = String(Math.floor((value % 1000) / 10)).padStart(2, "0");
  return `${minutes}:${seconds}.${centis}`;
}

function formatTenths(totalSeconds) {
  const value = Math.max(0, totalSeconds || 0);
  const minutes = String(Math.floor(value / 60)).padStart(2, "0");
  const seconds = String(Math.floor(value % 60)).padStart(2, "0");
  const tenths = Math.floor((value * 10) % 10);
  return `${minutes}:${seconds}.${tenths}`;
}

function wsUrl(path = "/ws") {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${path}`;
}

function showToast(message, isError = false) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.remove("show"), 2200);
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (error) {
      /* resposta sem JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (response.status === 204) return null;
  return response.json();
}

function heatLabel(heat) {
  if (!heat) return "—";
  const type = heat.heat_type === "bateria" ? "bateria" : "maratona";
  return `${heat.name} · ${type}#${heat.order_num}`;
}

function formatTime(ms) {
  const value = Math.max(0, Math.floor(ms || 0));
  const minutes = String(Math.floor(value / 60000)).padStart(2, "0");
  const seconds = String(Math.floor((value % 60000) / 1000)).padStart(2, "0");
  const centis = String(Math.floor((value % 1000) / 10)).padStart(2, "0");
  return `${minutes}:${seconds}.${centis}`;
}

function formatSpeed(distance_m, race_time_ms) {
  if (!distance_m || !race_time_ms || race_time_ms <= 0) return "—";
  return `${(distance_m / (race_time_ms / 1000)).toFixed(2)} m/s`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${hours}h${String(minutes).padStart(2, "0")}min`;
}

async function api(method, path, body) {
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined && body !== null) {
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      /* resposta sem JSON */
    }
    const error = new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail)
    );
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

function showFeedback(element, state, message) {
  if (!element) return;
  if (state === "loading") {
    if (!element.dataset.label) element.dataset.label = element.textContent;
    element.classList.remove("success", "error");
    element.classList.add("loading");
    element.disabled = true;
    element.textContent = message || "Salvando...";
    return;
  }
  element.classList.remove("loading");
  element.disabled = false;
  const label = element.dataset.label;
  if (state === "success") {
    element.classList.add("success");
    element.textContent = message || "✓ Salvo";
    setTimeout(() => {
      element.classList.remove("success");
      if (label) element.textContent = label;
    }, 1500);
  } else if (state === "error") {
    element.classList.add("error");
    element.textContent = message || "Erro";
    setTimeout(() => {
      element.classList.remove("error");
      if (label) element.textContent = label;
    }, 2500);
  }
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const STATUS_LABELS = {
  draft: "Rascunho",
  active: "Em andamento",
  finished: "Encerrado",
  scheduled: "Agendada",
  ready_check: "Chamada",
  assigned: "Aguardando",
  ready: "Pronta",
  dq: "DQ",
};

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}

function heatTypeLabel(heat) {
  if (!heat) return "—";
  if (heat.heat_type === "bateria") return `Bateria · ${heat.distance_m}m`;
  return `Maratona · ${formatDuration(heat.duration_s || 0)}`;
}

function pluralize(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural || singular + "s"}`;
}

window.WSClient = WSClient;
window.formatClock = formatClock;
window.formatRaceTime = formatRaceTime;
window.formatTenths = formatTenths;
window.formatTime = formatTime;
window.formatSpeed = formatSpeed;
window.formatDuration = formatDuration;
window.wsUrl = wsUrl;
window.showToast = showToast;
window.apiFetch = apiFetch;
window.api = api;
window.showFeedback = showFeedback;
window.escapeHtml = escapeHtml;
window.statusLabel = statusLabel;
window.heatTypeLabel = heatTypeLabel;
window.heatLabel = heatLabel;
window.pluralize = pluralize;
