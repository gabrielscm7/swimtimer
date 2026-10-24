const test = require("node:test");
const assert = require("node:assert/strict");

const {
  rowsThatFit,
  pageCount,
  clampPage,
  sliceWindow,
  formatPageIndicator,
  columnCount,
  batteryColumns,
  cardsPerPage,
} = require("../static/pagination_logic.js");

test("rowsThatFit usa a altura util dividida pela altura da linha", () => {
  assert.equal(rowsThatFit(600, 50), 12);
  assert.equal(rowsThatFit(600, 50, 100), 10);
  assert.equal(rowsThatFit(600, 70), 8);
  assert.equal(rowsThatFit(40, 50), 1);
  assert.equal(rowsThatFit(0, 50), 1);
});

test("pageCount cobre o resto em uma pagina extra", () => {
  assert.equal(pageCount(21, 10), 3);
  assert.equal(pageCount(20, 10), 2);
  assert.equal(pageCount(0, 10), 1);
});

test("clampPage mantem a pagina valida ao encolher", () => {
  assert.equal(clampPage(1, 2), 1);
  assert.equal(clampPage(5, 2), 1);
  assert.equal(clampPage(-3, 2), 0);
  assert.equal(clampPage(0, 0), 0);
});

test("sliceWindow calcula offset e limite da pagina", () => {
  assert.deepEqual(sliceWindow(21, 10, 2), {
    page: 2,
    pages: 3,
    offset: 20,
    limit: 10,
  });
  assert.deepEqual(sliceWindow(21, 10, 9), {
    page: 2,
    pages: 3,
    offset: 20,
    limit: 10,
  });
});

test("indicador de pagina so aparece com mais de uma pagina", () => {
  assert.equal(formatPageIndicator(0, 1), "");
  assert.equal(formatPageIndicator(0, 3), "1/3");
  assert.equal(formatPageIndicator(2, 3), "3/3");
  assert.equal(formatPageIndicator(9, 3), "3/3");
});

test("classificacao grande usa duas colunas", () => {
  assert.equal(columnCount(1), 1);
  assert.equal(columnCount(10), 1);
  assert.equal(columnCount(11), 2);
  assert.equal(columnCount(22), 2);
  assert.equal(columnCount(22, 3), 2);
});

test("baterias lado a lado conforme a largura util", () => {
  assert.equal(batteryColumns(1920, 380, 3), 3);
  assert.equal(batteryColumns(1100, 380, 3), 2);
  assert.equal(batteryColumns(500, 380, 3), 1);
  assert.equal(batteryColumns(0, 380, 3), 1);
  assert.equal(cardsPerPage(1920, 3).perPage, 3);
  assert.equal(cardsPerPage(800, 3).perPage, 2);
  assert.equal(cardsPerPage(1920, 1).perPage, 1);
  assert.equal(cardsPerPage(1920, 0).perPage, 1);
});
