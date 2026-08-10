"use strict";

// A conversation with one agent. Messages in, messages out, work shown while it
// happens. ⚠ Nothing here reads a terminal — answers are messages (HLD §7).

const $ = (id) => document.getElementById(id);
const state = { agent: "", client: "", cursor: null, activityCursor: null, turn: null, presence: "unknown" };

const CURSOR_KEY = () => `hflock.chat.${state.client}.cursor`;

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, options);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function stamp(ts) {
  const d = ts ? new Date(ts) : new Date();
  const node = el("time", "ts", d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  node.dateTime = d.toISOString();
  node.title = d.toISOString();
  return node;
}

function addMessage(who, text, ts, claimed) {
  const wrap = el("div", `msg ${who === "you" ? "mine" : "theirs"}`);
  const head = el("div", "head");
  head.append(el("span", "name", who === "you" ? "You" : who));
  // ⚠ producer is unverified (HLD invariant 2). Say "claimed" for anything that
  // is not this client's own outbound message.
  if (claimed) head.append(el("span", "claimed", "claimed identity"));
  head.append(stamp(ts));
  wrap.append(head, el("div", "body", text));
  $("thread").append(wrap);
  state.turn = null;
  $("thread").scrollTop = $("thread").scrollHeight;
}

// Tool activity is shown under the agent's current turn, names only, adjacent
// repeats collapsed — the shape the Telegram client proved works.
function addTool(name) {
  if (!state.turn) {
    state.turn = el("div", "turn");
    state.turn.append(el("div", "turn-label", `${state.agent} · working`));
    state.turn.tools = el("ol", "tools");
    state.turn.append(state.turn.tools);
    $("thread").append(state.turn);
  }
  const list = state.turn.tools;
  const last = list.lastElementChild;
  if (last && last.dataset.tool === name) {
    last.dataset.count = String(Number(last.dataset.count || 1) + 1);
    last.textContent = `⚙ ${name} ×${last.dataset.count}`;
  } else {
    const item = el("li", "tool", `⚙ ${name}`);
    item.dataset.tool = name;
    item.dataset.count = "1";
    list.append(item);
  }
  $("thread").scrollTop = $("thread").scrollHeight;
}

function setPresence(p) {
  state.presence = p;
  $("state").textContent = p;
  $("dot").className = `dot ${p}`;
  const notice = $("notice");
  const input = $("input");
  const send = $("send");
  if (p === "blocked") {
    notice.hidden = false;
    notice.className = "notice bad";
    notice.textContent = "Not accepting messages — a delivery was not consumed. Someone needs to look at this agent.";
    input.disabled = send.disabled = true;
  } else if (p === "unknown") {
    notice.hidden = false;
    notice.className = "notice warn";
    notice.textContent = "Nothing can be read from this agent. A reply may never come.";
    input.disabled = send.disabled = false;
  } else {
    notice.hidden = true;
    input.disabled = send.disabled = false;
  }
}

async function pollPresence() {
  try {
    const d = await api(`/agents/${encodeURIComponent(state.agent)}`);
    setPresence(d?.presence?.state || "unknown");
  } catch (_) {
    /* leave the last known state rather than lying about it */
  }
}

function stream(path, onEvent) {
  let attempt = 0;
  const open = () => {
    const src = new EventSource(path);
    src.onopen = () => { attempt = 0; };
    src.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch (_) {}
    };
    src.onerror = () => {
      src.close();
      attempt += 1;
      // ⚠ Never stop silently: a dead stream looks exactly like a quiet agent.
      setTimeout(open, Math.min(1000 * 2 ** attempt, 15000));
    };
  };
  open();
}

async function loadHistory() {
  const after = localStorage.getItem(CURSOR_KEY());
  const q = after ? `?after=${encodeURIComponent(after)}` : "";
  try {
    const d = await api(`/agents/${encodeURIComponent(state.client)}/messages${q}`);
    for (const m of d.messages || []) {
      const producer = m.producer || m?.envelope?.producer || "agent";
      const text = m?.payload?.text ?? m?.envelope?.payload?.text ?? "";
      if (text) addMessage(producer, text, m.ts, producer !== state.agent);
      if (m.cursor) { state.cursor = m.cursor; localStorage.setItem(CURSOR_KEY(), m.cursor); }
    }
  } catch (_) {}
}

async function send(text) {
  addMessage("you", text, new Date().toISOString(), false);
  await fetch(`/api/agents/${encodeURIComponent(state.agent)}/envelopes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, as: state.client }),
  });
}

async function boot() {
  const cfg = await (await fetch("/config")).json();
  state.agent = cfg.agent;
  state.client = cfg.client;
  $("agent").textContent = cfg.agent;
  $("as").textContent = `you are ${cfg.client}`;
  document.title = `chat · ${cfg.agent}`;
  $("input").placeholder = `Message ${cfg.agent}…`;

  await loadHistory();
  await pollPresence();
  // Presence is polled, not streamed — the same reason the Telegram client
  // polls it: a typing indicator has to be refreshed, not awaited.
  setInterval(pollPresence, 4000);

  stream(`/api/agents/${encodeURIComponent(state.client)}/messages/stream`, (m) => {
    const producer = m.producer || m?.envelope?.producer || "agent";
    const text = m?.payload?.text ?? m?.envelope?.payload?.text ?? "";
    if (text) addMessage(producer, text, m.ts, producer !== state.agent);
    if (m.cursor) localStorage.setItem(CURSOR_KEY(), m.cursor);
  });

  stream(`/api/agents/${encodeURIComponent(state.agent)}/activity/stream`, (e) => {
    if (e.kind === "tool" && e.tool) addTool(e.tool);
  });

  const input = $("input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
      ev.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("composer").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    await send(text);
  });
}

boot();
