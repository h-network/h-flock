"use strict";

const KEY = "hflock.console.preferences.v1";
const defaults = { density: "comfortable", theme: "system", selectedAgent: "", officeColumn: 42 };

export class Preferences {
  constructor() {
    this.value = this.load();
    this.apply();
    this.bind();
  }

  load() {
    try {
      const stored = JSON.parse(localStorage.getItem(KEY) || "{}");
      return {
        density: ["comfortable", "compact"].includes(stored.density) ? stored.density : defaults.density,
        theme: ["system", "light", "dark"].includes(stored.theme) ? stored.theme : defaults.theme,
        selectedAgent: typeof stored.selectedAgent === "string" ? stored.selectedAgent : "",
        officeColumn: Math.min(60, Math.max(32, Number(stored.officeColumn) || defaults.officeColumn)),
      };
    } catch (_) { return { ...defaults }; }
  }

  save(changes = {}) {
    this.value = { ...this.value, ...changes };
    localStorage.setItem(KEY, JSON.stringify(this.value));
    this.apply();
  }

  apply() {
    document.documentElement.dataset.density = this.value.density;
    document.documentElement.dataset.theme = this.value.theme;
    document.documentElement.style.setProperty("--office-column", `${this.value.officeColumn}%`);
    const density = document.getElementById("preference-density");
    const theme = document.getElementById("preference-theme");
    const width = document.getElementById("preference-panel-size");
    if (density) density.value = this.value.density;
    if (theme) theme.value = this.value.theme;
    if (width) width.value = String(this.value.officeColumn);
  }

  bind() {
    document.getElementById("open-preferences").onclick = () => { location.hash = "#/settings"; };
    document.getElementById("preferences-form").oninput = () => this.save({
      density: document.getElementById("preference-density").value,
      theme: document.getElementById("preference-theme").value,
      officeColumn: Number(document.getElementById("preference-panel-size").value),
    });
  }

  rememberAgent(agent) { this.save({ selectedAgent: agent }); }
}
