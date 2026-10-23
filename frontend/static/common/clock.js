const _clockState = { offset: 0, synced: false };
let _clockSyncing = false;

export function serverNow() {
  return Date.now() / 1000 + _clockState.offset;
}

async function _timeSample() {
  const t0 = Date.now();
  const response = await fetch("/api/time", { cache: "no-store" });
  const t1 = Date.now();
  if (!response.ok) throw new Error("time_sync_failed");
  const body = await response.json();
  const offset =
    typeof ClockLogic !== "undefined"
      ? ClockLogic.sampleOffset(body.now, t0, t1)
      : body.now - (t0 + t1) / 2000;
  return { rtt: t1 - t0, offset };
}

export async function syncServerClock() {
  if (_clockSyncing) return;
  _clockSyncing = true;
  try {
    const samples = [];
    for (let index = 0; index < 3; index += 1) {
      try {
        samples.push(await _timeSample());
      } catch (error) {
        /* amostra falhou: tenta a próxima */
      }
    }
    let best = null;
    if (typeof ClockLogic !== "undefined") {
      best = ClockLogic.pickBestSample(samples);
    } else if (samples.length) {
      best = samples.reduce((a, b) => (b.rtt < a.rtt ? b : a));
    }
    if (best) {
      _clockState.offset = best.offset;
      _clockState.synced = true;
    }
  } finally {
    _clockSyncing = false;
  }
}

setInterval(() => {
  syncServerClock();
}, 30000);
syncServerClock();
