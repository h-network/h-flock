"use strict";

import { absoluteTime, api, escapeHtml, forceDemoState, PanelStatus, relativeTime, ResumableFeed } from "./shared.js";

export class MessagesPanel {
  constructor({ client, isAgent = () => false }) {
    this.client = client;
    this.isAgent = isAgent;
    this.history = new Map();
    this.selected = "";
    this.sentHistory = [];
    this.historyIndex = 0;
    this.status = new PanelStatus("messages-status", () => this.restart());
    this.status.loading("Loading mailbox…");
    document.getElementById("composer").onsubmit = (event) => this.send(event);
    document.getElementById("message").onkeydown = (event) => this.keydown(event);
  }

  async start() {
    try {
      // The live feed is the client's inbox. Retained two-sided history is loaded
      // per selected agent by render(), so refresh never opens an empty thread.
      this.feed = new ResumableFeed({ path: `/agents/${encodeURIComponent(this.client)}/messages/stream`, eventName: "message", feed: "messages", client: this.client, status: this.status, onEvent: (message) => this.add(message) }).start();
    } catch (error) { this.status.error(error); }
  }

  restart() { this.feed?.close(); this.start(); }

  async render(agent) {
    this.selected = agent;
    const root = document.getElementById("messages");
    root.replaceChildren();
    this.status.loading(`Loading conversation with ${agent}…`);
    try {
      const value = await api(`/agents/${encodeURIComponent(agent)}/conversation`);
      const items = (value.messages || []).filter((message) => message.kind === "Message" && typeof message.payload?.text === "string");
      this.history.set(agent, items.slice(-100));
      for (const message of this.history.get(agent)) root.append(this.element(message));
      if (items.length) this.status.ready(`${items.length} messages · live`);
      else this.status.empty("No messages yet · start the conversation below");
    } catch (error) { this.status.error(error); }
  }

  add(envelope) {
    if (envelope.kind !== "Message" || typeof envelope.payload?.text !== "string") return;
    const agent = envelope.source || "unknown";
    envelope.direction ||= "inbound";
    if (!this.history.has(agent)) this.history.set(agent, []);
    this.history.get(agent).push(envelope);
    if (this.history.get(agent).length > 100) this.history.get(agent).shift();
    if (agent === this.selected) document.getElementById("messages").append(this.element(envelope));
  }

  element(envelope) {
    const item = document.createElement("li");
    const outbound = envelope.direction === "outbound";
    const source = envelope.source || "unknown";
    const operator = outbound && (source === "operator" || source === this.client);
    const enrolledAgent = !outbound && this.isAgent(source);
    item.className = `conversation-message ${operator ? "message-operator" : enrolledAgent ? "message-agent" : "message-client"}`;
    const speaker = operator ? "You" : enrolledAgent ? source : `Claimed by ${source}`;
    const trust = operator ? "recorded by this console" : enrolledAgent ? "unverified source · enrolled agent address" : "unverified client identity";
    item.innerHTML = `<header><strong>${escapeHtml(speaker)}</strong><span>${escapeHtml(trust)}</span><time datetime="${escapeHtml(envelope.ts || "")}" title="${escapeHtml(absoluteTime(envelope.ts))}">${escapeHtml(relativeTime(envelope.ts))}</time></header><p>${escapeHtml(envelope.payload.text)}</p>`;
    return item;
  }

  addActivity(event) {
    if (event.agent && event.agent !== this.selected) return;
    const root = document.getElementById("messages");
    if (event.kind !== "tool") return;
    const tool = String(event.tool || "tool");
    let run = root.lastElementChild?.classList.contains("conversation-activity") ? root.lastElementChild : null;
    if (!run) {
      run = document.createElement("li");
      run.className = "conversation-activity";
      run.innerHTML = `<header><strong>${escapeHtml(this.selected)}</strong><span>observable work · tool names only</span></header><ol></ol>`;
      root.append(run);
    }
    const list = run.querySelector("ol");
    const last = list.lastElementChild;
    if (last?.dataset.tool === tool) {
      const count = Number(last.dataset.count || "1") + 1;
      last.dataset.count = String(count);
      last.querySelector("span").textContent = `×${count}`;
    } else {
      const row = document.createElement("li");
      row.dataset.tool = tool;
      row.dataset.count = "1";
      row.innerHTML = `<span aria-hidden="true">⚙</span><strong>${escapeHtml(tool)}</strong><span></span>`;
      list.append(row);
    }
    root.scrollTop = root.scrollHeight;
  }

  setPresence(detail = {}) {
    const presence = detail.presence?.state || "unknown";
    const banner = document.getElementById("conversation-presence");
    const input = document.getElementById("message");
    const send = document.getElementById("send");
    const messages = {
      blocked: "Blocked · not accepting messages. Resolve the blocked condition or use Watch to complete an interactive prompt.",
      unknown: "Presence unknown · you may send, but a reply may never come.",
      working: "Working · messages are accepted and queued; no reply is promised.",
      idle: "Available · messages are accepted; no reply is promised.",
      pending: "Starting · wait for the agent window before sending.",
    };
    banner.className = `conversation-presence state-${presence}`;
    banner.textContent = messages[presence] || messages.unknown;
    const disabled = presence === "blocked" || presence === "pending";
    input.disabled = disabled;
    send.disabled = disabled;
    input.placeholder = disabled ? `${this.selected} is not accepting messages` : `Message ${this.selected}…`;
  }

  async send(event) {
    event.preventDefault();
    const input = document.getElementById("message");
    const text = input.value;
    if (!this.selected || !text.trim()) return;
    this.sentHistory.push(text);
    this.sentHistory = this.sentHistory.slice(-50);
    this.historyIndex = this.sentHistory.length;
    input.value = "";
    try {
      await api(`/agents/${encodeURIComponent(this.selected)}/envelopes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, as: this.client }) });
      const outgoing = { ts: new Date().toISOString(), kind: "Message", source: "operator", destination: this.selected, direction: "outbound", payload: { text } };
      if (!this.history.has(this.selected)) this.history.set(this.selected, []);
      this.history.get(this.selected).push(outgoing);
      document.getElementById("messages").append(this.element(outgoing));
      this.status.ready("Message accepted · no reply is promised");
    } catch (error) {
      input.value = text;
      this.status.error(error);
    }
  }

  keydown(event) {
    const input = event.currentTarget;
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      document.getElementById("composer").requestSubmit();
      return;
    }
    if (event.key === "ArrowUp" && input.selectionStart === 0 && input.selectionEnd === 0 && this.sentHistory.length) {
      event.preventDefault();
      this.historyIndex = Math.max(0, this.historyIndex - 1);
      input.value = this.sentHistory[this.historyIndex];
      input.setSelectionRange(input.value.length, input.value.length);
    } else if (event.key === "ArrowDown" && this.historyIndex < this.sentHistory.length) {
      event.preventDefault();
      this.historyIndex += 1;
      input.value = this.sentHistory[this.historyIndex] || "";
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }

  demoState(value) { forceDemoState(this.status, value); }
}
