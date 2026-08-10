"use strict";

import { TerminalPanel } from "./ui/terminal.js";

const state = { client: "", selected: "", agents: new Map(), history: new Map(), activity: null, messages: null, alerts: null };
const terminal = new TerminalPanel();
const $ = (id) => document.getElementById(id);
const cursorKey = (feed) => `hflock.cursor.${state.client}.${feed}`;

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function stream(path, feed, onEvent) {
  const cursor = localStorage.getItem(cursorKey(feed));
  const join = path.includes("?") ? "&" : "?";
  const source = new EventSource(`/api${path}${cursor ? `${join}after=${encodeURIComponent(cursor)}` : ""}`);
  source.onopen = () => { $("connection").textContent = "live"; };
  source.onerror = () => { $("connection").textContent = "reconnecting"; };
  source.onmessage = receive;
  source.addEventListener(feed.split(":")[0], receive);
  function receive(event) {
    if (!event.data) return;
    const value = JSON.parse(event.data);
    const next = value.cursor || event.lastEventId;
    if (next) localStorage.getItem(cursorKey(feed), next);
    onEvent(value);
  }
  return source;
}

function presenceState(detail) {
  if (detail.blocked) return "blocked";
  return detail.presence?.state || "unknown";
}

function markFor(value) {
  return { working: "●", idle: "○", blocked: "⊘", unknown: "?" }[value] || "?";
}

async function refreshRoster() {
  try {
    const roster = await api("/agents");
    const details = await Promise.all(roster.agents.map(async (name) => {
      try { return [name, await api(`/agents/${encodeURIComponent(name)}`)]; }
      catch (_) { return [name, { presence: { state: "unknown" } }]; }
    }));
    state.agents = new Map(details);
    renderRoster();
    if (state.selected) renderSelectedState();
  } catch (error) {
    $("connection").textContent = error.message;
  }
}

function renderRoster() {
  $("agents").replaceChildren(...Array.from(state.agents, ([name, detail]) => {
    const value = presenceState(detail);
    const button = document.createElement("button");
    button.className = `agent ${value}${name === state.selected ? " selected" : ""}`;
    button.innerHTML = `<span class="mark">${markFor(value)}</span><span>${escapeHtml(name)}</span><span class="muted">${escapeHtml(value)}</span>`;
    button.onclick = () => selectAgent(name);
    return button;
  }));
}

function selectAgent(name) {
  state.selected = name;
  $("agent-title").textContent = name;
  $("message").disabled = false;
  $("send").disabled = false;
  $("chat").replaceChildren();
  for (const entry of state.history.get(name) || []) appendChat(entry.className, entry.text);
  renderRoster();
  renderSelectedState();
  if (state.activity) state.activity.close();
  const feed = `activity:${name}`;
  state.activity = stream(`/agents/${encodeURIComponent(name)}/activity/stream`, feed, renderActivity);

  // If terminal panel is visible, open/connect terminal for the selected agent
  const termPanel = $("terminal-panel");
  if (termPanel && !termPanel.hidden) {
    terminal.connect(name);
  }
}

function renderSelectedState() {
  const detail = state.agents.get(state.selected) || {};
  $("agent-state").textContent = presenceState(detail);
}

function appendChat(className, text) {
  const item = document.createElement("li");
  item.className = className;
  item.textContent = text;
  $("chat").append(item);
  item.scrollIntoView({ block: "end" });
}

function renderActivity(event) {
  if (event.kind !== "tool") return;
  remember(event.agent, "activity", `⚙ ${event.tool}`);
}

function renderMessage(envelope) {
  if (envelope.kind !== "Message" || !envelope.payload || typeof envelope.payload.text !== "string") return;
  const label = envelope.producer || "agent";
  remember(label, "reply", `${label}: ${envelope.payload.text}`);
}

function remember(agent, className, text) {
  if (!state.history.has(agent)) state.history.set(agent, []);
  state.history.get(agent).push({ className, text });
  if (agent === state.selected) appendChat(className, text);
}

function renderAlert(alert) {
  const item = document.createElement("li");
  const age = alert.doing_age_s == null ? "" : ` ${Math.floor(alert.doing_age_s / 60)}m`;
  item.textContent = `${alert.agent || alert.account || "tenant"} ${alert.kind}${age}`;
  $("alerts").prepend(item);
  while ($("alerts").children.length > 30) $("alerts").lastElementChild.remove();
}

async function showBoard() {
  const panel = $("board");
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  try {
    const board = await api("/board");
    const selected = board.agents.find((entry) => entry.agent === state.selected);
    if (!selected) { panel.textContent = "No board for this agent."; return; }
    const columns = ["todo", "doing", "hold", "done"];
    panel.innerHTML = `<div class="columns">${columns.map((column) => `<section><h2>${column}</h2><ul>${(selected[column] || []).map((ticket) => `<li>${escapeHtml(ticket.title || ticket.id || "ticket")}</li>`).join("")}</ul></section>`).join("")}</div>`;
  } catch (error) { panel.textContent = error.message; }
}

function toggleTerminalPanel() {
  const panel = $("terminal-panel");
  panel.hidden = !panel.hidden;
  if (!panel.hidden && state.selected) {
    terminal.connect(state.selected);
  }
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value);
  return node.innerHTML;
}

async function start() {
  state.client = (await fetch("/client-config").then((response) => response.json())).client;
  await refreshRoster();
  setInterval(refreshRoster, 5000);
  state.messages = stream(`/agents/${encodeURIComponent(state.client)}/messages/stream`, "message", renderMessage);
  state.alerts = stream("/alerts/stream", "alert", renderAlert);
  $("composer").onsubmit = async (event) => {
    event.preventDefault();
    const text = $("message").value;
    if (!state.selected || !text.trim()) return;
    $("message").value = "";
    remember(state.selected, "mine", `you: ${text}`);
    try {
      await api(`/agents/${encodeURIComponent(state.selected)}/envelopes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, as: state.client })
      });
    } catch (error) { appendChat("error", `not sent: ${error.message}`); }
  };
  $("boards-toggle").onclick = showBoard;
  if ($("terminal-toggle")) $("terminal-toggle").onclick = toggleTerminalPanel;
}

start().catch((error) => { $("connection").textContent = error.message; });

window.terminal = terminal;
