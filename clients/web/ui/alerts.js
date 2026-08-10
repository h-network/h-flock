"use strict";

import { absoluteTime, catchUp, escapeHtml, forceDemoState, PanelStatus, relativeTime, ResumableFeed } from "./shared.js";

export class AlertsPanel {
  constructor({ onCount = () => {}, onResults = () => {}, onAlert = () => {} } = {}) {
    this.items = [];
    this.pending = [];
    this.renderFrame = null;
    this.client = "tenant";
    this.onCount = onCount;
    this.onResults = onResults;
    this.onAlert = onAlert;
    this.filter = "";
    this.status = new PanelStatus("alerts-status", () => this.restart());
  }

  async start() {
    this.status.loading("Loading alert history…");
    try {
      await catchUp({ path: "/alerts", collection: "alerts", feed: "alerts", client: this.client, onEvent: (item) => this.add(item, false) });
      this.onCount(this.items.length);
      if (!this.items.length) this.status.empty("No alerts · office is calm");
      this.feed = new ResumableFeed({ path: "/alerts/stream", eventName: "alert", feed: "alerts", client: this.client, status: this.status, onEvent: (item) => this.add(item) }).start();
    } catch (error) { this.status.error(error); }
  }

  restart() { this.feed?.close(); this.start(); }
  setFilter(value) { this.filter = value.trim().toLowerCase(); this.renderAll(); }

  add(alert, notify = true) {
    this.items.unshift(alert);
    this.items = this.items.slice(0, 300);
    this.pending.push(alert);
    if (notify) this.onAlert(alert);
    if (this.renderFrame == null) this.renderFrame = requestAnimationFrame(() => this.flush());
  }

  element(alert, repeats = 1) {
    const item = document.createElement("li");
    const severity = ["blocked", "stalled"].includes(alert.kind) ? "critical" : alert.kind === "credential" ? "warning" : "information";
    item.className = `alert alert-${alert.kind || "unknown"} severity-${severity}`;
    const subject = alert.agent || alert.account || "tenant";
    const facts = [alert.cli, alert.status, alert.ticket, alert.unconsumed_s == null ? "" : `${alert.unconsumed_s}s unconsumed`, alert.doing_age_s == null ? "" : `${Math.floor(alert.doing_age_s / 60)}m open`].filter(Boolean);
    const icon = severity === "critical" ? "!" : severity === "warning" ? "△" : "i";
    item.innerHTML = `<span class="alert-icon" aria-hidden="true">${icon}</span><strong>${escapeHtml(alert.kind || "alert")}</strong><span>${escapeHtml(subject)}</span><span>${escapeHtml(facts.join(" · "))}</span><span class="repeat-count" title="${repeats} matching events">${repeats > 1 ? `×${repeats}` : ""}</span><time datetime="${escapeHtml(alert.ts || "")}" title="${escapeHtml(absoluteTime(alert.ts))}">${escapeHtml(relativeTime(alert.ts))}</time>`;
    return item;
  }

  flush() {
    this.renderFrame = null;
    const root = document.getElementById("alerts");
    this.pending = [];
    this.renderAll();
    this.onCount(this.items.length);
  }

  matches(alert) {
    return !this.filter || Object.values(alert).some((value) => String(value ?? "").toLowerCase().includes(this.filter));
  }

  renderAll() {
    const matches = this.items.filter((alert) => this.matches(alert));
    const root = document.getElementById("alerts");
    if (!matches.length && this.filter) {
      this.onResults({ groups: 0, alerts: 0 });
      root.innerHTML = `<li class="filtered-empty">No alerts match “${escapeHtml(this.filter)}”</li>`;
    }
    else {
      const groups = new Map();
      for (const alert of matches) {
        const key = `${alert.kind || "alert"}:${alert.agent || alert.account || "tenant"}:${alert.status || ""}`;
        if (!groups.has(key)) groups.set(key, { alert, repeats: 0 });
        groups.get(key).repeats += 1;
      }
      this.onResults({ groups: groups.size, alerts: matches.length });
      root.replaceChildren(...Array.from(groups.values(), ({ alert, repeats }) => this.element(alert, repeats)));
    }
  }

  demoState(value) { forceDemoState(this.status, value); }
}
