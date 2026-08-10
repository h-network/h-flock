"use strict";

import { AgentsPanel } from "./ui/agents.js";
import { AlertsPanel } from "./ui/alerts.js";
import { BoardsPanel } from "./ui/boards.js";
import { ActivityPanel } from "./ui/activity.js";
import { MessagesPanel } from "./ui/messages.js";
import { LifecyclePanel } from "./ui/lifecycle.js";
import { TerminalPanel } from "./ui/terminal.js";
import { Preferences } from "./ui/preferences.js";
import { CommandPalette } from "./ui/palette.js";
import { AlertNotifications } from "./ui/notifications.js";
import { HashRouter } from "./ui/router.js";
import { renderRecordingsSection } from "./ui/recordings.js";
import { renderAuditSection } from "./ui/audit.js";
import { PanelStatus } from "./ui/shared.js";

const $ = (id) => document.getElementById(id);
const state = { selected: "", tab: "activity", demo: false, roster: null, alertCount: null, results: { agents: 0, alerts: 0, boards: 0 } };
const terminal = new TerminalPanel();
const preferences = new Preferences();
const notifications = new AlertNotifications();
const updateResult = (panel) => (count) => { state.results[panel] = count; renderSearchSummary(); };
const boards = new BoardsPanel({ onBoards: (value) => agents.setBoards(value), onResults: updateResult("boards") });
const agents = new AgentsPanel({
  onSelect: (agent) => router.go(`agents/${encodeURIComponent(agent)}`),
  onResults: updateResult("agents"),
  onRoster: (summary) => {
    state.roster = summary;
    $("empty-office").hidden = summary.staffed !== 0;
    $("sidebar-agent-count").textContent = String(summary.total);
    updateOfficeSummary();
    populateTerminalAgents();
  },
});
const activity = new ActivityPanel();
let messages;
let lifecycle;
const alerts = new AlertsPanel({
  onCount: (count) => { state.alertCount = count; $("sidebar-alert-count").textContent = String(count); updateOfficeSummary(); },
  onResults: updateResult("alerts"),
  onAlert: (alert) => notifications.receive(alert),
});
let palette;
let router;
const loadedSections = new Set();

function renderSearchSummary() {
  const query = $("global-search")?.value.trim();
  const plural = (count, singular) => `${count} ${singular}${count === 1 ? "" : "s"}`;
  const alertResult = state.results.alerts;
  const alertsText = typeof alertResult === "object"
    ? `${plural(alertResult.groups, "alert group")} (${plural(alertResult.alerts, "event")})`
    : plural(alertResult, "alert");
  $("search-results-summary").textContent = query
    ? `${plural(state.results.agents, "agent")} · ${alertsText} · ${plural(state.results.boards, "ticket")}`
    : "All office data";
}

function filterOffice(query) {
  agents.setFilter(query);
  alerts.setFilter(query);
  boards.setFilter(query);
}

function populateTerminalAgents() {
  const names = agents.names().filter((name) => agents.detail(name)?.vab === "tmux");
  for (let index = 1; index <= 4; index += 1) {
    const select = $(`cell-agent-${index}`);
    if (!select) continue;
    const current = select.value;
    select.replaceChildren(new Option("Select Agent", ""), ...names.map((name) => new Option(name, name)));
    if (names.includes(current)) select.value = current;
  }
}

function updateOfficeSummary() {
  if (!state.roster) return;
  const { working, blocked } = state.roster;
  const alertsText = state.alertCount == null ? "alerts loading" : `${state.alertCount} retained alert${state.alertCount === 1 ? "" : "s"}`;
  $("overview-working").textContent = String(working);
  $("overview-blocked").textContent = String(blocked);
  $("overview-alerts").textContent = state.alertCount == null ? "—" : String(state.alertCount);
  $("overview-blocked-action").disabled = blocked === 0;
  $("overview-blocked-action").classList.toggle("summary-attention", blocked > 0);
}

