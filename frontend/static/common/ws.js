import { syncServerClock } from "./clock.js";

export class WSClient {
  constructor(url, onMessage) {
    this.url = url;
    this.onMessage = onMessage;
    this.ws = null;
    this.attempts = 0;
    this.onStatusChange = null;
    this._delays = [500, 1000, 2000, 3000, 5000];
    this._reconnectTimer = null;
    this._heartbeat = null;
    this._pongTimer = null;
    this._subscription = null;
  }

  subscribe(eventId, options = {}) {
    if (!eventId) {
      this._subscription = null;
      return false;
    }
    this._subscription = {
      event_id: eventId,
      public: Boolean(options.public),
    };
    return this._sendSubscription();
  }

  _sendSubscription() {
    if (!this._subscription) return false;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({ type: "subscribe", ...this._subscription }));
    return true;
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
    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      this._status(false);
      this._scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      if (this.ws !== socket) return;
      this.attempts = 0;
      syncServerClock();
      this._sendSubscription();
      this._status(true);
      this._startHeartbeat();
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      try {
        const message = JSON.parse(event.data);
        if (message && message.type === "pong") {
          if (this._pongTimer) {
            clearTimeout(this._pongTimer);
            this._pongTimer = null;
          }
          return;
        }
        this.onMessage(message);
      } catch (error) {
        console.error("Mensagem inválida", error);
      }
    };

    socket.onclose = () => {
      if (this.ws !== socket) return;
      this._stopHeartbeat();
      this._status(false);
      this._scheduleReconnect();
    };

    socket.onerror = () => {
      if (this.ws !== socket) return;
      try {
        socket.close();
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

  _startHeartbeat() {
    this._stopHeartbeat();
    this._heartbeat = setInterval(() => this._ping(), 5000);
  }

  _stopHeartbeat() {
    if (this._heartbeat) {
      clearInterval(this._heartbeat);
      this._heartbeat = null;
    }
    if (this._pongTimer) {
      clearTimeout(this._pongTimer);
      this._pongTimer = null;
    }
  }

  _ping() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    // Sem pong em 3 s: fecha o socket; onclose agenda a reconexão.
    if (this._pongTimer) clearTimeout(this._pongTimer);
    this._pongTimer = setTimeout(() => {
      this._pongTimer = null;
      try {
        this.ws.close();
      } catch (error) {
        /* noop */
      }
    }, 3000);
    try {
      this.ws.send(JSON.stringify({ type: "ping" }));
    } catch (error) {
      /* noop */
    }
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

export function wsUrl(path = "/ws") {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${path}`;
}
