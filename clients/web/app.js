"use strict";

import { AgentsPanel } from "./ui/agents.js";
import { AlertsPanel } from "./ui/alerts.js";
import { BoardsPanel } from "./ui/boards.js";
import { ActivityPanel } from "./ui/activity.js";
import { MessagesPanel } from "./ui/messages.js";
import { TerminalPanel } from "./ui/terminal.js";

const $ = (id) => document.getElementById(id);
const state = { selected: "", tab: "activity", demo: false };
const terminal = new TerminalPanel();
const boards = new BoardsPanel({ onBoards: (value) => agents.setBoards(value) });
const agents = new AgentsPanel({
  onSelect: (agent) => selectAgent(agent),
  onSummary: (text) => { $("office-summary").textContent = text; },
});
const activity = new ActivityPanel();
let messages;
const alerts = new AlertsPanel();

function activateTab(name) {
  state.tab = name;
  for (const tab of ["activity", "terminal", "messages"]) {
    const selected = tab === name;
    $(`${tab}-tab`).setAttribute("aria-selected", String(selected));
    const view = tab === "terminal" ? $("terminal-panel") : $(`${tab}-view`);
    view.hidden = !selected;
  }
  if (name === "terminal" && state.selected) terminal.connect(state.selected);
}

async function selectAgent(agent) {
  state.selected = agent;
  const detail = agents.detail(agent);
  $("detail-title").textContent = agent;
  $("detail-subtitle").textContent = `${detail?.vab || "unknown VAB"} · ${detail?.presence?.state || "unknown"}`;
  $("message").disabled = false;
  $("send").disabled = false;
  agents.render();
  await activity.select(agent);
  messages.render(agent);
  if (state.tab === "terminal") terminal.connect(agent);
}

function bindTabs() {
  for (const name of ["activity", "terminal", "messages"]) {
    $(`${name}-tab`).onclick = () => activateTab(name);
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

async function start() {
  const config = await fetch("/client-config").then((response) => response.json());
  state.demo = Boolean(config.demo);
  messages = new MessagesPanel({ client: config.client });
  bindTabs();
  bindDemoControls();
  $("global-connection").textContent = "live";
  $("global-connection").className = "badge state-ready";
  await Promise.allSettled([boards.start(), agents.start(), alerts.start(), messages.start()]);
}

start().catch((error) => {
  $("global-connection").textContent = `startup failed: ${error.message}`;
  $("global-connection").className = "badge state-error";
});
