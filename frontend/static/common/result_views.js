import { escapeHtml, formatTime } from "./format.js";
import { statusLabel } from "./ui.js";
import "../results_logic.js";

const CLASSIFICATION_STATUS = {
  valid: "Válido",
  dq: "Desclassificado",
  no_time: "Sem tempo",
  pending: "Em andamento",
};

const CLASSIFICATION_SHORT = {
  dq: "DQ",
  no_time: "sem tempo",
  pending: "em andamento",
};

function displayName(name, mode) {
  const api = globalThis.ResultsLogic;
  return api ? api.displayName(name, mode) : name;
}

function pubName(name, opts) {
  return displayName(name, opts.nameMode || "full") || "—";
}

function posClass(index) {
  if (index === 0) return "gold";
  if (index === 1) return "silver";
  if (index === 2) return "bronze";
  return "";
}

function logoImg(url, name, opts) {
  if (!opts.showLogos || !url) return "";
  return `<img class="team-logo small" src="${escapeHtml(
    url
  )}" alt="${escapeHtml(name || "Logo")}" loading="lazy" />`;
}

function participantLanes(heat) {
  return [...((heat && heat.heat_lanes) || [])]
    .filter((lane) => lane.participant_name || lane.team_id)
    .sort((a, b) => a.lane_number - b.lane_number);
}

function laneResultText(lane, heat) {
  if (lane.status === "dq") return "DQ";
  if (heat.heat_type === "maratona") {
    return `${lane.laps || 0} voltas · ${lane.meters || 0} m`;
  }
  return (
    lane.race_time_display ||
    (lane.race_time_ms != null ? formatTime(lane.race_time_ms) : "—")
  );
}

function tvHeatRows(heat) {
  const lanes = participantLanes(heat);
  if (heat.heat_type === "maratona") {
    return [...lanes]
      .sort(
        (a, b) => (b.laps || 0) - (a.laps || 0) || (b.meters || 0) - (a.meters || 0)
      )
      .map((lane, index) => ({
        kind: lane.status === "dq" ? "dq" : "finished",
        position: lane.status === "dq" ? null : index + 1,
        lane,
      }));
  }
  const finished = lanes
    .filter((lane) => lane.finish_at != null && lane.status !== "dq")
    .sort((a, b) => (a.race_time_ms || 0) - (b.race_time_ms || 0));
  const running = lanes.filter(
    (lane) => lane.finish_at == null && lane.status !== "dq"
  );
  const dq = lanes.filter((lane) => lane.status === "dq");
  return [
    ...finished.map((lane, index) => ({
      kind: "finished",
      position: index + 1,
      lane,
    })),
    ...running.map((lane) => ({ kind: "running", position: null, lane })),
    ...dq.map((lane) => ({ kind: "dq", position: null, lane })),
  ];
}

function windowRows(rows, opts) {
  const win = opts.window;
  if (!win) return rows;
  const offset = Math.max(0, Number(win.offset) || 0);
  const limit =
    win.limit == null ? rows.length : Math.max(0, Number(win.limit) || 0);
  return rows.slice(offset, offset + limit);
}

