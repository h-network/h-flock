"use strict";

const KEY = "hflock.console.notifications.v1";

export class AlertNotifications {
  constructor() {
    this.enabled = localStorage.getItem(KEY) === "enabled";
    this.muted = localStorage.getItem(KEY) === "muted";
    this.open = new Map();
    this.button = document.getElementById("notification-control");
    this.button.onclick = () => this.toggle();
    this.render();
  }

  async toggle() {
    if (!this.enabled) {
      if (!("Notification" in window)) return this.render("Desktop notifications are unavailable");
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return this.render("Notification permission was not granted");
      this.enabled = true;
      this.muted = false;
      localStorage.setItem(KEY, "enabled");
    } else {
      this.muted = !this.muted;
      localStorage.setItem(KEY, this.muted ? "muted" : "enabled");
      if (this.muted) this.closeAll();
    }
    this.render();
  }

  key(alert) { return `${alert.kind || "alert"}:${alert.agent || alert.account || "tenant"}`; }

  receive(alert) {
    const key = this.key(alert);
    if (alert.resolved || alert.cleared || ["clear", "cleared", "resolved", "healthy"].includes(alert.status)) {
      this.open.get(key)?.close();
      this.open.delete(key);
      return;
    }
    // Alert history has no resolved event today. Permission and mute state are
    // ready, but emitting a notification we cannot retire would lie to users.
  }

  closeAll() { for (const notification of this.open.values()) notification.close(); this.open.clear(); }

  render(message = "") {
    const label = !this.enabled ? "Enable notices" : this.muted ? "Notices muted" : "Notices ready";
    this.button.textContent = label;
    this.button.setAttribute("aria-pressed", String(this.enabled && !this.muted));
    this.button.title = message || "Notification preference is ready; alert delivery awaits a resolvable lifecycle";
  }
}
