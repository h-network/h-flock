"use strict";

import { absoluteTime, api, classifyFailure, escapeHtml, forceDemoState, PanelStatus, relativeTime } from "./shared.js";

export class AgentsPanel {
  constructor({ onSelect, onSummary }) {
    this.onSelect = onSelect;
    this.onSummary = onSummary;
    this.details = new Map();
    this.boards = new Map();
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

  async refresh() {
    try {
      const roster = await api("/agents");
      const names = (roster.agents || []).map((value) => typeof value === "string" ? value : value.agent);
      const details = await Promise.all(names.map(async (agent) => [agent, await api(`/agents/${encodeURIComponent(agent)}`)]));
      this.details = new Map(details);
      if (this.details.size) this.status.ready(`${this.details.size} participants`);
      else this.status.empty("No enrolled participants");
      const blocked = Array.from(this.details.values()).filter((detail) => detail.presence?.state === "blocked").length;
      this.onSummary(`${this.details.size} participants${blocked ? ` · ${blocked} blocked` : " · no blocked agents"}`);
      this.render();
    } catch (error) { classifyFailure(this.status, error, this.details.size > 0); }
  }

  render() {
    const root = document.getElementById("agents");
    if (!this.details.size) { root.replaceChildren(); return; }
    root.replaceChildren(...Array.from(this.details, ([agent, detail]) => {
      const presence = detail.presence?.state || "unknown";
      const doing = this.boards.get(agent)?.doing || [];
      const ticket = typeof doing[0] === "string" ? { title: doing[0] } : doing[0];
      const button = document.createElement("button");
      button.type = "button";
      button.className = `agent-row state-${presence}${agent === this.selected ? " selected" : ""}`;
      button.setAttribute("aria-label", `${agent}, ${presence}${presence === "blocked" ? ", action required" : ""}`);
      button.innerHTML = `<span class="state-icon" aria-hidden="true">${{ working: "●", idle: "○", blocked: "⊘", unknown: "?" }[presence] || "?"}</span><strong>${escapeHtml(agent)}</strong><span class="presence-label">${escapeHtml(presence)}${presence === "blocked" ? " · ACT" : ""}</span><span class="vab">${escapeHtml(detail.vab || "unknown VAB")}</span><span class="ticket">${ticket ? escapeHtml(ticket.title || ticket.id || "open ticket") : "No open ticket"}</span><span class="age">${ticket?.started_ts ? escapeHtml(relativeTime(ticket.started_ts)) : ""}</span><time title="${escapeHtml(detail.presence?.last_activity ? absoluteTime(detail.presence.last_activity) : "No activity recorded")}">${detail.presence?.last_activity ? escapeHtml(relativeTime(detail.presence.last_activity)) : "activity unknown"}</time>`;
      button.onclick = () => { this.selected = agent; this.onSelect(agent); };
      return button;
    }));
  }

  demoState(value) { forceDemoState(this.status, value); }
}
