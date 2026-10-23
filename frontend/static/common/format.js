export function formatClock(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${secs}`;
}

export function formatRaceTime(ms) {
  const value = Math.max(0, Math.floor(ms || 0));
  const minutes = String(Math.floor(value / 60000)).padStart(2, "0");
  const seconds = String(Math.floor((value % 60000) / 1000)).padStart(2, "0");
  const centis = String(Math.floor((value % 1000) / 10)).padStart(2, "0");
  return `${minutes}:${seconds}.${centis}`;
}

export function formatTenths(totalSeconds) {
  const value = Math.max(0, totalSeconds || 0);
  const minutes = String(Math.floor(value / 60)).padStart(2, "0");
  const seconds = String(Math.floor(value % 60)).padStart(2, "0");
  const tenths = Math.floor((value % 1) * 10);
  return `${minutes}:${seconds}.${tenths}`;
}

export function formatTime(ms) {
  const value = Math.max(0, Math.floor(ms || 0));
  const minutes = String(Math.floor(value / 60000)).padStart(2, "0");
  const seconds = String(Math.floor((value % 60000) / 1000)).padStart(2, "0");
  const centis = String(Math.floor((value % 1000) / 10)).padStart(2, "0");
  return `${minutes}:${seconds}.${centis}`;
}

export function formatSpeed(distance_m, race_time_ms) {
  if (!distance_m || !race_time_ms || race_time_ms <= 0) return "—";
  return `${(distance_m / (race_time_ms / 1000)).toFixed(2)} m/s`;
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${hours}h${String(minutes).padStart(2, "0")}min`;
}

export function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
