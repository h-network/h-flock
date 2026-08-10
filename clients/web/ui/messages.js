"use strict";

import { absoluteTime, api, catchUp, escapeHtml, forceDemoState, PanelStatus, ResumableFeed } from "./shared.js";

export class MessagesPanel {
  constructor({ client }) {
    this.client = client;
    this.history = new Map();
    this.selected = "";
    this.status = new PanelStatus("messages-status", () => this.restart());
    this.status.loading("Loading mailbox…");
    document.getElementById("composer").onsubmit = (event) => this.send(event);
  }

  async start() {
    try {
      await catchUp({ path: `/agents/${encodeURIComponent(this.client)}/messages`, collection: "messages", feed: "messages", client: this.client, onEvent: (message) => this.add(message) });
      if (![...this.history.values()].some((items) => items.length)) this.status.empty("No replies yet · none is promised");
      this.feed = new ResumableFeed({ path: `/agents/${encodeURIComponent(this.client)}/messages/stream`, eventName: "message", feed: "messages", client: this.client, status: this.status, onEvent: (message) => this.add(message) }).start();
    } catch (error) { this.status.error(error); }
  }

  restart() { this.feed?.close(); this.start(); }

  render(agent) {
    this.selected = agent;
    const root = document.getElementById("messages");
    root.replaceChildren();
    for (const message of this.history.get(agent) || []) root.append(this.element(message));
  }

  add(envelope) {
    if (envelope.kind !== "Message" || typeof envelope.payload?.text !== "string") return;
    const agent = envelope.producer || "unknown";
    if (!this.history.has(agent)) this.history.set(agent, []);
    this.history.get(agent).push(envelope);
    if (this.history.get(agent).length > 100) this.history.get(agent).shift();
    if (agent === this.selected) document.getElementById("messages").append(this.element(envelope));
  }

  element(envelope) {
    const item = document.createElement("li");
    item.className = "reply";
    item.innerHTML = `<strong>${escapeHtml(envelope.producer || "agent")}</strong><span>${escapeHtml(envelope.payload.text)}</span><time datetime="${escapeHtml(envelope.ts || "")}" title="${escapeHtml(absoluteTime(envelope.ts))}">${escapeHtml(envelope.ts ? new Date(envelope.ts).toLocaleTimeString() : "")}</time>`;
    return item;
  }

  async send(event) {
    event.preventDefault();
    const input = document.getElementById("message");
    const text = input.value;
    if (!this.selected || !text.trim()) return;
    input.value = "";
    try {
      await api(`/agents/${encodeURIComponent(this.selected)}/envelopes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, as: this.client }) });
      this.status.ready("Message accepted · no reply is promised");
    } catch (error) {
      input.value = text;
      this.status.error(error);
    }
  }

  demoState(value) { forceDemoState(this.status, value); }
}
