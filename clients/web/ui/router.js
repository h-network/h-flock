"use strict";

const routes = new Set(["overview", "agents", "terminals", "alerts", "boards", "recordings", "audit", "settings"]);
const sectionIds = {
  overview: "overview-section",
  agents: "agents-panel",
  agent: "detail",
  terminals: "terminals-section",
  alerts: "alerts-panel",
  boards: "boards-panel",
  recordings: "recordings-section",
  audit: "audit-section",
  settings: "settings-section",
};

export function parseRoute(hash = location.hash) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "agents" && parts[1]) {
    try { return { section: "agent", agent: decodeURIComponent(parts.slice(1).join("/")) }; }
    catch (_) { return { section: "overview" }; }
  }
  return { section: routes.has(parts[0]) ? parts[0] : "overview" };
}

export class HashRouter {
  constructor({ onRoute = () => {} } = {}) {
    this.onRoute = onRoute;
    this.handleChange = () => this.render();
  }

  start() {
    window.addEventListener("hashchange", this.handleChange);
    if (!location.hash || parseRoute().section === "overview" && location.hash !== "#/overview") {
      history.replaceState(null, "", "#/overview");
    }
    this.render();
  }

  go(path) { location.hash = path.startsWith("#/") ? path : `#/${path.replace(/^\//, "")}`; }

  current() { return parseRoute(); }

  render() {
    const route = this.current();
    const activeId = sectionIds[route.section];
    for (const section of document.querySelectorAll(".app-section")) section.hidden = section.id !== activeId;
    const navSection = route.section === "agent" ? "agents" : route.section;
    for (const link of document.querySelectorAll("[data-nav]")) {
      if (link.dataset.nav === navSection) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    document.body.dataset.route = route.section;
    this.onRoute(route);
  }
}
