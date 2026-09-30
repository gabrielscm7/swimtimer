class WSClient {
  constructor(url, onMessage) {
    this.url = url;
    this.onMessage = onMessage;
    this.ws = null;
    this.attempts = 0;
    this.onStatusChange = null;
    this._delays = [1000, 2000, 4000, 8000, 30000];
  }

  connect() {
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
    const delay = this._delays[Math.min(this.attempts, this._delays.length - 1)];
    this.attempts += 1;
    setTimeout(() => this.connect(), delay);
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

window.WSClient = WSClient;
window.formatClock = formatClock;
window.formatRaceTime = formatRaceTime;
window.formatTenths = formatTenths;
window.wsUrl = wsUrl;
window.showToast = showToast;
