"use strict";

import { absoluteTime, catchUp, escapeHtml, forceDemoState, PanelStatus, ResumableFeed } from "./shared.js";

export class ActivityPanel {
  constructor() {
    this.agent = "";
    this.count = 0;
    this.status = new PanelStatus("activity-status", () => this.select(this.agent));
    this.status.empty("Select an agent to inspect activity");
  }

  async select(agent) {
    this.feed?.close();
    this.agent = agent;
    this.count = 0;
    document.getElementById("activity").replaceChildren();
    this.status.loading(`Loading ${agent} activity…`);
    const feedName = `activity:${agent}`;
    try {
      await catchUp({ path: `/agents/${encodeURIComponent(agent)}/activity`, collection: "activity", feed: feedName, client: "tenant", onEvent: (event) => this.add(event) });
      if (!this.count) this.status.empty("No observable activity for this agent");
      this.feed = new ResumableFeed({ path: `/agents/${encodeURIComponent(agent)}/activity/stream`, eventName: "activity", feed: feedName, client: "tenant", status: this.status, onEvent: (event) => this.add(event) }).start();
    } catch (error) { this.status.error(error); }
  }

  add(event) {
    if (event.agent && event.agent !== this.agent) return;
    this.count += 1;
    const item = document.createElement("li");
    item.className = `activity-${event.kind || "unknown"}`;
    item.innerHTML = `<time datetime="${escapeHtml(event.ts || "")}" title="${escapeHtml(absoluteTime(event.ts))}">${escapeHtml(event.ts ? new Date(event.ts).toLocaleTimeString() : "")}</time><span class="activity-kind">${escapeHtml(event.kind || "activity")}</span><strong>${escapeHtml(event.kind === "tool" ? event.tool || "tool" : "")}</strong>`;
    const root = document.getElementById("activity");
    root.append(item);
    while (root.children.length > 100) root.firstElementChild.remove();
  }

  demoState(value) { forceDemoState(this.status, value); }
}
