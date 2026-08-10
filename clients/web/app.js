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

const $ = (id) => document.getElementById(id);
const state = { selected: "", tab: "activity", demo: false, roster: null, alertCount: null, results: { agents: 0, alerts: 0, boards: 0 } };
const terminal = new TerminalPanel();
const preferences = new Preferences();
const notifications = new AlertNotifications();
const updateResult = (panel) => (count) => { state.results[panel] = count; renderSearchSummary(); };
const boards = new BoardsPanel({ onBoards: (value) => agents.setBoards(value), onResults: updateResult("boards") });
const agents = new AgentsPanel({
  onSelect: (agent) => selectAgent(agent),
  onResults: updateResult("agents"),
  onRoster: (summary) => {
    state.roster = summary;
    $("empty-office").hidden = summary.staffed !== 0;
    updateOfficeSummary();
    populateTerminalAgents();
  },
});
const activity = new ActivityPanel();
let messages;
let lifecycle;
const alerts = new AlertsPanel({
  onCount: (count) => { state.alertCount = count; updateOfficeSummary(); },
  onResults: updateResult("alerts"),
  onAlert: (alert) => notifications.receive(alert),
});
let palette;

function renderSearchSummary() {
  const query = $("global-search")?.value.trim();
  $("search-results-summary").textContent = query
    ? `${state.results.agents} agents · ${state.results.alerts} alerts · ${state.results.boards} tickets`
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
  $("office-summary").textContent = `${working} working · ${blocked} blocked · ${alertsText}`;
  $("office-summary").className = blocked || state.alertCount ? "summary-attention" : "summary-calm";
  $("overview-working").textContent = String(working);
  $("overview-blocked").textContent = String(blocked);
  $("overview-alerts").textContent = state.alertCount == null ? "—" : String(state.alertCount);
  $("overview-blocked-action").disabled = blocked === 0;
}

function activateTab(name) {
  state.tab = name;
  for (const tab of ["activity", "terminal", "messages"]) {
    const selected = tab === name;
    const button = $(`${tab}-tab`);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    const view = tab === "terminal" ? $("terminal-panel") : $(`${tab}-view`);
    view.hidden = !selected;
  }
  if (name === "terminal" && state.selected) terminal.connect(state.selected);
}

async function selectAgent(agent) {
  state.selected = agent;
  preferences.rememberAgent(agent);
  const detail = agents.detail(agent);
  $("detail-title").textContent = agent;
  $("detail-overview").hidden = true;
  $("detail-subtitle").textContent = `${detail?.vab || "unknown VAB"} · ${detail?.presence?.state || "unknown"}`;
  $("detail-title").focus();
  $("message").disabled = false;
  $("send").disabled = false;
  agents.render();
  lifecycle.select(agent);
  await activity.select(agent);
  messages.render(agent);
  if (state.tab === "terminal") terminal.connect(agent);
}

function commandList() {
  const commands = [
    { label: "Hire an agent", hint: "Lifecycle", keywords: "start enrol", run: () => $("hire-dialog").showModal() },
    { label: "Open alerts", hint: "Panel", keywords: "filter warning", run: () => $("alerts-panel").scrollIntoView({ behavior: "smooth" }) },
    { label: "Open task board", hint: "Panel", keywords: "tickets work", run: () => $("boards-panel").scrollIntoView({ behavior: "smooth" }) },
    { label: "Search the office", hint: "/", keywords: "filter agents alerts boards", run: () => $("global-search").focus() },
    { label: "Display preferences", hint: "Theme · density", keywords: "compact light dark size", run: () => $("preferences-dialog").showModal() },
    { label: "Keyboard shortcuts", hint: "?", keywords: "help keys", run: () => $("shortcuts-dialog").showModal() },
  ];
  for (const agent of agents.names()) {
    commands.push({ label: `Open ${agent}`, hint: "Agent", keywords: `${agents.detail(agent)?.presence?.state || "unknown"} terminal messages`, run: () => selectAgent(agent) });
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
  const names = ["activity", "terminal", "messages"];
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
    if (blocked) selectAgent(blocked);
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

async function start() {
  const config = await fetch("/client-config").then((response) => response.json());
  state.demo = Boolean(config.demo);
  messages = new MessagesPanel({ client: config.client });
  lifecycle = new LifecyclePanel({ agents });
  $("empty-office-hire").onclick = () => $("hire-dialog").showModal();
  bindTabs();
  bindDemoControls();
  bindGlobalControls();
  $("global-connection").textContent = "live";
  $("global-connection").className = "badge state-ready";
  await Promise.allSettled([boards.start(), agents.start(), alerts.start(), messages.start()]);
  populateTerminalAgents();
  if (preferences.value.selectedAgent && agents.detail(preferences.value.selectedAgent)) await selectAgent(preferences.value.selectedAgent);
}

start().catch((error) => {
  $("global-connection").textContent = `startup failed: ${error.message}`;
  $("global-connection").className = "badge state-error";
});
