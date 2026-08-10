"use strict";

import { absoluteTime, catchUp, escapeHtml, forceDemoState, PanelStatus, relativeTime, ResumableFeed } from "./shared.js";

export class AlertsPanel {
  constructor() {
    this.items = [];
    this.client = "tenant";
    this.status = new PanelStatus("alerts-status", () => this.restart());
  }

  async start() {
    this.status.loading("Loading alert history…");
    try {
      await catchUp({ path: "/alerts", collection: "alerts", feed: "alerts", client: this.client, onEvent: (item) => this.add(item) });
      if (!this.items.length) this.status.empty("No alerts · office is calm");
      this.feed = new ResumableFeed({ path: "/alerts/stream", eventName: "alert", feed: "alerts", client: this.client, status: this.status, onEvent: (item) => this.add(item) }).start();
    } catch (error) { this.status.error(error); }
  }

  restart() { this.feed?.close(); this.start(); }

  add(alert) {
    this.items.unshift(alert);
    this.items = this.items.slice(0, 300);
    const root = document.getElementById("alerts");
    const item = document.createElement("li");
    item.className = `alert alert-${alert.kind || "unknown"}`;
    const subject = alert.agent || alert.account || "tenant";
    const facts = [alert.cli, alert.status, alert.ticket, alert.unconsumed_s == null ? "" : `${alert.unconsumed_s}s unconsumed`, alert.doing_age_s == null ? "" : `${Math.floor(alert.doing_age_s / 60)}m open`].filter(Boolean);
    item.innerHTML = `<span class="alert-icon" aria-hidden="true">⚠</span><strong>${escapeHtml(alert.kind || "alert")}</strong><span>${escapeHtml(subject)}</span><span>${escapeHtml(facts.join(" · "))}</span><time datetime="${escapeHtml(alert.ts || "")}" title="${escapeHtml(absoluteTime(alert.ts))}">${escapeHtml(relativeTime(alert.ts))}</time>`;
    root.prepend(item);
    while (root.children.length > 300) root.lastElementChild.remove();
  }

  demoState(value) { forceDemoState(this.status, value); }
}
