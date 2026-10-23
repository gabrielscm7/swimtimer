export const DISTANCES = [25, 50, 100, 200, 400, 800, 1500];
export const DURATIONS = [1, 2, 3, 4, 5];
export const LANE_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8];
export const MAX_LOGO_BYTES = 1024 * 1024;

const params = new URLSearchParams(window.location.search);
export const eventId = params.get("event");
if (!eventId) {
  window.location.replace("index.html");
}

export const els = {
  sidebar: document.getElementById("sidebar"),
  hamburger: document.getElementById("btn-hamburger"),
  eventName: document.getElementById("event-name"),
  eventStatus: document.getElementById("event-status"),
  main: document.getElementById("main"),
  overview: document.getElementById("section-overview"),
  heats: document.getElementById("section-heats"),
  teams: document.getElementById("section-teams"),
  athletes: document.getElementById("section-athletes"),
  settings: document.getElementById("section-settings"),
};

export const state = {
  eventData: null,
  theme: null,
  themeForm: null,
  themeDirty: false,
  activeSection: "overview",
  expanded: new Set(),
  heatForm: null,
  laneTeams: {},
  laneAthletes: {},
  laneLoading: {},
  teamsFormOpen: false,
  dirty: false,
  dragHeat: null,
  allAthletes: [],
  athletesState: {
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
    q: "",
    teamId: "",
    naipe: "",
    category: "",
  },
  athleteForm: null,
  athleteImport: null,
  athleteSearchTimer: null,
  athleteRefreshTimer: null,
};
