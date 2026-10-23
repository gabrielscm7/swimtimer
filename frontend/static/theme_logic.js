(function (root) {
  const DEFAULT_THEME = {
    bg: "#0f1117",
    bg2: "#14161f",
    panel: "#1a1d27",
    text: "#e8eaf0",
    muted: "#6b7280",
    accent: "#00d4ff",
    accent_strong: "#00b0d6",
    bg_image_url: null,
    bg_opacity: 1,
    bg_fit: "cover",
    bg_position: "center",
    logo_url: null,
    title_override: null,
    footer_text: null,
    show_team_logos: true,
    font_scale: 1,
  };

  const COLOR_KEYS = [
    "bg",
    "bg2",
    "panel",
    "text",
    "muted",
    "accent",
    "accent_strong",
  ];
  const FITS = ["cover", "contain", "center"];
  const HEX_RE = /^#[0-9a-fA-F]{6}$/;
  const URL_RE = /^\/theme\/[A-Za-z0-9._-]+$/;
  const POSITION_RE = /^[A-Za-z0-9% .-]{1,40}$/;

  const PRESETS = {
    padrao_azul: { ...DEFAULT_THEME },
    claro_alto_contraste: {
      ...DEFAULT_THEME,
      bg: "#f4f7fb",
      bg2: "#e6ecf5",
      panel: "#ffffff",
      text: "#0b1220",
      muted: "#445066",
      accent: "#005fcc",
      accent_strong: "#004a9e",
    },
    escuro_neutro: {
      ...DEFAULT_THEME,
      bg: "#111111",
      bg2: "#181818",
      panel: "#1f1f1f",
      text: "#f0f0f0",
      muted: "#9a9a9a",
      accent: "#9ecbff",
      accent_strong: "#6fa8dc",
    },
  };

  function isValidHex(value) {
    return typeof value === "string" && HEX_RE.test(value);
  }

  function clamp(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, number));
  }

  function normalizeTheme(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const theme = { ...DEFAULT_THEME };

    for (const key of COLOR_KEYS) {
      if (isValidHex(source[key])) theme[key] = source[key].toLowerCase();
    }

    for (const key of ["bg_image_url", "logo_url"]) {
      const value = source[key];
      if (value === null || value === undefined) theme[key] = null;
      else if (typeof value === "string" && URL_RE.test(value)) {
        theme[key] = value;
      }
    }

    theme.bg_opacity = clamp(
      source.bg_opacity,
      0,
      1,
      DEFAULT_THEME.bg_opacity
    );
    if (FITS.includes(source.bg_fit)) theme.bg_fit = source.bg_fit;
    if (
      typeof source.bg_position === "string" &&
      POSITION_RE.test(source.bg_position)
    ) {
      theme.bg_position = source.bg_position;
    }
    theme.font_scale = clamp(
      source.font_scale,
      0.8,
      1.4,
      DEFAULT_THEME.font_scale
    );

    const textLimits = { title_override: 200, footer_text: 300 };
    for (const [key, limit] of Object.entries(textLimits)) {
      if (source[key] === null || source[key] === undefined) theme[key] = null;
      else if (typeof source[key] === "string") {
        theme[key] = source[key].slice(0, limit);
      }
    }

    if (typeof source.show_team_logos === "boolean") {
      theme.show_team_logos = source.show_team_logos;
    }

    return theme;
  }

  function hexToRgb(value) {
    if (!isValidHex(value)) return null;
    return [
      parseInt(value.slice(1, 3), 16),
      parseInt(value.slice(3, 5), 16),
      parseInt(value.slice(5, 7), 16),
    ];
  }

  function relativeLuminance(value) {
    const rgb = hexToRgb(value);
    if (!rgb) return null;
    const channels = rgb.map((component) => {
      const channel = component / 255;
      return channel <= 0.03928
        ? channel / 12.92
        : Math.pow((channel + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  }

  function contrastRatio(first, second) {
    const firstLum = relativeLuminance(first);
    const secondLum = relativeLuminance(second);
    if (firstLum === null || secondLum === null) return 0;
    const lighter = Math.max(firstLum, secondLum);
    const darker = Math.min(firstLum, secondLum);
    return (lighter + 0.05) / (darker + 0.05);
  }

  function contrastReport(raw) {
    const theme = normalizeTheme(raw);
    const pairs = {
      textPanel: contrastRatio(theme.text, theme.panel),
      textBg: contrastRatio(theme.text, theme.bg),
      mutedPanel: contrastRatio(theme.muted, theme.panel),
      mutedBg: contrastRatio(theme.muted, theme.bg),
      accentPanel: contrastRatio(theme.accent, theme.panel),
      accentBg: contrastRatio(theme.accent, theme.bg),
      accentStrongPanel: contrastRatio(theme.accent_strong, theme.panel),
      accentStrongBg: contrastRatio(theme.accent_strong, theme.bg),
    };
    const textMin = Math.min(pairs.textPanel, pairs.textBg);
    const min = Math.min(...Object.values(pairs));
    return {
      ...pairs,
      textMin,
      min,
      warning: textMin < 4.5,
      blocked: min < 3,
    };
  }

  function pickReadableColor(candidates, backgrounds) {
    if (!Array.isArray(candidates) || !candidates.length) return null;
    const targets = Array.isArray(backgrounds) ? backgrounds : [backgrounds];
    const score = (candidate) =>
      Math.min(
        ...targets.map((background) => contrastRatio(candidate, background))
      );
    return candidates.reduce((best, candidate) =>
      score(candidate) > score(best) ? candidate : best
    );
  }

  function isThemeSaveable(raw) {
    return !contrastReport(raw).blocked;
  }

  const api = {
    DEFAULT_THEME,
    PRESETS,
    isValidHex,
    normalizeTheme,
    hexToRgb,
    relativeLuminance,
    contrastRatio,
    contrastReport,
    pickReadableColor,
    isThemeSaveable,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.ThemeLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
