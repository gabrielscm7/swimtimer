// Logica pura da apresentacao curada do telao — testavel com `node --test`.
(function (root) {
  function parseRef(ref) {
    if (typeof ref !== "string") return null;
    const separator = ref.indexOf(":");
    if (separator <= 0) return null;
    const kind = ref.slice(0, separator);
    const targetId = ref.slice(separator + 1);
    if (!targetId || (kind !== "prova" && kind !== "bateria")) return null;
    return { kind, targetId };
  }

  function refOf(slide) {
    if (!slide) return null;
    return `${slide.kind}:${slide.target_id}`;
  }

  function heatSeq(heat) {
    const value = Number(heat && heat.event_seq);
    return Number.isFinite(value) ? value : 0;
  }

  function findProva(provas, provaId) {
    return (provas || []).find((prova) => prova.id === provaId) || null;
  }

  function findHeat(heats, heatId) {
    return (heats || []).find((heat) => heat.id === heatId) || null;
  }

  function resolveRef(ref, eventData) {
    const parsed = parseRef(ref);
    if (!parsed || !eventData) return null;
    if (parsed.kind === "prova") {
      const prova = findProva(eventData.provas, parsed.targetId);
      if (!prova) return null;
      return {
        kind: "prova",
        id: prova.id,
        ref,
        prova,
        heat: null,
        label: `${prova.order_num}. ${prova.name}`,
        eligible: prova.status === "finished",
      };
    }
    const heat = findHeat(eventData.heats, parsed.targetId);
    if (!heat) return null;
    const prova = findProva(eventData.provas, heat.prova_id);
    return {
      kind: "bateria",
      id: heat.id,
      ref,
      prova,
      heat,
      label: `${prova ? `${prova.order_num}. ${prova.name} · ` : ""}Bateria ${heat.order_num} · ${heat.name}`,
      eligible: heat.status === "finished",
    };
  }

  function configOf(eventData) {
    const raw = (eventData && eventData.presentation) || {};
    return {
      enabled: raw.enabled !== false,
      rotation: raw.rotation !== false,
      slide_duration_s: Math.max(
        5,
        Math.min(60, Number(raw.slide_duration_s) || 15)
      ),
      show_next_prova: raw.show_next_prova !== false,
      pinned_ref: raw.pinned_ref || null,
      slides: Array.isArray(raw.slides) ? raw.slides : [],
    };
  }

  function eligibleSlides(eventData) {
    const config = configOf(eventData);
    if (!config.enabled) return [];
    return config.slides
      .map((slide) => resolveRef(refOf(slide), eventData))
      .filter((item) => item && item.eligible);
  }

  function orderedProvas(provas) {
    return [...(provas || [])].sort(
      (a, b) => Number(a.order_num) - Number(b.order_num)
    );
  }

  function nextScheduledHeatForProva(heats, provaId) {
    return (
      [...(heats || [])]
        .filter(
          (heat) => heat.prova_id === provaId && heat.status === "scheduled"
        )
        .sort((a, b) => heatSeq(a) - heatSeq(b))[0] || null
    );
  }

  function nextProva(heats, provas, referenceHeat) {
    const ordered = orderedProvas(provas);
    if (!ordered.length) return null;
    let currentOrder = null;
    if (referenceHeat) {
      const prova = findProva(provas, referenceHeat.prova_id);
      const value = prova
        ? Number(prova.order_num)
        : Number(referenceHeat.prova_order_num);
      if (Number.isFinite(value)) currentOrder = value;
    }
    for (const prova of ordered) {
      if (currentOrder !== null && Number(prova.order_num) <= currentOrder) {
        continue;
      }
      const heat = nextScheduledHeatForProva(heats, prova.id);
      if (heat) return { prova, heat };
    }
    return null;
  }

  function nextProvaLabel(next) {
    if (!next) return "";
    const battery = next.heat
      ? ` · Bateria ${next.heat.heat_index_in_prova ?? next.heat.order_num}`
      : "";
    return `Próxima prova: ${next.prova.order_num}. ${next.prova.name}${battery}`;
  }

  const api = {
    parseRef,
    refOf,
    resolveRef,
    configOf,
    eligibleSlides,
    nextProva,
    nextProvaLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PublicPresentationLogic = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
