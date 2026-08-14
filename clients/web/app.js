"use strict";

import { AgentsPanel } from "./ui/agents.js";
import { AlertsPanel } from "./ui/alerts.js";
import { BoardsPanel } from "./ui/boards.js";
import { ActivityPanel } from "./ui/activity.js";
import { MessagesPanel } from "./ui/messages.js";
import { LifecyclePanel } from "./ui/lifecycle.js";
import { globalTerminalWorkspace } from "./ui/terminal.js";
import { Preferences } from "./ui/preferences.js";
import { CommandPalette } from "./ui/palette.js";
import { AlertNotifications } from "./ui/notifications.js";
import { HashRouter } from "./ui/router.js";
import { renderRecordingsSection } from "./ui/recordings.js";
import { renderAuditSection } from "./ui/audit.js";
import { PanelStatus } from "./ui/shared.js";

const $ = (id) => document.getElementById(id);
const state = { selected: "", secondary: "", demo: false, roster: null, alertCount: null, results: { agents: 0, alerts: 0, boards: 0 } };
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
    if (state.selected) messages?.setPresence(agents.detail(state.selected));
  },
});
let messages;
const activity = new ActivityPanel({ onEvent: (event) => messages?.addActivity(event) });
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
  const names = agents.names().filter((name) => agents.detail(name)?.port_type === "tmux");
  for (let index = 1; index <= 4; index += 1) {
    const select = $(`cell-agent-${index}`);
    if (!select) continue;
    const current = select.value;
    select.replaceChildren(new Option("Select Agent", ""), ...names.map((name) => new Option(name, name)));
    if (names.includes(current)) select.value = current;
  }
  if (router?.current().section === "terminals") globalTerminalWorkspace.renderWorkspace($("terminals-workspace-mount"), names);
}

function connectAgentTerminal(agent) {
  if (!globalTerminalWorkspace.openTabs.includes(agent)) globalTerminalWorkspace.openTabs.push(agent);
  globalTerminalWorkspace.activeAgent = agent;
  globalTerminalWorkspace.attachWatchPanel(agent, $("terminal-container"));
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

function showSecondary(name = "") {
  state.secondary = state.secondary === name ? "" : name;
  const views = { watch: "terminal-panel", board: "agent-board-view", lifecycle: "lifecycle-view" };
  const buttons = { watch: "watch-agent", board: "show-agent-board", lifecycle: "show-agent-lifecycle" };
  for (const [key, id] of Object.entries(views)) {
    const selected = state.secondary === key;
    $(id).hidden = !selected;
    $(buttons[key]).setAttribute("aria-expanded", String(selected));
  }
  $("detail").classList.toggle("with-secondary", Boolean(state.secondary));
  if (state.secondary === "watch" && state.selected) connectAgentTerminal(state.selected);
  if (state.secondary === "board" && state.selected) boards.renderAgent(state.selected);
}

async function selectAgent(agent) {
  state.selected = agent;
  preferences.rememberAgent(agent);
  const detail = agents.detail(agent);
  $("detail-title").textContent = agent;
  $("detail-subtitle").textContent = `${detail?.port_type || "unknown port_type"} · ${detail?.presence?.state || "unknown"}`;
  $("detail-title").focus();
  agents.render();
  lifecycle.select(agent);
  messages.setPresence(detail);
  await messages.render(agent);
  await activity.select(agent);
  boards.renderAgent(agent);
  if (state.secondary === "watch") connectAgentTerminal(agent);
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
  if (state.selected && agents.detail(state.selected)?.port_type === "tmux") {
    commands.push(
      { label: `Pause ${state.selected}`, hint: "Lifecycle", keywords: "stop cli keep identity", run: () => lifecycle.control("PauseAgent", "Pause accepted · messages will queue until resume") },
      { label: `Resume ${state.selected}`, hint: "Lifecycle", keywords: "start cli drain", run: () => lifecycle.control("ResumeAgent", "Resume accepted · queued messages will drain") },
      { label: `Retire ${state.selected}`, hint: "Destructive · confirmation required", keywords: "remove let go", run: () => lifecycle.openRetire() },
    );
  }
  return commands;
}

function bindAgentControls() {
  $("watch-agent").onclick = () => showSecondary("watch");
  $("show-agent-board").onclick = () => showSecondary("board");
  $("show-agent-lifecycle").onclick = () => showSecondary("lifecycle");
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.secondary) showSecondary(state.secondary);
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
  if (route.section === "terminals") {
    const names = agents.names().filter((name) => agents.detail(name)?.port_type === "tmux");
    globalTerminalWorkspace.renderWorkspace($("terminals-workspace-mount"), names);
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
  messages = new MessagesPanel({ client: config.client, isAgent: (source) => agents.detail(source)?.port_type === "tmux" });
  lifecycle = new LifecyclePanel({ agents });
  router = new HashRouter({ onRoute: handleRoute });
  $("empty-office-hire").onclick = () => $("hire-dialog").showModal();
  bindAgentControls();
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
