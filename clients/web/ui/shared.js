"use strict";

export const api = async (path, options = {}) => {
  let response;
  try { response = await fetch(`/api${path}`, options); }
  catch (error) { throw new TypeError(`tenant connection failed: ${error.message}`); }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
};

export const escapeHtml = (value) => {
  const node = document.createElement("span");
  node.textContent = String(value ?? "");
  return node.innerHTML;
};

export const absoluteTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString();
};

export const relativeTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};

export class PanelStatus {
  constructor(elementId, retry) {
    this.element = document.getElementById(elementId);
    this.retry = retry;
    this.lastUpdate = null;
    this.value = "loading";
  }

  set(value, message, { retry = false, updated = false } = {}) {
    this.value = value;
    if (updated) this.lastUpdate = new Date();
    const freshness = this.lastUpdate ? ` · updated ${relativeTime(this.lastUpdate)}` : "";
    this.element.className = `panel-state state-${value}`;
    this.element.innerHTML = `<span>${escapeHtml(message)}${escapeHtml(freshness)}</span>${retry ? '<button type="button">Retry</button>' : ""}`;
    this.element.querySelector("button")?.addEventListener("click", () => this.retry());
  }

  loading(message = "Loading…") { this.set("loading", message); }
  ready(message = "Live") { this.set("ready", message, { updated: true }); }
  empty(message) { this.set("empty", message, { updated: true }); }
  stale(message = "Stale data") { this.set("stale", message, { retry: true }); }
  disconnected(message) { this.set("disconnected", message, { retry: true }); }
  error(error) { this.set("error", `${error.message} · ${absoluteTime(new Date())}`, { retry: true }); }
}

export const classifyFailure = (status, error, hasData) => {
  if (hasData) status.stale(`Refresh failed: ${error.message}`);
  else if (error instanceof TypeError || navigator.onLine === false) status.disconnected(error.message);
  else status.error(error);
};

export const cursorKey = (client, feed) => `hflock.cursor.${client}.${feed}`;

const isNewCursor = (candidate, previous) => {
  if (!previous) return true;
  if (candidate === previous) return false;
  const left = candidate.match(/^(\d+)-(\d+)$/);
  const right = previous.match(/^(\d+)-(\d+)$/);
  if (!left || !right) return true;
  return BigInt(left[1]) > BigInt(right[1]) || (left[1] === right[1] && BigInt(left[2]) > BigInt(right[2]));
};

export class ResumableFeed {
  constructor({ path, eventName, feed, client, status, onEvent }) {
    Object.assign(this, { path, eventName, feed, client, status, onEvent });
    this.source = null;
    this.timer = null;
    this.attempt = 0;
    this.closed = false;
  }

  start() { this.closed = false; this.connect(); return this; }

  connect() {
    if (this.closed) return;
    const cursor = localStorage.getItem(cursorKey(this.client, this.feed));
    const join = this.path.includes("?") ? "&" : "?";
    this.source = new EventSource(`/api${this.path}${cursor ? `${join}after=${encodeURIComponent(cursor)}` : ""}`);
    this.source.onopen = () => {
      this.attempt = 0;
      if (this.status.value !== "empty") this.status.ready("Live stream");
    };
    const receive = (event) => {
      if (!event.data) return;
      let value;
      try { value = JSON.parse(event.data); } catch (_) { return; }
      const cursorValue = value.cursor || event.lastEventId;
      const previous = localStorage.getItem(cursorKey(this.client, this.feed));
      if (cursorValue && !isNewCursor(cursorValue, previous)) return;
      if (cursorValue) localStorage.setItem(cursorKey(this.client, this.feed), cursorValue);
      this.onEvent(value);
      this.status.ready("Live stream");
    };
    this.source.onmessage = receive;
    this.source.addEventListener(this.eventName, receive);
    this.source.onerror = () => {
      if (this.closed) return;
      this.source.close();
      this.attempt += 1;
      const delay = Math.min(1000 * (2 ** (this.attempt - 1)), 30000);
      this.status.set("disconnected", `Disconnected · retry ${this.attempt} in ${Math.ceil(delay / 1000)}s`, { retry: true });
      this.timer = setTimeout(() => this.connect(), delay);
    };
  }

  close() {
    this.closed = true;
    clearTimeout(this.timer);
    this.source?.close();
  }
}

export async function catchUp({ path, collection, feed, client, onEvent }) {
  const cursor = localStorage.getItem(cursorKey(client, feed));
  const join = path.includes("?") ? "&" : "?";
  const value = await api(`${path}${cursor ? `${join}after=${encodeURIComponent(cursor)}` : ""}`);
  for (const event of value[collection] || []) {
    const previous = localStorage.getItem(cursorKey(client, feed));
    if (event.cursor && !isNewCursor(event.cursor, previous)) continue;
    if (event.cursor) localStorage.setItem(cursorKey(client, feed), event.cursor);
    onEvent(event);
  }
  return (value[collection] || []).length;
}

export const forceDemoState = (status, value) => {
  if (value === "loading") status.loading("Loading fixture…");
  else if (value === "empty") status.empty("No data · calm");
  else if (value === "error") status.error(new Error("Fixture request failed"));
  else if (value === "stale") status.stale("Fixture is 5m old");
  else if (value === "disconnected") status.set("disconnected", "Disconnected · retry 3 in 4s", { retry: true });
  else status.ready("Live fixture");
};
