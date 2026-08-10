"use strict";

import { absoluteTime, api, classifyFailure, escapeHtml, forceDemoState, PanelStatus, relativeTime } from "./shared.js";

const presenceOrder = ["blocked", "unknown", "pending", "working", "idle"];

export class AgentsPanel {
  constructor({ onSelect, onRoster, onResults = () => {} }) {
    this.onSelect = onSelect;
    this.onRoster = onRoster;
    this.onResults = onResults;
    this.filter = "";
    this.details = new Map();
    this.boards = new Map();
    this.pending = new Set();
    this.selected = "";
    this.sort = { key: "presence", direction: "asc" };
    this.status = new PanelStatus("agents-status", () => this.refresh());
  }

  async start() {
    this.status.loading("Loading roster…");
    await this.refresh();
    this.timer = setInterval(() => this.refresh(), 5000);
  }

  setBoards(boards) { this.boards = boards; this.render(); }
  detail(agent) { return this.details.get(agent); }
  names() { return Array.from(this.details.keys()); }
  setFilter(value) { this.filter = value.trim().toLowerCase(); this.render(); }

  async refresh() {
    try {
      const roster = await api("/agents");
      const names = (roster.agents || []).map((value) => typeof value === "string" ? value : value.agent);
      const details = await Promise.all(names.map(async (agent) => [agent, await api(`/agents/${encodeURIComponent(agent)}`)]));
      this.details = new Map(details);
      for (const agent of names) this.pending.delete(agent);
      for (const agent of this.pending) this.details.set(agent, { vab: "tmux", presence: { state: "pending" } });
      if (this.details.size) this.status.ready(`${this.details.size} participants`);
      else this.status.empty("No enrolled participants");
      this.publishRoster();
      this.render();
    } catch (error) { classifyFailure(this.status, error, this.details.size > 0); }
  }

  addPending(agent) {
    this.pending.add(agent);
    this.details.set(agent, { vab: "tmux", presence: { state: "pending" } });
    this.publishRoster();
    this.render();
  }

  publishRoster() {
    const counts = Object.fromEntries(presenceOrder.map((presence) => [presence, 0]));
    let staffed = 0;
    for (const detail of this.details.values()) {
      const presence = presenceOrder.includes(detail.presence?.state) ? detail.presence.state : "unknown";
      if (detail.vab === "tmux") {
        staffed += 1;
        counts[presence] += 1;
      }
    }
    this.onRoster({ total: this.details.size, staffed, ...counts });
  }

  render() {
    const root = document.getElementById("agents");
    if (!this.details.size) { root.replaceChildren(); return; }
    const matches = ([agent, detail]) => {
      if (!this.filter) return true;
      const doing = this.boards.get(agent)?.doing || [];
      return [agent, detail.vab, detail.presence?.state, ...doing.map((value) => typeof value === "string" ? value : `${value?.id || ""} ${value?.title || ""}`)]
        .some((value) => String(value || "").toLowerCase().includes(this.filter));
    };
    const valueFor = ([agent, detail], key) => {
      const doing = this.boards.get(agent)?.doing || [];
      const task = typeof doing[0] === "string" ? { title: doing[0] } : doing[0];
      if (key === "agent") return agent;
      if (key === "presence") return presenceOrder.indexOf(detail.presence?.state || "unknown");
      if (key === "vab") return detail.vab || "";
      if (key === "task") return task?.title || task?.id || "";
      if (key === "started") return task?.started_ts || "";
      return detail.presence?.last_activity || "";
    };
    const multiplier = this.sort.direction === "asc" ? 1 : -1;
    const entries = Array.from(this.details).filter(matches).sort((left, right) => {
      const a = valueFor(left, this.sort.key);
      const b = valueFor(right, this.sort.key);
      const compared = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
      return (compared || left[0].localeCompare(right[0])) * multiplier;
    });
    this.onResults(entries.length);
    if (!entries.length) {
      root.innerHTML = `<p class="filtered-empty">No agents match “${escapeHtml(this.filter)}”</p>`;
      return;
    }
    const columns = [["agent", "Agent"], ["presence", "Presence"], ["vab", "Host"], ["task", "Open task"], ["started", "Started"], ["activity", "Last activity"]];
    const table = document.createElement("table");
    table.className = "roster-table";
    table.innerHTML = `<thead><tr>${columns.map(([key, label]) => `<th scope="col"><button type="button" data-sort="${key}" aria-sort="${this.sort.key === key ? (this.sort.direction === "asc" ? "ascending" : "descending") : "none"}">${label}<span aria-hidden="true">${this.sort.key === key ? (this.sort.direction === "asc" ? "↑" : "↓") : "↕"}</span></button></th>`).join("")}</tr></thead><tbody>${entries.map(([agent, detail]) => this.agentRow(agent, detail)).join("")}</tbody>`;
    root.replaceChildren(table);
    for (const button of table.querySelectorAll("[data-sort]")) button.onclick = () => {
      const key = button.dataset.sort;
      this.sort = { key, direction: this.sort.key === key && this.sort.direction === "asc" ? "desc" : "asc" };
      this.render();
    };
    const agentButtons = Array.from(table.querySelectorAll("[data-agent]"));
    for (const button of agentButtons) {
      button.onclick = () => { this.selected = button.dataset.agent; this.onSelect(this.selected); };
      button.onkeydown = (event) => {
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        let index = agentButtons.indexOf(button);
        if (event.key === "ArrowDown") index = (index + 1) % agentButtons.length;
        else if (event.key === "ArrowUp") index = (index + agentButtons.length - 1) % agentButtons.length;
        else if (event.key === "Home") index = 0;
        else index = agentButtons.length - 1;
        event.preventDefault();
        agentButtons[index].focus();
      };
    }
  }

  agentRow(agent, detail) {
    const presence = detail.presence?.state || "unknown";
    const doing = this.boards.get(agent)?.doing || [];
    const ticket = typeof doing[0] === "string" ? { title: doing[0] } : doing[0];
    const stateLabel = `${presence}${presence === "blocked" ? " · action required" : ""}`;
    const lastActivity = detail.presence?.last_activity;
    return `<tr class="agent-row state-${presence}${agent === this.selected ? " selected" : ""}"><th scope="row"><button type="button" class="agent-link" data-agent="${escapeHtml(agent)}"><span class="state-icon" aria-hidden="true">${{ working: "●", idle: "○", blocked: "⊘", unknown: "?", pending: "…" }[presence] || "?"}</span><span>${escapeHtml(agent)}</span></button></th><td><span class="presence-label"${presence === "blocked" ? ' title="Action required"' : ""}>${escapeHtml(stateLabel)}</span></td><td class="vab">${escapeHtml(detail.vab || "unknown")}</td><td class="ticket">${presence === "pending" ? "Roster and window are converging" : ticket ? escapeHtml(ticket.title || ticket.id || "open ticket") : "No open ticket"}</td><td class="age">${ticket?.started_ts ? `<time datetime="${escapeHtml(ticket.started_ts)}" title="${escapeHtml(absoluteTime(ticket.started_ts))}">${escapeHtml(relativeTime(ticket.started_ts))}</time>` : "—"}</td><td><time datetime="${escapeHtml(lastActivity || "")}" title="${escapeHtml(lastActivity ? absoluteTime(lastActivity) : "No activity recorded")}">${lastActivity ? escapeHtml(relativeTime(lastActivity)) : "Unknown"}</time></td></tr>`;
  }

  demoState(value) { forceDemoState(this.status, value); }
}
