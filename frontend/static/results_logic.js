/* Logica pura da pagina publica de resultados (testavel via node --test). */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.ResultsLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const CONNECTORS = new Set([
    "da",
    "das",
    "de",
    "di",
    "do",
    "dos",
    "du",
    "e",
    "la",
    "las",
    "le",
    "les",
    "del",
    "van",
    "von",
  ]);

  function displayName(name, mode) {
    if (name == null) return name;
    if (mode !== "initials") return name;
    const tokens = String(name).trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return name;
    const first = tokens[0];
    const significant = tokens
      .slice(1)
      .filter((token) => !CONNECTORS.has(token.toLowerCase()));
    if (!significant.length) {
      return tokens.length === 1 ? first : `${first}.`;
    }
    const last = significant[significant.length - 1];
    return `${first} ${last.charAt(0).toUpperCase()}.`;
  }

  const BADGES = {
    official: "Oficial",
    provisional: "Provisório",
    corrected: "Retificado",
  };

  function badgeLabel(badge) {
    return BADGES[badge] || BADGES.provisional;
  }

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function matches(query, ...values) {
    const needle = normalize(query);
    if (!needle) return true;
    return values.some((value) => normalize(value).includes(needle));
  }

  function entryMatches(entry, query) {
    return matches(query, entry.participant_name, entry.team_name);
  }

  function laneStatusLabel(entry) {
    if (entry.classification_status === "dq" || entry.status === "dq") {
      return "DQ";
    }
    if (entry.classification_status === "no_time") return "sem tempo";
    if (entry.classification_status === "pending") return "em andamento";
    return entry.race_time_display || "—";
  }

  function filterProvas(provas, query) {
    if (!normalize(query)) return provas;
    return provas
      .map((prova) => {
        const standings = (prova.standings || []).filter((entry) =>
          entryMatches(entry, query)
        );
        const excluded = (prova.excluded || []).filter((entry) =>
          entryMatches(entry, query)
        );
        const byNaipe = {};
        for (const [naipe, entries] of Object.entries(
          prova.standings_by_naipe || {}
        )) {
          byNaipe[naipe] = (entries || []).filter((entry) =>
            entryMatches(entry, query)
          );
        }
        const heats = (prova.heats || [])
          .map((heat) => ({
            ...heat,
            lanes: (heat.lanes || []).filter((entry) =>
              entryMatches(entry, query)
            ),
          }))
          .filter((heat) => heat.lanes.length);
        const found =
          standings.length ||
          excluded.length ||
          heats.length ||
          Object.values(byNaipe).some((entries) => entries.length);
        if (!found) return null;
        return { ...prova, standings, excluded, standings_by_naipe: byNaipe, heats };
      })
      .filter(Boolean);
  }

  return {
    displayName,
    badgeLabel,
    normalize,
    matches,
    entryMatches,
    laneStatusLabel,
    filterProvas,
  };
});
