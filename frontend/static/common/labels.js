// Rotulos compartilhados de EVENTO / PROVA / BATERIA (ADR-012).
// UMD: funciona via require nos testes node e como window.Labels no browser.
// As listas STROKES/CATEGORIES devem espelhar backend/app/domain.py; o teste
// tests/domain_sync.test.js verifica a igualdade.
(function (root) {
  const STROKES = ["crawl", "borboleta", "peito", "costas", "livre", "medley"];
  const CATEGORIES = [
    "pre_mirim",
    "mirim",
    "petiz",
    "infantil",
    "juvenil",
    "junior",
    "adulto",
    "livre",
  ];
  const STROKE_LABELS = {
    crawl: "Crawl",
    borboleta: "Borboleta",
    peito: "Peito",
    costas: "Costas",
    livre: "Livre",
    medley: "Medley",
  };
  const NAIPE_LABELS = { M: "Masculino", F: "Feminino", MISTO: "Misto" };
  const CATEGORY_LABELS = {
    pre_mirim: "Pré Mirim",
    mirim: "Mirim",
    petiz: "Petiz",
    infantil: "Infantil",
    juvenil: "Juvenil",
    junior: "Júnior",
    adulto: "Adulto",
    livre: "Cat. Livre",
  };

  function _titleCase(value) {
    return String(value)
      .split(/[-_\s]+/)
      .map((part) =>
        part ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : ""
      )
      .join("-");
  }

  function strokeLabel(value) {
    if (!value) return "";
    return STROKE_LABELS[String(value).toLowerCase()] || String(value);
  }

  function naipeLabel(value) {
    if (!value) return "";
    return NAIPE_LABELS[String(value).toUpperCase()] || String(value);
  }

  function categoryLabel(value) {
    if (!value) return "";
    const key = String(value).toLowerCase();
    return CATEGORY_LABELS[key] || _titleCase(value);
  }

  function isFreeCategory(value) {
    return String(value || "").toLowerCase() === "livre";
  }

  function _formatHours(durationS) {
    const hours = Number(durationS) / 3600;
    if (!Number.isFinite(hours) || hours <= 0) return "";
    const text = Number.isInteger(hours)
      ? String(hours)
      : hours.toFixed(1).replace(/0$/, "").replace(/\.$/, "");
    return `${text} h`;
  }

  function generateProvaName(prova) {
    const data = prova || {};
    const parts = [];
    const stroke = strokeLabel(data.stroke);
    if (String(data.heat_type || data.format || "bateria").toLowerCase() === "maratona") {
      const duration = _formatHours(data.duration_s);
      const prefix = duration ? `Maratona ${duration}` : "Maratona";
      parts.push(stroke ? `${prefix} · ${stroke}` : prefix);
    } else if (data.distance_m) {
      parts.push(`${data.distance_m} m${stroke ? ` ${stroke}` : ""}`);
    } else if (stroke) {
      parts.push(stroke);
    }
    if (data.naipe) parts.push(naipeLabel(data.naipe));
    if (data.category && !isFreeCategory(data.category)) {
      parts.push(categoryLabel(data.category));
    }
    return parts.join(" · ") || "Prova";
  }

  function provaDescriptor(prova) {
    if (!prova) return "";
    if (prova.name) return prova.name;
    return generateProvaName(prova);
  }

  function provaLabel(prova) {
    if (!prova) return "";
    const order = Number(prova.order_num);
    const prefix = Number.isFinite(order) && order > 0 ? `PROVA ${order}` : "PROVA";
    const descriptor = provaDescriptor(prova);
    return descriptor ? `${prefix} · ${descriptor}` : prefix;
  }

  function defaultBateriaName(name, index, total, label) {
    if (!name) return true;
    const normalized = String(name).trim().toLowerCase();
    return new Set(
      [
        String(index),
        `bateria ${index}`,
        `bateria ${index} de ${total || ""}`.trim(),
        label.toLowerCase(),
      ].map((value) => value.trim())
    ).has(normalized);
  }

  function bateriaLabel(heat, options) {
    if (!heat) return "";
    const opts = options || {};
    const rawIndex = opts.index ?? heat.heat_index_in_prova ?? heat.order_num;
    const index = Number(rawIndex);
    const rawTotal = opts.total ?? heat.heats_in_prova;
    const total = Number(rawTotal);
    const label = Number.isFinite(index) && index > 0
      ? `BATERIA ${index}${Number.isFinite(total) && total > 0 ? ` de ${total}` : ""}`
      : "BATERIA";
    const name = String(heat.name || "").trim();
    const withName = defaultBateriaName(name, index, total, label)
      ? label
      : `${label} · ${name}`;
    const rawProvaOrder = opts.provaOrder ?? heat.prova_order_num;
    const provaOrder = Number(rawProvaOrder);
    if (opts.includeProva && Number.isFinite(provaOrder) && provaOrder > 0) {
      return `${withName} · Prova ${provaOrder}`;
    }
    return withName;
  }

  function classificationHelp(_consolidateResults, batteryCount) {
    const count = Number(batteryCount) || 0;
    return `Classificação consolidada de ${count} baterias (menor tempo)`;
  }

  const api = {
    STROKES,
    CATEGORIES,
    STROKE_LABELS,
    CATEGORY_LABELS,
    strokeLabel,
    naipeLabel,
    categoryLabel,
    isFreeCategory,
    generateProvaName,
    provaDescriptor,
    provaLabel,
    bateriaLabel,
    classificationHelp,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) root.Labels = api;
})(typeof window !== "undefined" ? window : globalThis);
