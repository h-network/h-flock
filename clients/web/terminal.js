"use strict";

/* --- Terminal Panel Implementation (Build 33 - tmux lane) --- */

const termState = {
  term: null,
  socket: null,
  isReadOnly: true,
  agent: null
};

const $el = (id) => document.getElementById(id);

function initTerminal() {
  if (termState.term || typeof window.Terminal === "undefined") return;
  // Exact 120x32 geometry per LLD-session & BUILD-33 spec
  termState.term = new window.Terminal({
    cols: 120,
    rows: 32,
    convertEol: true,
    cursorBlink: true,
    theme: {
      background: "#0a0c10",
      foreground: "#d0d7de",
      cursor: "#58a6ff",
      selectionBackground: "#264f78"
    }
  });

  const container = $el("terminal-container") || $el("terminal");
  if (container) {
    termState.term.open(container);
  }

  // Handle terminal user data input (typing)
  termState.term.onData((data) => {
    // ⚠ SAFETY RULE (Invariant 7): Terminal is a rendering and user typing interface.
    // Do NOT scrape terminal bytes for presence, status, or replies!
    if (!termState.isReadOnly && termState.socket && termState.socket.readyState === WebSocket.OPEN) {
      termState.socket.send(data);
    }
  });

  if ($el("toggle-input-mode")) $el("toggle-input-mode").onclick = toggleTerminalInputMode;
  if ($el("reconnect-terminal")) $el("reconnect-terminal").onclick = () => {
    if (termState.agent) connectTerminal(termState.agent);
  };
}

function toggleTerminalPanel() {
  const panel = $el("terminal-panel");
  if (!panel) return;
  panel.hidden = !panel.hidden;
  if (!panel.hidden && termState.agent) {
    connectTerminal(termState.agent);
  }
}

function toggleTerminalInputMode() {
  termState.isReadOnly = !termState.isReadOnly;
  updateTerminalModeUI();
}

function updateTerminalModeUI() {
  const badge = $el("terminal-mode-badge");
  const btn = $el("toggle-input-mode");
  if (!badge || !btn) return;
  if (termState.isReadOnly) {
    badge.textContent = "READ-ONLY";
    badge.className = "badge mode-readonly";
    btn.textContent = "Enable Typing";
  } else {
    badge.textContent = "INTERACTIVE (TYPING)";
    badge.className = "badge mode-interactive";
    btn.textContent = "Disable Typing";
  }
}

function connectTerminal(agentName) {
  if (!agentName) return;
  initTerminal();
  if (!termState.term) return;

  if (termState.socket) {
    try { termState.socket.close(); } catch (_) {}
    termState.socket = null;
  }

  termState.agent = agentName;
  termState.term.reset();
  termState.term.writeln(`\x1b[36m--- Terminal Window for ${agentName} (120x32) ---\x1b[0m`);

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${location.host}/session?agent=${encodeURIComponent(agentName)}`;

  try {
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      termState.term.writeln(`\x1b[32m--- Connected to session socket [120x32, ${termState.isReadOnly ? "read-only" : "interactive"}] ---\x1b[0m\r\n`);
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        termState.term.write(event.data);
      } else if (event.data instanceof ArrayBuffer) {
        termState.term.write(new Uint8Array(event.data));
      }
    };

    ws.onclose = () => {
      termState.term.writeln(`\r\n\x1b[33m--- Terminal session disconnected ---\x1b[0m`);
    };

    ws.onerror = () => {
      termState.term.writeln(`\r\n\x1b[31m--- WebSocket connection error ---\x1b[0m`);
    };

    termState.socket = ws;
  } catch (err) {
    termState.term.writeln(`\r\n\x1b[31mFailed to connect: ${err.message}\x1b[0m`);
  }
}

// Global exports for seamless mounting by bus/api scripts
window.connectTerminal = connectTerminal;
window.toggleTerminalPanel = toggleTerminalPanel;
window.toggleTerminalInputMode = toggleTerminalInputMode;