function activateTab(name) {
  state.tab = name;
  for (const tab of ["activity", "terminal", "messages", "board", "lifecycle"]) {
    const selected = tab === name;
    const button = $(`${tab}-tab`);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    const view = tab === "terminal" ? $("terminal-panel") : $(`${tab === "board" ? "agent-board" : tab}-view`);
    view.hidden = !selected;
  }
  if (name === "terminal" && state.selected) terminal.connect(state.selected);
  if (name === "board" && state.selected) boards.renderAgent(state.selected);
}

async function selectAgent(agent) {
  state.selected = agent;
  preferences.rememberAgent(agent);
  const detail = agents.detail(agent);
  $("detail-title").textContent = agent;
  $("detail-subtitle").textContent = `${detail?.vab || "unknown VAB"} · ${detail?.presence?.state || "unknown"}`;
  $("detail-title").focus();
  $("message").disabled = false;
  $("send").disabled = false;
  agents.render();
  lifecycle.select(agent);
  await activity.select(agent);
  messages.render(agent);
  boards.renderAgent(agent);
  if (state.tab === "terminal") terminal.connect(agent);
}

function commandList() {
  const commands = [
    { label: "Hire an agent", hint: "Lifecycle", keywords: "start enrol", run: () => $("hire-dialog").showModal() },
    { label: "Open overview", hint: "Section", keywords: "home health summary", run: () => router.go("overview") },
    { label: "Open agents", hint: "Section", keywords: "roster presence", run: () => router.go("agents") },
    { label: "Open terminals", hint: "Section", keywords: "sessions shell", run: () => router.go("terminals") },
    { label: "Filter alerts", hint: "Section", keywords: "search warning", run: () => { router.go("alerts"); $("global-search").focus(); } },
    { label: "Open task board", hint: "Section", keywords: "tickets work", run: () => router.go("boards") },
    { label: "Open recordings", hint: "Section", keywords: "terminal replay", run: () => router.go("recordings") },
    { label: "Open audit log", hint: "Section", keywords: "operator security actions", run: () => router.go("audit") },
    { label: "Search the office", hint: "/", keywords: "filter agents alerts boards", run: () => $("global-search").focus() },
    { label: "Display preferences", hint: "Theme · density", keywords: "compact light dark size", run: () => router.go("settings") },
    { label: "Keyboard shortcuts", hint: "?", keywords: "help keys", run: () => $("shortcuts-dialog").showModal() },
  ];
  for (const agent of agents.names()) {
    commands.push({ label: `Open ${agent}`, hint: "Agent", keywords: `${agents.detail(agent)?.presence?.state || "unknown"} terminal messages`, run: () => router.go(`agents/${encodeURIComponent(agent)}`) });
    commands.push({ label: `Open ${agent} board`, hint: "Task board", keywords: "tickets todo doing hold done", run: () => { $("global-search").value = agent; filterOffice(agent); router.go("boards"); } });
  }
  if (state.selected && agents.detail(state.selected)?.vab === "tmux") {
    commands.push(
      { label: `Pause ${state.selected}`, hint: "Lifecycle", keywords: "stop cli keep identity", run: () => lifecycle.control("PauseAgent", "Pause accepted · messages will queue until resume") },
      { label: `Resume ${state.selected}`, hint: "Lifecycle", keywords: "start cli drain", run: () => lifecycle.control("ResumeAgent", "Resume accepted · queued messages will drain") },
      { label: `Retire ${state.selected}`, hint: "Destructive · confirmation required", keywords: "remove let go", run: () => lifecycle.openRetire() },
    );
  }
  return commands;
}

