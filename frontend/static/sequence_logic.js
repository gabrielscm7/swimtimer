// Sequencia canonica de baterias — pura e testavel com `node --test`.
//
// `heat.order_num` e unico apenas DENTRO da prova (reinicia em 1). A unica
// ordem correta entre provas e `event_seq`, calculado no backend por
// (prova.order_num, heat.order_num). Nenhum cliente deve ordenar por
// `order_num` isolado.
(function (root) {
  function heatSeq(heat) {
    const value = Number(heat && heat.event_seq);
    return Number.isFinite(value) ? value : 0;
  }

  function heatsSorted(heats) {
    return [...(heats || [])].sort((a, b) => heatSeq(a) - heatSeq(b));
  }

  function nextScheduledAfter(heats, eventSeq) {
    const seq = Number(eventSeq);
    if (!Number.isFinite(seq)) return null;
    return (
      heatsSorted(heats).find(
        (heat) => heatSeq(heat) > seq && heat.status === "scheduled"
      ) || null
    );
  }

  function lastFinished(heats) {
    const finished = heatsSorted(heats).filter(
      (heat) => heat.status === "finished"
    );
    return finished.length ? finished[finished.length - 1] : null;
  }

  function heatsOfProva(heats, provaId) {
    return heatsSorted(heats).filter((heat) => heat.prova_id === provaId);
  }

  function nextInProva(heats, heat) {
    if (!heat) return null;
    const seq = heatSeq(heat);
    return (
      heatsSorted(heats).find(
        (item) =>
          item.prova_id === heat.prova_id &&
          heatSeq(item) > seq &&
          item.status === "scheduled"
      ) || null
    );
  }

  function nextProvaAfter(heats, provas, heat) {
    if (!heat) return null;
    const current = (provas || []).find(
      (prova) => prova.id === heat.prova_id
    );
    const currentOrder = current ? Number(current.order_num) : 0;
    const candidates = [...(provas || [])]
      .filter((prova) => Number(prova.order_num) > currentOrder)
      .sort((a, b) => Number(a.order_num) - Number(b.order_num));
    for (const prova of candidates) {
      const next = heatsSorted(heats).find(
        (item) => item.prova_id === prova.id && item.status === "scheduled"
      );
      if (next) return { prova, heat: next };
    }
    return null;
  }

  function heatPosition(heat) {
    const index = Number(heat && heat.heat_index_in_prova);
    const total = Number(heat && heat.heats_in_prova);
    if (!Number.isFinite(index) || !Number.isFinite(total) || total <= 0) {
      return null;
    }
    return { index, total };
  }

  function provaLabel(heat) {
    if (!heat) return "";
    const order = Number(heat.prova_order_num);
    const name = heat.prova_name || "";
    if (Number.isFinite(order) && order > 0) {
      return `Prova ${order}${name ? ` · ${name}` : ""}`;
    }
    return name;
  }

  function provaHeaderLabel(heat) {
    if (!heat) return "";
    const label = provaLabel(heat);
    const position = heatPosition(heat);
    if (!position) return label;
    const battery = `Bateria ${position.index} de ${position.total}`;
    return label ? `${label} · ${battery}` : battery;
  }

  const api = {
    heatSeq,
    heatsSorted,
    nextScheduledAfter,
    lastFinished,
    heatsOfProva,
    nextInProva,
    nextProvaAfter,
    heatPosition,
    provaLabel,
    provaHeaderLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.SequenceLogic = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
