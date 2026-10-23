(function (root) {
  function athleteOptionLabel(athlete) {
    const team = athlete.team_name || "Sem equipe";
    const code = athlete.registration_code
      ? ` · ${athlete.registration_code}`
      : "";
    return `${athlete.name} — ${team}${code}`;
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
    if (naipe === "MISTO") return "Misto";
    return "—";
  }

  function mixedRankingLabel(value) {
    if (value === "overall") return "Geral";
    if (value === "by_naipe") return "Por naipe";
    if (value === "both") return "Geral + por naipe";
    return "Geral + por naipe";
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

  function nextHeatOrder(heats) {
    const max = (heats || []).reduce(
      (value, heat) => Math.max(value, Number(heat.order_num) || 0),
      0
    );
    return max + 1;
  }

  function bateriaLabel(heat) {
    if (!heat) return "Bateria";
    return `Bateria ${heat.order_num}${
      heat.name ? ` · ${heat.name}` : ""
    }`;
  }

  const ERROR_MESSAGES = {
    order_num_duplicado:
      "Esta ordem já está em uso. Provas têm ordem única no programa do evento; baterias têm ordem única dentro da prova.",
    ordem_ids_invalidos:
      "A nova ordem não corresponde a todos os itens. Recarregue a página e tente novamente.",
    prova_ja_iniciada:
      "Não é possível alterar: a prova ou bateria já foi iniciada.",
    bateria_ja_iniciada:
      "Não é possível alterar: a bateria já foi iniciada.",
    bateria_nao_esta_scheduled:
      "A bateria precisa estar agendada (não iniciada) para esta ação.",
    bateria_nao_esta_em_ready_check:
      "A bateria não está em verificação de fiscais (ready check).",
    bateria_nao_esta_ativa: "A bateria não está em andamento.",
    bateria_nao_iniciada: "A bateria ainda não foi iniciada.",
    bateria_nao_encontrada: "Bateria não encontrada.",
    equipe_em_uso: "Esta equipe possui atletas ou raias vinculadas.",
    atleta_em_uso: "Este atleta está alocado em uma raia.",
    atleta_duplicado:
      "Já existe um atleta com este nome nesta equipe.",
    naipe_incompativel:
      "O naipe do atleta é incompatível com o naipe da prova.",
    categoria_incompativel:
      "A categoria do atleta é incompatível com a categoria da prova.",
    atleta_duplicado_na_bateria:
      "Este atleta já está inscrito nesta bateria.",
    atleta_em_outra_bateria_ativa:
      "Este atleta já está em uma bateria ativa (ou em verificação) de outra prova.",
    atleta_com_resultado:
      "O atleta já possui resultado finalizado; alterar naipe/categoria exige exceção do supervisor.",
    override_reason_obrigatorio:
      "Informe o motivo da exceção para autorizar com o PIN do supervisor.",
    override_requer_pin_do_supervisor:
      "O servidor não tem PIN de supervisor configurado; exceções estão desabilitadas.",
    pin_do_supervisor_invalido: "PIN do supervisor inválido.",
    equipe_nao_encontrada: "Equipe não encontrada neste evento.",
    atleta_nao_encontrado: "Atleta não encontrado neste evento.",
    naipe_invalido: "Naipe inválido: use Masculino ou Feminino.",
    nome_obrigatorio: "Informe o nome.",
    arquivo_muito_grande: "Arquivo maior que o limite permitido.",
    arquivo_vazio: "O arquivo está vazio.",
    formato_invalido: "Formato inválido: use CSV ou XLSX.",
    planilha_invalida: "Não foi possível ler a planilha.",
    planilha_sem_cabecalho:
      "Cabeçalho não encontrado. Inclua NOME, EQUIPE, NAIPE e CATEGORIA.",
    planilha_muito_grande:
      "Planilha acima do limite de linhas permitido.",
    importacao_conflito:
      "Outra importação ocorreu ao mesmo tempo. Tente novamente.",
    distance_m_obrigatorio: "Informe a distância da bateria.",
    duration_s_obrigatorio: "Informe a duração da maratona.",
    contraste_insuficiente:
      "Contraste abaixo de 3:1 entre texto, destaques e fundo/painel. Ajuste as cores antes de salvar.",
    imagem_muito_grande:
      "Imagem muito grande: use no máximo 3840 px em cada lado.",
    imagem_formato_invalido:
      "Formato de imagem inválido: use PNG, JPG ou WebP.",
    url_tema_invalida:
      "A imagem referenciada não pertence a este evento. Envie a imagem novamente.",
    imagem_tema_ausente:
      "A imagem referenciada não existe mais. Envie-a novamente antes de salvar.",
  };

  function gestaoErrorMessage(error) {
    const raw =
      error && error.message ? String(error.message) : String(error || "");
    const key = raw.trim();
    if (ERROR_MESSAGES[key]) return ERROR_MESSAGES[key];
    if (key.startsWith("colunas_obrigatorias:")) {
      const columns = key.slice("colunas_obrigatorias:".length);
      return `Colunas obrigatórias ausentes: ${columns.replace(/,/g, ", ")}.`;
    }
    if (key.startsWith("atleta_duplicado_na_prova:")) {
      const battery = key
        .slice("atleta_duplicado_na_prova:".length)
        .trim();
      return battery
        ? `Este atleta já está inscrito na bateria "${battery}" desta prova.`
        : "Este atleta já está inscrito em outra bateria desta prova.";
    }
    return key || "Erro inesperado.";
  }

  const api = {
    athleteOptionLabel,
    athleteLabelIndex,
    naipeLabel,
    mixedRankingLabel,
    paginationInfo,
    buildAthleteQuery,
    importResultSummary,
    distinctCategories,
    nextHeatOrder,
    bateriaLabel,
    gestaoErrorMessage,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.GestaoLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
