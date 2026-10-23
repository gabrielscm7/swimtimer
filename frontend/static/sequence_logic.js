// Sequencia canonica de baterias — pura e testavel com `node --test`.
//
// Desde o ADR-012, `heat.order_num` e unico por EVENTO e representa a ordem
// livre do programa. O backend expoe `event_seq = order_num`; clientes devem
// usar `event_seq` (nunca `prova.order_num` nem `order_num` isolado) para a
// sequencia canonica entre grupos intercalados.
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
    // A proxima prova e a do proximo item agendado na ordem global, o que
    // funciona tambem quando grupos estao intercalados (A1, B1, A2, B2).
    const seq = Number(heat.event_seq);
    const next = nextScheduledAfter(heats, seq);
    if (!next) return null;
    const prova = (provas || []).find((item) => item.id === next.prova_id);
    return prova ? { prova, heat: next } : null;
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
    const api =
      typeof globalThis !== "undefined" ? globalThis.Labels : null;
    if (api) {
      return api.bateriaLabel(heat, {
        index: heat.heat_index_in_prova,
        total: heat.heats_in_prova,
        provaOrder: heat.prova_order_num,
        includeProva: true,
      });
    }
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
