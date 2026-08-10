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
    const grouped = new Map();
    for (const [agent, detail] of this.details) {
      const presence = presenceOrder.includes(detail.presence?.state) ? detail.presence.state : "unknown";
      if (!grouped.has(presence)) grouped.set(presence, []);
      grouped.get(presence).push([agent, detail]);
    }
    const matches = ([agent, detail]) => {
      if (!this.filter) return true;
      const doing = this.boards.get(agent)?.doing || [];
      return [agent, detail.vab, detail.presence?.state, ...doing.map((value) => typeof value === "string" ? value : `${value?.id || ""} ${value?.title || ""}`)]
        .some((value) => String(value || "").toLowerCase().includes(this.filter));
    };
    for (const [presence, values] of grouped) grouped.set(presence, values.filter(matches));
    const entries = presenceOrder.flatMap((presence) => (grouped.get(presence) || []).sort(([left], [right]) => left.localeCompare(right)));
    this.onResults(entries.length);
    if (!entries.length) {
      root.innerHTML = `<p class="filtered-empty">No agents match “${escapeHtml(this.filter)}”</p>`;
      return;
    }
    const buttons = new Map(entries.map(([agent, detail], index) => [agent, this.agentButton(root, agent, detail, index === 0)]));
    root.replaceChildren(...presenceOrder.filter((presence) => grouped.get(presence)?.length).map((presence) => {
      const group = document.createElement("section");
      const heading = document.createElement("h3");
      heading.id = `agents-${presence}`;
      heading.className = `agent-group-heading state-${presence}`;
      heading.textContent = `${presence}${presence === "blocked" ? " · action required" : ""} · ${grouped.get(presence).length}`;
      group.className = `agent-group agent-group-${presence}`;
      group.setAttribute("role", "group");
      group.setAttribute("aria-labelledby", heading.id);
      group.append(heading, ...grouped.get(presence).sort(([left], [right]) => left.localeCompare(right)).map(([agent]) => buttons.get(agent)));
      return group;
    }));
  }

  agentButton(root, agent, detail, first) {
    const presence = detail.presence?.state || "unknown";
    const doing = this.boards.get(agent)?.doing || [];
    const ticket = typeof doing[0] === "string" ? { title: doing[0] } : doing[0];
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(agent === this.selected));
    button.className = `agent-row state-${presence}${agent === this.selected ? " selected" : ""}`;
    button.setAttribute("aria-label", `${agent}, ${presence}${presence === "blocked" ? ", action required" : ""}`);
    button.tabIndex = agent === this.selected || (!this.selected && first) ? 0 : -1;
    button.innerHTML = `<span class="state-icon" aria-hidden="true">${{ working: "●", idle: "○", blocked: "⊘", unknown: "?", pending: "…" }[presence] || "?"}</span><strong>${escapeHtml(agent)}</strong><span class="presence-label">${escapeHtml(presence)}${presence === "blocked" ? " · ACT" : ""}</span><span class="vab">${escapeHtml(detail.vab || "unknown VAB")}</span><span class="ticket">${presence === "pending" ? "Roster and window are converging" : ticket ? escapeHtml(ticket.title || ticket.id || "open ticket") : "No open ticket"}</span><span class="age">${ticket?.started_ts ? escapeHtml(relativeTime(ticket.started_ts)) : ""}</span><time title="${escapeHtml(detail.presence?.last_activity ? absoluteTime(detail.presence.last_activity) : "No activity recorded")}">${detail.presence?.last_activity ? escapeHtml(relativeTime(detail.presence.last_activity)) : "activity unknown"}</time>`;
    button.onclick = () => { this.selected = agent; this.onSelect(agent); };
    button.onkeydown = (event) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const rows = Array.from(root.querySelectorAll(".agent-row"));
      let index = rows.indexOf(button);
      if (event.key === "ArrowDown") index = (index + 1) % rows.length;
      else if (event.key === "ArrowUp") index = (index + rows.length - 1) % rows.length;
      else if (event.key === "Home") index = 0;
      else index = rows.length - 1;
      event.preventDefault();
      rows[index].focus();
    };
    return button;
  }

  demoState(value) { forceDemoState(this.status, value); }
}
