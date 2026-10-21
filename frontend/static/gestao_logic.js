(function (root) {
  function athleteOptionLabel(athlete) {
    const team = athlete.team_name || "Sem equipe";
    return `${athlete.name} — ${team}`;
  }

  function athleteLabelIndex(athletes) {
    const index = new Map();
    for (const athlete of athletes || []) {
      index.set(athleteOptionLabel(athlete), athlete);
    }
    return index;
  }

  function naipeLabel(naipe) {
    if (naipe === "M") return "Masculino";
    if (naipe === "F") return "Feminino";
    return "—";
  }

  function paginationInfo(total, limit, offset) {
    const safeLimit = Math.max(1, Number(limit) || 1);
    const safeTotal = Math.max(0, Number(total) || 0);
    const pages = Math.max(1, Math.ceil(safeTotal / safeLimit));
    const rawPage = Math.floor((Number(offset) || 0) / safeLimit) + 1;
    const page = Math.min(pages, Math.max(1, rawPage));
    return {
      page,
      pages,
      hasPrev: page > 1,
      hasNext: page < pages,
    };
  }

  function buildAthleteQuery(state) {
    const params = new URLSearchParams();
    params.set("limit", String(state.limit));
    params.set("offset", String(state.offset));
    if (state.q) params.set("q", state.q);
    if (state.teamId) params.set("team_id", state.teamId);
    if (state.naipe) params.set("naipe", state.naipe);
    if (state.category) params.set("category", state.category);
    return params.toString();
  }

  function importResultSummary(result) {
    if (!result) return "";
    const parts = [
      `${result.created_athletes} atleta(s) criado(s)`,
    ];
    if (result.created_teams) {
      parts.push(`${result.created_teams} equipe(s) criada(s)`);
    }
    if (result.skipped) {
      parts.push(`${result.skipped} linha(s) vazia(s) ignorada(s)`);
    }
    const errors = (result.errors || []).length;
    if (errors) parts.push(`${errors} erro(s)`);
    return parts.join(" · ");
  }

  function distinctCategories(athletes) {
    return Array.from(
      new Set(
        (athletes || []).map((athlete) => athlete.category).filter(Boolean)
      )
    ).sort();
  }

  const api = {
    athleteOptionLabel,
    athleteLabelIndex,
    naipeLabel,
    paginationInfo,
    buildAthleteQuery,
    importResultSummary,
    distinctCategories,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.GestaoLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
