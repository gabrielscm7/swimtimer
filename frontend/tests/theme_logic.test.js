const test = require("node:test");
const assert = require("node:assert/strict");

const {
  DEFAULT_THEME,
  PRESETS,
  normalizeTheme,
  isValidHex,
  contrastRatio,
  contrastReport,
  pickReadableColor,
  isThemeSaveable,
} = require("../static/theme_logic.js");

test("isValidHex aceita #RRGGBB e rejeita valores ruins", () => {
  assert.equal(isValidHex("#00d4ff"), true);
  assert.equal(isValidHex("#ABCDEF"), true);
  assert.equal(isValidHex("#fff"), false);
  assert.equal(isValidHex("azul"), false);
  assert.equal(isValidHex("#zzzzzz"), false);
  assert.equal(isValidHex(null), false);
});

test("normalizeTheme preenche defaults e descarta invalidos", () => {
  assert.deepEqual(normalizeTheme(null), DEFAULT_THEME);
  const theme = normalizeTheme({
    bg: "#ffffff",
    panel: "invalido",
    bg_opacity: 0.35,
    bg_fit: "contain",
    font_scale: 1.25,
    show_team_logos: false,
    bg_image_url: "javascript:alert(1)",
  });
  assert.equal(theme.bg, "#ffffff");
  assert.equal(theme.panel, DEFAULT_THEME.panel);
  assert.equal(theme.bg_opacity, 0.35);
  assert.equal(theme.bg_fit, "contain");
  assert.equal(theme.font_scale, 1.25);
  assert.equal(theme.show_team_logos, false);
  assert.equal(theme.bg_image_url, null);

  const truncated = normalizeTheme({
    title_override: "x".repeat(250),
    footer_text: "y".repeat(350),
  });
  assert.equal(truncated.title_override.length, 200);
  assert.equal(truncated.footer_text.length, 300);
});

test("contrastRatio calcula branco/preto como 21:1", () => {
  assert.equal(contrastRatio("#ffffff", "#000000"), 21);
  assert.equal(contrastRatio("#000000", "#000000"), 1);
});

test("contrastReport sinaliza aviso e bloqueio", () => {
  const low = {
    ...DEFAULT_THEME,
    bg: "#888888",
    panel: "#888888",
    text: "#777777",
  };
  const blocked = contrastReport(low);
  assert.equal(blocked.blocked, true);
  assert.equal(blocked.warning, true);
  assert.equal(isThemeSaveable(low), false);

  const medium = {
    ...DEFAULT_THEME,
    bg: "#777777",
    panel: "#777777",
    text: "#ffffff",
    muted: "#e0e0e0",
    accent: "#ffffff",
    accent_strong: "#ffffff",
  };
  const warned = contrastReport(medium);
  assert.equal(warned.blocked, false);
  assert.equal(warned.warning, true);
  assert.equal(isThemeSaveable(medium), true);

  const standard = contrastReport(DEFAULT_THEME);
  assert.equal(standard.blocked, false);
  assert.equal(standard.warning, false);
  assert.ok(standard.textPanel >= 4.5);
  assert.ok(standard.textBg >= 4.5);
});

test("contrastReport considera destaque e texto suave", () => {
  const accentLow = {
    ...DEFAULT_THEME,
    accent: DEFAULT_THEME.bg,
    accent_strong: DEFAULT_THEME.bg2,
  };
  assert.equal(contrastReport(accentLow).blocked, true);
  assert.equal(isThemeSaveable(accentLow), false);

  const mutedLow = {
    ...DEFAULT_THEME,
    muted: DEFAULT_THEME.panel,
  };
  assert.equal(contrastReport(mutedLow).blocked, true);
});

test("pickReadableColor escolhe a variante com maior contraste", () => {
  assert.equal(
    pickReadableColor(["#facc15", "#6b5200"], ["#ffffff", "#f4f7fb"]),
    "#6b5200"
  );
  assert.equal(
    pickReadableColor(["#facc15", "#6b5200"], ["#0f1117", "#1a1d27"]),
    "#facc15"
  );
});

test("presets passam no contraste minimo", () => {
  assert.ok(Object.keys(PRESETS).length >= 3);
  for (const preset of Object.values(PRESETS)) {
    const report = contrastReport(normalizeTheme(preset));
    assert.equal(report.blocked, false, JSON.stringify(report));
  }
});
