import { api } from "./common/api.js";
import {
  escapeHtml,
  formatClock,
  formatTenths,
  formatTime,
} from "./common/format.js";
import { heatTypeLabel } from "./common/ui.js";
import { serverNow } from "./common/clock.js";
import { WSClient, wsUrl } from "./common/ws.js";

const {
  heatsSorted,
  nextScheduledAfter: nextScheduledAfterSeq,
  lastFinished: lastFinishedSeq,
  nextInProva,
  nextProvaAfter,
  provaHeaderLabel,
} = window.SequenceLogic;
const { displayName } = window.ResultsLogic;

const RESULT_MS = 20000;
const PROVA_RESULT_MS = 30000;

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event");

const els = {
  stage: document.getElementById("pub-stage"),
  overlay: document.getElementById("pub-overlay"),
  dot: document.getElementById("pub-dot"),
  fullscreen: document.getElementById("pub-fullscreen"),
  qr: document.getElementById("pub-qr"),
};

let eventData = null;
let events = [];
let state = 0; // 0 seleção, 1 aguardando, 2 ready, 3 prova, 4 resultado, 5 intervalo, 6 encerrado
let currentHeatId = null;
let resultTimer = null;
let tickInterval = null;
let renderToken = 0;
const classifications = {};
let classificationRequest = null;

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
function heats() {
  if (!eventData) return [];
  return heatsSorted(eventData.heats);
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

function pubName(name) {
  return displayName(name, eventData ? eventData.public_name_mode : "full");
}

function updateQr() {
  if (!els.qr) return;
  if (!eventData || eventData.public_results_enabled === false) {
    els.qr.hidden = true;
    return;
  }
  const url = new URL("resultados.html", window.location.href);
  url.search = `?event=${encodeURIComponent(eventData.id)}`;
  try {
    const qr = qrcode(0, "M");
    qr.addData(url.toString());
    qr.make();
    els.qr.innerHTML = `${qr.createSvgTag({ cellSize: 4, margin: 1 })}<div class="pub-qr-label">Resultados no celular</div>`;
    els.qr.hidden = false;
  } catch (error) {
    els.qr.hidden = true;
  }
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

function logoImg(url, name) {
  if (!url) return "";
  return `<img class="team-logo small" src="${escapeHtml(url)}" alt="${escapeHtml(
    name || "Logo"
  )}" loading="lazy" />`;
}

function classificationRows(standings, excluded) {
  const rows = [];
  for (const entry of standings || []) {
    rows.push(`
      <div class="pub-trow finished">
        <div class="pub-pos ${posClass((entry.position || 1) - 1)}">${entry.position ?? "—"}º${entry.tied ? "=" : ""}</div>
        <div class="pub-name">${escapeHtml(pubName(entry.participant_name) || "—")}</div>
        <div class="pub-team">${logoImg(entry.team_logo_url, entry.team_name)} ${escapeHtml(entry.team_name || "—")}</div>
        <div class="pub-time">${entry.race_time_display || "—"}</div>
      </div>`);
  }
  for (const entry of excluded || []) {
    const label =
      entry.classification_status === "dq"
        ? "DQ"
        : entry.classification_status === "no_time"
          ? "sem tempo"
          : "em andamento";
    rows.push(`
      <div class="pub-trow dq">
        <div class="pub-pos">—</div>
        <div class="pub-name">${escapeHtml(pubName(entry.participant_name) || "—")}</div>
        <div class="pub-team">${logoImg(entry.team_logo_url, entry.team_name)} ${escapeHtml(entry.team_name || "—")}</div>
        <div class="pub-time">${label}</div>
      </div>`);
  }
  return rows.join("");
}

function classificationTable(data) {
  const badge = data.is_provisional ? "provisória" : "definitiva";
  const mode = data.mixed_ranking || "both";
  const section = (title, standings, excluded = []) => `
    <div class="pub-label" style="color:var(--cyan)">${escapeHtml(title)} ${badge}</div>
    <div class="pub-table pub-battery" style="margin-bottom:12px">
      <div class="pub-thead"><div>Pos</div><div>Atleta</div><div>Equipe</div><div style="text-align:right">Tempo</div></div>
      ${classificationRows(standings, excluded) || '<div class="pub-trow"><div class="muted">Sem resultados</div></div>'}
    </div>`;
  const sections = [];
  if (mode !== "by_naipe") {
    sections.push(
      section("Classificação", data.standings || [], data.excluded || [])
    );
  }
  if (mode !== "overall" && data.standings_by_naipe) {
    for (const naipe of ["M", "F"]) {
      sections.push(
        section(
          `Classificação ${naipe === "M" ? "Masculino" : "Feminino"}`,
          data.standings_by_naipe[naipe] || []
        )
      );
    }
  }
  return sections.join("");
}

function allFinished() {
  const list = heats();
  return list.length > 0 && list.every((heat) => heat.status === "finished");
}

function subtitle() {
  const parts = [];
  if (eventData.location) parts.push(eventData.location);
  if (eventData.date) parts.push(eventData.date);
  return parts.join(" · ");
}

function marathonRemaining(heat) {
  if (!heat.started_at) return heat.duration_s || 0;
  return Math.max(0, (heat.duration_s || 0) - (serverNow() - heat.started_at));
}

function posClass(index) {
  if (index === 0) return "gold";
  if (index === 1) return "silver";
  if (index === 2) return "bronze";
  return "";
}

// --------------------------------------------------------------------------- //
// Render / transições
// --------------------------------------------------------------------------- //
function render(html, fade = true) {
  els.stage.classList.toggle("pub-select", state === 0);
  const token = ++renderToken;
  if (!fade) {
    els.stage.style.opacity = "1";
    els.stage.innerHTML = html;
    return;
  }
  els.stage.style.opacity = "0";
  window.setTimeout(() => {
    if (token !== renderToken) return;
    els.stage.innerHTML = html;
    els.stage.style.opacity = "1";
  }, 150);
}

function setState(next, options = {}) {
  const heatId = options.heatId !== undefined ? options.heatId : currentHeatId;
  const same = next === state && heatId === currentHeatId;
  currentHeatId = heatId;
  state = next;
  if (resultTimer) {
    window.clearTimeout(resultTimer);
    resultTimer = null;
  }
  if (next === 4 || next === 7) {
    renderState(true);
    resultTimer = window.setTimeout(() => {
      resultTimer = null;
      if (next === 7) goAfterProvaResult();
      else goAfterResult();
    }, next === 7 ? PROVA_RESULT_MS : RESULT_MS);
    if (next === 7) {
      refreshClassifications().then(() => {
        if (state === 7) renderState(false);
      });
    }
  } else {
    renderState(!same);
  }
  manageTick();
}

function renderState(fade) {
  if (state === 0) render(viewSelection(), fade);
  else if (state === 1) render(viewWaiting(), fade);
  else if (state === 2) render(viewReady(), fade);
  else if (state === 3) render(viewRacing(), fade);
  else if (state === 4) render(viewResult(), fade);
  else if (state === 5) render(viewInterval(), fade);
  else if (state === 6) render(viewEnded(), fade);
  else if (state === 7) render(viewProvaResult(), fade);
}

function goAfterResult() {
  const heat = currentHeat();
  if (!heat) return setState(1, { heatId: null });
  // Ultima bateria da prova: mostra o resultado final da prova antes
  // de seguir para a proxima bateria/prova.
  if (!nextInProva(heats(), heat)) {
    return setState(7, { heatId: heat.id });
  }
  setState(5, { heatId: heat.id });
}

function goAfterProvaResult() {
  const heat = currentHeat();
  const next = heat ? nextScheduledAfter(heat.event_seq) : null;
  if (next) setState(5, { heatId: heat.id });
  else if (allFinished()) setState(6, { heatId: null });
  else setState(1, { heatId: null });
}

function manageTick() {
  if (state === 3 && !tickInterval) {
    tickInterval = window.setInterval(updateTick, 100);
  } else if (state !== 3 && tickInterval) {
    window.clearInterval(tickInterval);
    tickInterval = null;
  }
  if (state === 3) updateTick();
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
// Views
// --------------------------------------------------------------------------- //
function viewSelection() {
  const cards = events
    .map((event) => {
      const info = [
        event.location || null,
        `${event.heats.length} bateria(s)`,
      ]
        .filter(Boolean)
        .join(" · ");
      return `<a class="pub-select-card" href="publico.html?event=${event.id}">${escapeHtml(event.name)}<small>${escapeHtml(info)}</small></a>`;
    })
    .join("");
  return `
    <div class="pub-center">
      <div class="pub-selection">
        <h1 class="pub-event-title">Swim<span style="color:var(--cyan)">Timer</span></h1>
        <div class="pub-subtitle">Selecione o evento para exibir</div>
        ${cards || '<div class="pub-subtitle">Nenhum evento ativo no momento</div>'}
      </div>
    </div>`;
}

function viewWaiting() {
  const upcoming = heats()
    .filter((heat) => heat.status === "scheduled")
    .slice(0, 4)
    .map(
      (heat) =>
        `<div class="pub-up-item"><span class="pub-up-num">${heat.event_seq}</span><span>${escapeHtml(provaHeaderLabel(heat))} <span class="muted">· ${heatTypeLabel(heat)}</span></span></div>`
    )
    .join("");
  return `
    <div class="pub-center">
      <h1 class="pub-event-title">${escapeHtml(eventData.name)}</h1>
      <div class="pub-subtitle">${escapeHtml(subtitle())}</div>
      <div class="pub-upcoming">
        <div class="pub-label">A seguir</div>
        ${upcoming || '<div class="muted" style="font-size:clamp(18px,2vw,30px);padding:12px">Nenhuma bateria agendada</div>'}
      </div>
      <div class="pub-waiting"><span class="dot online"></span> Aguardando início</div>
    </div>`;
}

function viewReady() {
  const heat = currentHeat();
  if (!heat) return viewWaiting();
  const cards = participantLanes(heat)
    .map(
      (lane) => `
      <div class="pub-lane-card">
        <div class="pub-lane-num">RAIA ${lane.lane_number}</div>
        <div class="pub-lane-name">${escapeHtml(pubName(lane.participant_name) || "—")}</div>
        <div class="pub-lane-team">${logoImg(lane.team_logo_url, lane.team)} ${escapeHtml(lane.team || "sem equipe")}</div>
      </div>`
    )
    .join("");
  return `
    <div class="pub-top-event">${escapeHtml(eventData.name)}</div>
    <div class="pub-center">
      <div class="pub-label">A seguir</div>
      <div class="pub-heat-name">${escapeHtml(provaHeaderLabel(heat))}</div>
      <div class="pub-heat-type">${heatTypeLabel(heat)}</div>
      <div class="pub-lane-grid">${cards || '<div class="muted">Sem participantes</div>'}</div>
    </div>
    <div class="pub-footer">Aguardando disparo...</div>`;
}

function viewRacing() {
  const heat = currentHeat();
  if (!heat) return viewWaiting();
  const battery = heat.heat_type === "bateria";
  const clock = battery
    ? `<div class="pub-clock" id="pub-clock">00:00.0</div>`
    : `<div class="pub-clock" id="pub-clock">${formatClock(marathonRemaining(heat))}</div><div class="muted" style="font-size:clamp(14px,1.4vw,22px)">restante</div>`;
  return `
    <div class="pub-racing-top">
      <div class="pub-racing-meta">
        <div class="muted" style="font-size:clamp(14px,1.4vw,22px)">${escapeHtml(eventData.name)}</div>
        <div class="pub-heat-name">${escapeHtml(provaHeaderLabel(heat))}</div>
        <div class="pub-heat-type">${heatTypeLabel(heat)}</div>
      </div>
      <div class="pub-racing-clock">${clock}</div>
    </div>
    <div class="pub-racing-body">${battery ? batteryTable(heat, true) : marathonTable(heat, true)}</div>`;
}

function batteryTable(heat, live) {
  const lanes = participantLanes(heat);
  const finished = lanes
    .filter((lane) => lane.finish_at != null)
    .sort((a, b) => a.race_time_ms - b.race_time_ms);
  const running = lanes.filter(
    (lane) => lane.finish_at == null && lane.status !== "dq"
  );
  const dq = lanes.filter((lane) => lane.status === "dq");

  const rows = [];
  finished.forEach((lane, index) => {
    rows.push(`
      <div class="pub-trow finished">
        <div class="pub-pos ${posClass(index)}">${index + 1}º</div>
        <div class="pub-name">${escapeHtml(pubName(lane.participant_name) || "—")}</div>
        <div class="pub-team">${logoImg(lane.team_logo_url, lane.team)} ${escapeHtml(lane.team || "—")}</div>
        <div class="pub-time">${lane.race_time_display || formatTime(lane.race_time_ms)}</div>
        <div class="pub-speed">${lane.speed_ms != null ? lane.speed_ms + " m/s" : "—"}</div>
      </div>`);
  });
  running.forEach((lane) => {
    rows.push(`
      <div class="pub-trow running">
        <div class="pub-pos">—</div>
        <div class="pub-name">${escapeHtml(pubName(lane.participant_name) || "—")}</div>
        <div class="pub-team">${logoImg(lane.team_logo_url, lane.team)} ${escapeHtml(lane.team || "—")}</div>
        <div class="pub-time">${live ? '<span data-lane-time>00:00.00</span>' : "—"}</div>
        <div class="pub-speed">—</div>
      </div>`);
  });
  dq.forEach((lane) => {
    rows.push(`
      <div class="pub-trow dq">
        <div class="pub-pos">—</div>
        <div class="pub-name">${escapeHtml(pubName(lane.participant_name) || "—")}</div>
        <div class="pub-team">${logoImg(lane.team_logo_url, lane.team)} ${escapeHtml(lane.team || "—")}</div>
        <div class="pub-time"><span class="pub-dq-badge">DQ</span></div>
        <div class="pub-speed">—</div>
      </div>`);
  });
  return `
    <div class="pub-table pub-battery">
      <div class="pub-thead"><div>Pos</div><div>Nome</div><div>Equipe</div><div style="text-align:right">Tempo</div><div style="text-align:right">Vel.</div></div>
      ${rows.join("") || '<div class="pub-trow"><div class="muted">Sem participantes</div></div>'}
    </div>`;
}

function marathonTable(heat, live) {
  const lanes = [...participantLanes(heat)].sort(
    (a, b) => b.laps - a.laps || b.meters - a.meters
  );
  const rows = lanes
    .map(
      (lane, index) => `
      <div class="pub-trow ${lane.status === "dq" ? "dq" : ""}">
        <div class="pub-pos ${posClass(index)}">${lane.status === "dq" ? "—" : index + 1}º</div>
        <div class="pub-name">${escapeHtml(lane.team || pubName(lane.participant_name) || "—")}</div>
        <div class="pub-team">Raia ${lane.lane_number}</div>
        <div class="pub-time">${lane.laps}</div>
        <div class="pub-speed">${lane.meters} m</div>
      </div>`
    )
    .join("");
  return `
    <div class="pub-table pub-marathon">
      <div class="pub-thead"><div>Pos</div><div>Equipe</div><div>Raia</div><div style="text-align:right">Voltas</div><div style="text-align:right">Metros</div></div>
      ${rows || '<div class="pub-trow"><div class="muted">Sem participantes</div></div>'}
    </div>`;
}

function compactTable(heat) {
  const lanes = participantLanes(heat);
  if (heat.heat_type === "maratona") {
    const rows = [...lanes]
      .sort((a, b) => b.laps - a.laps)
      .map(
        (lane, index) =>
          `<div class="pub-trow"><div class="pub-pos ${posClass(index)}">${index + 1}º</div><div class="pub-name">${escapeHtml(lane.team || pubName(lane.participant_name) || "—")}</div><div class="pub-time">${lane.laps}</div></div>`
      )
      .join("");
    return `<div class="pub-table pub-marathon"><div class="pub-thead"><div>Pos</div><div>Equipe</div><div style="text-align:right">Voltas</div></div>${rows}</div>`;
  }
  const finished = lanes
    .filter((lane) => lane.finish_at != null)
    .sort((a, b) => a.race_time_ms - b.race_time_ms);
  const rows = finished
    .map(
      (lane, index) =>
        `<div class="pub-trow finished"><div class="pub-pos ${posClass(index)}">${index + 1}º</div><div class="pub-name">${escapeHtml(pubName(lane.participant_name) || "—")}</div><div class="pub-time">${lane.race_time_display || formatTime(lane.race_time_ms)}</div></div>`
    )
    .join("");
  return `<div class="pub-table pub-battery"><div class="pub-thead"><div>Pos</div><div>Nome</div><div style="text-align:right">Tempo</div></div>${rows || '<div class="pub-trow"><div class="muted">—</div></div>'}</div>`;
}

function podium(heat) {
  const lanes = participantLanes(heat);
  let ranked;
  if (heat.heat_type === "maratona") {
    ranked = [...lanes].sort((a, b) => b.laps - a.laps || b.meters - a.meters);
  } else {
    ranked = lanes
      .filter((lane) => lane.finish_at != null)
      .sort((a, b) => a.race_time_ms - b.race_time_ms);
  }
  if (!ranked.length) return '<div class="pub-subtitle">Sem resultados.</div>';
  const medals = ["🥇", "🥈", "🥉"];
  const top = ranked.slice(0, 3);
  const order = [top[1], top[0], top[2]].filter(Boolean);
  const cards = order
    .map((lane) => {
      const place = top.indexOf(lane) + 1;
      const result =
        heat.heat_type === "maratona"
          ? `${lane.laps} voltas`
          : lane.race_time_display || formatTime(lane.race_time_ms);
      const sub =
        heat.heat_type === "maratona"
          ? `${lane.meters} m`
          : lane.speed_ms != null
            ? `${lane.speed_ms} m/s`
            : "";
      return `
        <div class="pub-podium-card place-${place}">
          <div class="pub-podium-medal">${medals[place - 1]}</div>
          <div class="pub-podium-name">${escapeHtml(pubName(lane.participant_name) || lane.team || "—")}</div>
          <div class="pub-podium-team">${logoImg(lane.team_logo_url, lane.team)} ${escapeHtml(lane.team || "—")}</div>
          <div class="pub-podium-result">${result}</div>
          <div class="pub-podium-team">${sub}</div>
        </div>`;
    })
    .join("");
  return `<div class="pub-podium">${cards}</div>`;
}

function viewResult() {
  const heat = currentHeat();
  if (!heat) return viewWaiting();
  const prova = provaOf(heat);
  const consolidated =
    prova && prova.consolidate_results ? classifications[prova.id] : null;
  return `
    <div class="pub-center" style="justify-content:flex-start;padding-top:12px">
      <div class="pub-label" style="color:var(--cyan)">🏁 Resultado da bateria</div>
      <div class="pub-heat-name">${escapeHtml(provaHeaderLabel(heat))}</div>
      <div class="pub-heat-type">${heatTypeLabel(heat)}</div>
      ${podium(heat)}
      <div class="pub-result-table" style="width:100%;max-width:1100px;margin-top:8px">
        ${compactTable(heat)}
        ${consolidated ? classificationTable(consolidated) : ""}
      </div>
    </div>`;
}

function viewInterval() {
  const heat = currentHeat();
  const inProva = heat ? nextInProva(heats(), heat) : null;
  const nextProva =
    heat && !inProva ? nextProvaAfter(heats(), provasSorted(), heat) : null;
  let nextInfo;
  if (inProva) {
    const lanes = participantLanes(inProva);
    nextInfo = `
      <div class="pub-label">A seguir</div>
      <div class="pub-heat-name">${escapeHtml(provaHeaderLabel(inProva))}</div>
      <div class="pub-heat-type">${heatTypeLabel(inProva)}</div>
      <div style="margin-top:24px">
        ${lanes.map((lane) => `<div class="pub-up-item"><span class="pub-up-num">R${lane.lane_number}</span><span>${escapeHtml(pubName(lane.participant_name) || "—")} <span class="muted">· ${escapeHtml(lane.team || "sem equipe")}</span></span></div>`).join("") || '<div class="muted">Sem participantes</div>'}
      </div>`;
  } else if (nextProva) {
    nextInfo = `
      <div class="pub-label">Próxima prova:</div>
      <div class="pub-heat-name">${escapeHtml(`${nextProva.prova.order_num}. ${nextProva.prova.name}`)}</div>
      <div class="pub-heat-type">${escapeHtml(provaHeaderLabel(nextProva.heat))}</div>`;
  } else {
    nextInfo = '<div class="muted">Nenhuma próxima bateria</div>';
  }
  const prova = heat ? provaOf(heat) : null;
  const partial =
    prova && prova.consolidate_results ? classifications[prova.id] : null;
  return `
    <div class="pub-interval">
      <div class="pub-interval-col">
        <div class="pub-label">Resultado — ${heat ? escapeHtml(provaHeaderLabel(heat)) : ""}</div>
        ${heat ? compactTable(heat) : ""}
        ${partial ? classificationTable(partial) : ""}
      </div>
      <div class="pub-interval-col">${nextInfo}</div>
    </div>`;
}

function viewProvaResult() {
  const heat = currentHeat();
  if (!heat) return viewWaiting();
  const prova = provaOf(heat);
  const data =
    prova && prova.consolidate_results ? classifications[prova.id] : null;
  const meta = prova
    ? [
        prova.naipe === "MISTO" ? "Misto" : "",
        prova.category || "",
        prova.distance_m ? `${prova.distance_m}m` : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  return `
    <div class="pub-center" style="justify-content:flex-start;padding-top:16px">
      <div class="pub-label" style="color:var(--cyan)">🏁 Resultado final da prova</div>
      <div class="pub-heat-name">${escapeHtml(prova ? `${prova.order_num}. ${prova.name}` : heat.prova_name || heat.name)}</div>
      ${meta ? `<div class="pub-heat-type">${escapeHtml(meta)}</div>` : ""}
      <div class="pub-result-table" style="width:100%;max-width:1100px;margin-top:12px">
        ${data ? classificationTable(data) : perBattery || '<div class="muted">Classificação em processamento…</div>'}
      </div>
    </div>`;
}

function viewEnded() {
  const groups = provasSorted()
    .map((prova) => {
      const provaHeats = heats().filter(
        (heat) => heat.prova_id === prova.id && heat.status === "finished"
      );
      if (!provaHeats.length) return "";
      const data = prova.consolidate_results
        ? classifications[prova.id]
        : null;
      const body = data
        ? classificationTable(data)
        : provaHeats
            .map(
              (heat) => `
              <div class="pub-end-group">
                <div class="pub-heat-name" style="font-size:clamp(18px,2vw,30px)">Bateria ${heat.heat_index_in_prova ?? heat.order_num} · ${escapeHtml(heat.name)}</div>
                ${compactTable(heat)}
              </div>`
            )
            .join("");
      return `
        <div class="pub-end-group">
          <div class="pub-heat-name" style="font-size:clamp(20px,2.2vw,34px)">${prova.order_num}. ${escapeHtml(prova.name)}</div>
          ${body}
        </div>`;
    })
    .join("");
  return `
    <div class="pub-center" style="justify-content:flex-start;padding-top:16px">
      <div class="pub-label" style="color:var(--cyan)">🏆 Evento encerrado</div>
      <h1 class="pub-event-title">${escapeHtml(eventData.name)}</h1>
      <div class="pub-subtitle">${escapeHtml(subtitle())}</div>
      <div style="width:100%;max-width:1100px;text-align:left;overflow:auto;flex:1">
        ${groups || '<div class="pub-subtitle">Nenhuma bateria finalizada.</div>'}
      </div>
    </div>`;
}

// --------------------------------------------------------------------------- //
// Reconciliação / WebSocket
// --------------------------------------------------------------------------- //
function reconcile() {
  const active = heats().find((heat) => heat.status === "active");
  if (active) return setState(3, { heatId: active.id });
  const ready = heats().find((heat) => heat.status === "ready_check");
  if (ready) return setState(2, { heatId: ready.id });
  if (allFinished()) return setState(6, { heatId: null });
  const last = lastFinished();
  if (last && nextScheduledAfter(last.event_seq)) {
    if (!nextInProva(heats(), last)) {
      return setState(7, { heatId: last.id });
    }
    return setState(5, { heatId: last.id });
  }
  return setState(1, { heatId: null });
}

async function refreshClassifications() {
  if (!eventData || !eventData.provas) return;
  const targets = eventData.provas.filter(
    (prova) =>
      prova.consolidate_results &&
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
    updateQr();
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
    stroke: payload.stroke,
    distance_m: payload.distance_m,
    naipe: payload.naipe,
    mixed_ranking: payload.mixed_ranking,
    category: payload.category,
    consolidate_results: payload.consolidate_results,
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
    setState(2, { heatId: heat.id });
  } else if (heat.status === "active") {
    setState(3, { heatId: heat.id });
  } else if (heat.status === "finished") {
    if (previousStatus === "active" && heat.id === currentHeatId) {
      setState(4, { heatId: heat.id });
    } else if (heat.id === currentHeatId) {
      goAfterResult();
    } else {
      renderState(false);
    }
    refreshClassifications().then(() => {
      if (state === 4) renderState(false);
    });
  } else {
    // scheduled atualizado (ex.: reordenação)
    renderState(false);
  }
}

const ws = new WSClient(wsUrl(), (message) => {
  if (message.type === "heat_state") onHeatState(message.payload);
  else if (message.type === "prova_state") {
    upsertProva(message.payload);
    api("GET", `/api/provas/${message.payload.id}/classification`)
      .then((data) => {
        classifications[message.payload.id] = data;
        if (state === 4 || state === 6) renderState(false);
      })
      .catch(() => {});
  } else if (message.type === "settings_updated") {
    if (eventData) {
      eventData.public_results_enabled =
        message.payload.public_results_enabled;
      eventData.public_name_mode = message.payload.public_name_mode;
    }
    updateQr();
    renderState(false);
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

async function loadSelection() {
  els.overlay.hidden = true;
  if (els.qr) els.qr.hidden = true;
  try {
    const all = await api("GET", "/api/events");
    events = all.filter((event) => event.status !== "finished");
  } catch (error) {
    events = [];
  }
  setState(0, { heatId: null });
}

async function init() {
  if (!eventId) {
    await loadSelection();
    return;
  }
  els.overlay.hidden = false;
  try {
    eventData = await api("GET", `/api/events/${eventId}`);
  } catch (error) {
    window.location.replace("publico.html");
    return;
  }
  updateQr();
  await refreshClassifications();
  reconcile();
  ws.connect();
}

init();
