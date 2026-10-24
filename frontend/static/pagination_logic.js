// Matematica pura do telao (paginacao e colunas) — testavel com `node --test`.
(function (root) {
  function positive(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  function rowsThatFit(bodyHeight, rowHeight, reserve = 0) {
    const usable = Number(bodyHeight) - Number(reserve || 0);
    const line = positive(rowHeight, 1);
    if (!Number.isFinite(usable) || usable <= 0) return 1;
    return Math.max(1, Math.floor(usable / line));
  }

  function pageCount(totalRows, rowsPerPage) {
    const total = Math.max(0, Math.floor(Number(totalRows) || 0));
    const perPage = positive(rowsPerPage, 1);
    if (!total) return 1;
    return Math.max(1, Math.ceil(total / perPage));
  }

  function clampPage(page, pages) {
    const total = positive(pages, 1);
    const value = Math.floor(Number(page) || 0);
    if (value < 0) return 0;
    return Math.min(value, total - 1);
  }

  function sliceWindow(totalRows, rowsPerPage, page) {
    const perPage = positive(rowsPerPage, 1);
    const pages = pageCount(totalRows, perPage);
    const current = clampPage(page, pages);
    return {
      page: current,
      pages,
      offset: current * perPage,
      limit: perPage,
    };
  }

  function formatPageIndicator(page, pages) {
    const total = positive(pages, 1);
    if (total <= 1) return "";
    return `${clampPage(page, total) + 1}/${total}`;
  }

  function columnCount(rows, maxColumns = 2, threshold = 10) {
    const total = Math.max(0, Number(rows) || 0);
    if (total <= threshold) return 1;
    return Math.max(1, Math.min(2, maxColumns));
  }

  function batteryColumns(availableWidth, minColumnWidth = 380, maxColumns = 3) {
    const width = Number(availableWidth) || 0;
    const min = positive(minColumnWidth, 1);
    const max = Math.max(1, Math.floor(Number(maxColumns) || 1));
    if (width <= 0) return 1;
    return Math.max(1, Math.min(max, Math.floor(width / min)));
  }

  function cardsPerPage(availableWidth, cards, options = {}) {
    const columns = batteryColumns(
      availableWidth,
      options.minColumnWidth || 380,
      options.maxColumns || 3
    );
    const total = Math.max(0, Number(cards) || 0);
    return { columns, perPage: Math.max(1, Math.min(columns, total || 1)) };
  }

  const api = {
    rowsThatFit,
    pageCount,
    clampPage,
    sliceWindow,
    formatPageIndicator,
    columnCount,
    batteryColumns,
    cardsPerPage,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) root.PaginationLogic = api;
})(typeof window !== "undefined" ? window : globalThis);