function tvHeatTable(heat, opts) {
  const rows = windowRows(tvHeatRows(heat), opts);
  if (!rows.length) return "";
  const marathon = heat.heat_type === "maratona";
  const compact = Boolean(opts.compact);
  const omitTeam = Boolean(opts.omitTeam);
  const body = rows
    .map(({ kind, position, lane }) => {
      const name = escapeHtml(
        marathon
          ? lane.team || pubName(lane.participant_name, opts)
          : pubName(lane.participant_name, opts)
      );
      const positionCell = marathon
        ? `<div class="pub-pos ${posClass((position || 1) - 1)}">${
            position == null ? "—" : `${position}º`
          }</div>`
        : `<div class="pub-pos ${position ? posClass(position - 1) : ""}">${
            position == null ? "—" : `${position}º`
          }</div>`;
      const timeCell =
        kind === "running" && opts.live
          ? '<span data-lane-time>00:00.00</span>'
          : kind === "dq"
            ? '<span class="pub-dq-badge">DQ</span>'
            : marathon
              ? escapeHtml(String(lane.laps || 0))
              : escapeHtml(laneResultText(lane, heat));
      if (marathon) {
        return `<div class="pub-trow ${kind === "dq" ? "dq" : ""}">
        ${positionCell}
        <div class="pub-name">${name}</div>
        ${
          omitTeam
            ? ""
            : `<div class="pub-team">Raia ${escapeHtml(
                String(lane.lane_number)
              )}</div>`
        }
        <div class="pub-time">${timeCell}</div>
        ${
          compact
            ? ""
            : `<div class="pub-speed">${escapeHtml(
                String(lane.meters || 0)
              )} m</div>`
        }
      </div>`;
      }
      return `<div class="pub-trow ${kind}">
        ${positionCell}
        <div class="pub-name">${name}</div>
        ${
          omitTeam
            ? ""
            : `<div class="pub-team">${logoImg(
                lane.team_logo_url,
                lane.team,
                opts
              )} ${escapeHtml(lane.team || "—")}</div>`
        }
        <div class="pub-time">${timeCell}</div>
        ${
          compact
            ? ""
            : `<div class="pub-speed">${
                lane.speed_ms != null ? `${lane.speed_ms} m/s` : "—"
              }</div>`
        }
      </div>`;
    })
    .join("");
  const className = `${compact ? " pub-compact" : ""}${
    omitTeam ? " pub-card" : ""
  }`;
  if (marathon) {
    return `<div class="pub-table pub-marathon${className}">
      <div class="pub-thead"><div>Pos</div><div>Equipe</div>${
        omitTeam ? "" : "<div>Raia</div>"
      }<div class="right">Voltas</div>${
        compact ? "" : '<div class="right">Metros</div>'
      }</div>
      ${body}
    </div>`;
  }
  return `<div class="pub-table pub-battery${className}">
    <div class="pub-thead"><div>Pos</div><div>Nome</div>${
      omitTeam ? "" : "<div>Equipe</div>"
    }<div class="right">Tempo</div>${
      compact ? "" : '<div class="right">Vel.</div>'
    }</div>
    ${body}
  </div>`;
}