function bindTabs() {
  const names = ["activity", "terminal", "messages", "board", "lifecycle"];
  for (const name of names) {
    const button = $(`${name}-tab`);
    button.onclick = () => activateTab(name);
    button.onkeydown = (event) => {
      let index = names.indexOf(name);
      if (event.key === "ArrowRight") index = (index + 1) % names.length;
      else if (event.key === "ArrowLeft") index = (index + names.length - 1) % names.length;
      else if (event.key === "Home") index = 0;
      else if (event.key === "End") index = names.length - 1;
      else return;
      event.preventDefault();
      activateTab(names[index]);
      $(`${names[index]}-tab`).focus();
    };
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.tab !== "activity") activateTab("activity");
  });
}

function bindDemoControls() {
  if (!state.demo) return;
  $("demo-controls").hidden = false;
  for (const button of $("demo-controls").querySelectorAll("button")) {
    button.onclick = () => {
      const value = button.dataset.demoState;
      for (const panel of [agents, alerts, boards, activity, messages]) panel.demoState(value);
    };
  }
}

function bindGlobalControls() {
  palette = new CommandPalette({ commands: commandList });
  $("open-command").onclick = () => palette.open();
  $("overview-command-action").onclick = () => palette.open();
  $("overview-blocked-action").onclick = () => {
    const blocked = agents.names().find((agent) => agents.detail(agent)?.presence?.state === "blocked");
    if (blocked) router.go(`agents/${encodeURIComponent(blocked)}`);
  };
  $("open-shortcuts").onclick = () => $("shortcuts-dialog").showModal();
  $("global-search").oninput = (event) => filterOffice(event.target.value);
  document.addEventListener("keydown", (event) => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      palette.open();
    } else if (event.key === "/" && !typing) {
      event.preventDefault();
      $("global-search").focus();
    } else if (event.key === "?" && !typing) {
      event.preventDefault();
      $("shortcuts-dialog").showModal();
    }
  });
}

async function handleRoute(route) {
  const labels = { overview: "Overview", agents: "Agents", agent: "Agent", terminals: "Terminals", alerts: "Alerts", boards: "Boards", recordings: "Recordings", audit: "Audit", settings: "Settings" };
  $("office-summary").textContent = route.section === "agent" ? route.agent : labels[route.section];
  $("office-summary").className = "";
  if (route.section === "agent") {
    if (agents.detail(route.agent)) await selectAgent(route.agent);
    else {
      $("detail-title").textContent = route.agent;
      $("detail-subtitle").textContent = "Loading agent…";
    }
  }
  if (route.section === "recordings" && !loadedSections.has("recordings")) {
    loadedSections.add("recordings");
    const status = new PanelStatus("recordings-status", () => renderRecordingsSection($("recordings-mount"), status));
    renderRecordingsSection($("recordings-mount"), status);
  }
  if (route.section === "audit" && !loadedSections.has("audit")) {
    loadedSections.add("audit");
    const status = new PanelStatus("audit-status", () => renderAuditSection($("audit-mount"), status));
    renderAuditSection($("audit-mount"), status);
  }
}

async function start() {
  const config = await fetch("/client-config").then((response) => response.json());
  state.demo = Boolean(config.demo);
  messages = new MessagesPanel({ client: config.client });
  lifecycle = new LifecyclePanel({ agents });
  router = new HashRouter({ onRoute: handleRoute });
  $("empty-office-hire").onclick = () => $("hire-dialog").showModal();
  bindTabs();
  bindDemoControls();
  bindGlobalControls();
  $("settings-notification-control").onclick = () => $("notification-control").click();
  $("logout-control").onclick = async () => {
    await fetch("/logout", { method: "POST" });
    location.assign("/");
  };
  router.start();
  $("global-connection").textContent = "live";
  $("global-connection").className = "badge state-ready";
  $("sidebar-live-text").textContent = "Live";
  $("sidebar-live-dot").className = "sidebar-live-dot state-ready";
  await Promise.allSettled([boards.start(), agents.start(), alerts.start(), messages.start()]);
  populateTerminalAgents();
  handleRoute(router.current());
}

start().catch((error) => {
  $("global-connection").textContent = `startup failed: ${error.message}`;
  $("global-connection").className = "badge state-error";
});