function docHeatTable(heat, opts) {
  const lanes = participantLanes(heat);
  if (!lanes.length) return "";
  const marathon = heat.heat_type === "maratona";
  const tableClass = opts.variant === "print" ? "" : ' class="res-table"';
  const rows = lanes
    .map(
      (lane) => `<tr>
        <td class="pos">${escapeHtml(String(lane.lane_number))}</td>
        <td>${escapeHtml(lane.participant_name || "—")}</td>
        <td class="muted">${escapeHtml(lane.team || "—")}</td>
        <td class="time">${escapeHtml(laneResultText(lane, heat))}</td>
        <td>${escapeHtml(statusLabel(lane.status))}${
          opts.variant !== "print" && lane.late
            ? ' <span class="res-badge provisional">atrasado</span>'
            : ""
        }</td>
      </tr>`
    )
    .join("");
  return `<table${tableClass}>
    <thead><tr><th>Raia</th><th>Atleta</th><th>Equipe</th><th>${
      marathon ? "Parcial" : "Tempo"
    }</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

export function renderHeatResult(heat, opts = {}) {
  if (!heat) return "";
  const variant = opts.variant || "tv";
  if (variant === "tv") return tvHeatTable(heat, opts);
  if (variant === "compact") {
    return tvHeatTable(heat, {
      ...opts,
      compact: true,
      omitTeam: true,
      card: true,
    });
  }
  return docHeatTable(heat, opts);
}

export function renderPodium(heat, opts = {}) {
  const lanes = participantLanes(heat);
  let ranked;
  if (heat.heat_type === "maratona") {
    ranked = [...lanes].sort(
      (a, b) => (b.laps || 0) - (a.laps || 0) || (b.meters || 0) - (a.meters || 0)
    );
  } else {
    ranked = lanes
      .filter((lane) => lane.finish_at != null && lane.status !== "dq")
      .sort((a, b) => (a.race_time_ms || 0) - (b.race_time_ms || 0));
  }
  if (!ranked.length) return "";
  const medals = ["🥇", "🥈", "🥉"];
  const top = ranked.slice(0, 3);
  const order = [top[1], top[0], top[2]].filter(Boolean);
  const cards = order
    .map((lane) => {
      const place = top.indexOf(lane) + 1;
      const result =
        heat.heat_type === "maratona"
          ? `${lane.laps || 0} voltas`
          : lane.race_time_display || formatTime(lane.race_time_ms);
      const sub =
        heat.heat_type === "maratona"
          ? `${lane.meters || 0} m`
          : lane.speed_ms != null
            ? `${lane.speed_ms} m/s`
            : "";
      return `<div class="pub-podium-card place-${place}">
        <div class="pub-podium-medal">${medals[place - 1]}</div>
        <div class="pub-podium-name">${escapeHtml(
          pubName(lane.participant_name, opts) || lane.team || "—"
        )}</div>
        <div class="pub-podium-team">${logoImg(
          lane.team_logo_url,
          lane.team,
          opts
        )} ${escapeHtml(lane.team || "—")}</div>
        <div class="pub-podium-result">${escapeHtml(result)}</div>
        <div class="pub-podium-team">${escapeHtml(sub)}</div>
      </div>`;
    })
    .join("");
  return `<div class="pub-podium">${cards}</div>`;
}

function effectiveMode(classification, prova) {
  const naipe = String((prova && prova.naipe) || "").toUpperCase();
  if (naipe && naipe !== "MISTO") return "overall";
  const requested = classification && classification.mixed_ranking;
  return requested === "by_naipe" || requested === "both"
    ? requested
    : "overall";
}

function classificationSections(classification, prova) {
  const data = classification || {};
  const mode = effectiveMode(data, prova);
  const sections = [];
  if (mode !== "by_naipe") {
    const rows = [
      ...(data.standings || []).map((entry) => ({ entry, excluded: false })),
      ...(data.excluded || []).map((entry) => ({ entry, excluded: true })),
    ];
    sections.push({ key: "overall", label: "Classificação", rows });
  }
  if (mode !== "overall" && data.standings_by_naipe) {
    for (const naipe of ["M", "F"]) {
      const rows = (data.standings_by_naipe[naipe] || []).map((entry) => ({
        entry,
        excluded: false,
      }));
      if (!rows.length) continue;
      sections.push({
        key: naipe,
        label: naipe === "M" ? "Masculino" : "Feminino",
        rows,
      });
    }
  }
  return sections.filter((section) => section.rows.length);
}

function windowSections(sections, win) {
  if (!win) return sections.map((section) => ({ ...section, offset: 0 }));
  const offset = Math.max(0, Number(win.offset) || 0);
  const limit =
    win.limit == null
      ? Infinity
      : Math.max(0, Number(win.limit) || 0);
  const result = [];
  let cursor = 0;
  let emitted = 0;
  for (const section of sections) {
    const sectionStart = cursor;
    cursor += section.rows.length;
    if (emitted >= limit) break;
    if (cursor <= offset) continue;
    const from = Math.max(0, offset - sectionStart);
    const rows = section.rows.slice(from, from + (limit - emitted));
    if (!rows.length) continue;
    result.push({ ...section, rows, offset: from });
    emitted += rows.length;
  }
  return result;
}

function columnCount(rows) {
  return rows.length > 10 ? 2 : 1;
}

function splitColumns(rows, columns) {
  if (columns <= 1) return [rows];
  const size = Math.ceil(rows.length / columns);
  return [rows.slice(0, size), rows.slice(size)];
}

function tvClassificationCells({ entry, excluded }, opts) {
  const time = excluded
    ? CLASSIFICATION_SHORT[entry.classification_status] || "—"
    : entry.race_time_display || "—";
  const position = excluded
    ? "—"
    : `${entry.position ?? "—"}º${entry.tied ? "=" : ""}`;
  const rowClass = excluded
    ? "dq"
    : entry.position === 1
      ? "finished"
      : "";
  return `<div class="pub-trow ${rowClass}">
    <div class="pub-pos ${
      excluded || entry.position == null ? "" : posClass(entry.position - 1)
    }">${escapeHtml(position)}</div>
    <div class="pub-name">${escapeHtml(
      pubName(entry.participant_name, opts)
    )}</div>
    <div class="pub-team">${logoImg(
      entry.team_logo_url,
      entry.team_name,
      opts
    )} ${escapeHtml(entry.team_name || "—")}</div>
    <div class="pub-time">${escapeHtml(time)}</div>
  </div>`;
}

function tvProvaResult(prova, classification, opts) {
  const sections = windowSections(
    classificationSections(classification, prova),
    opts.window
  );
  if (!sections.length) return "";
  return sections
    .map((section) => {
      const columns = columnCount(section.rows);
      const chunks = splitColumns(section.rows, columns);
      const header = `<div class="pub-thead"><div>Pos</div><div>Nome</div><div>Equipe</div><div class="right">Tempo</div></div>`;
      const cols = chunks
        .map(
          (chunk) =>
            `<div class="pub-col">${header}${chunk
              .map((row) => tvClassificationCells(row, opts))
              .join("")}</div>`
        )
        .join("");
      const continuation = section.offset > 0 ? " (cont.)" : "";
      return `<div class="pub-section" data-section="${escapeHtml(
        section.key
      )}">
        <div class="pub-section-title">${escapeHtml(
          section.label
        )}${continuation}</div>
        <div class="pub-cols" data-cols="${columns}">${cols}</div>
      </div>`;
    })
    .join("");
}

function docClassificationTable(title, entries, opts) {
  if (!entries || !entries.length) return "";
  const rows = entries
    .map(
      (entry) => `<tr>
        <td class="pos">${
          entry.position ? `${entry.position}º${entry.tied ? "=" : ""}` : "—"
        }</td>
        <td>${escapeHtml(entry.participant_name || "—")}</td>
        <td class="muted">${escapeHtml(entry.team_name || "—")}</td>
        <td class="time">${escapeHtml(entry.race_time_display || "—")}</td>
        <td>${escapeHtml(
          CLASSIFICATION_STATUS[entry.classification_status] ||
            entry.classification_status ||
            "—"
        )}</td>
      </tr>`
    )
    .join("");
  const tableClass = opts.variant === "print" ? "" : ' class="res-table"';
  return `<div class="res-section-title">${escapeHtml(title)}</div>
    <table${tableClass}>
      <thead><tr><th>Pos</th><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function docExcludedTable(entries, opts) {
  if (!entries || !entries.length) return "";
  const rows = entries
    .map(
      (entry) => `<tr>
        <td>${escapeHtml(entry.participant_name || "—")}</td>
        <td class="muted">${escapeHtml(entry.team_name || "—")}</td>
        <td class="time">${escapeHtml(entry.race_time_display || "—")}</td>
        <td>${escapeHtml(
          CLASSIFICATION_STATUS[entry.classification_status] ||
            entry.classification_status ||
            "—"
        )}</td>
      </tr>`
    )
    .join("");
  const tableClass = opts.variant === "print" ? "" : ' class="res-table"';
  return `<div class="res-section-title">Fora da classificação</div>
    <table${tableClass}>
      <thead><tr><th>Atleta</th><th>Equipe</th><th>Tempo</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function docProvaResult(prova, classification, opts) {
  const data = classification || {};
  const mode = effectiveMode(data, prova);
  const parts = [];
  if (mode !== "by_naipe") {
    parts.push(
      docClassificationTable(
        "Classificação geral",
        data.standings || [],
        opts
      )
    );
    parts.push(docExcludedTable(data.excluded || [], opts));
  }
  if (mode !== "overall" && data.standings_by_naipe) {
    for (const naipe of ["M", "F"]) {
      const entries = data.standings_by_naipe[naipe] || [];
      if (!entries.length) continue;
      parts.push(
        docClassificationTable(
          naipe === "M" ? "Masculino" : "Feminino",
          entries,
          opts
        )
      );
    }
  }
  return parts.filter(Boolean).join("");
}

export function renderProvaResult(prova, classification, opts = {}) {
  const variant = opts.variant || "tv";
  if (variant === "tv") return tvProvaResult(prova, classification, opts);
  return docProvaResult(prova, classification, opts);
}

export function heatRowCount(heat) {
  return heat ? tvHeatRows(heat).length : 0;
}

export function provaRowCount(classification, prova) {
  return classificationSections(classification, prova).reduce(
    (total, section) => total + section.rows.length,
    0
  );
}
