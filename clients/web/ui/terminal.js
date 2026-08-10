"use strict";

/**
 * Terminal UI Panel (Build 33 / SPEC.md §4, §6 - tmux lane)
 *
 * Implements xterm.js against proxied session socket (/session?agent=...)
 * Features required by SPEC.md:
 * - Read-only by default (deliberate toggle for typing)
 * - Exact 120x32 geometry matching LLD-session
 * - 5 Required Panel States: loading, empty, error (with retry), stale (update age), disconnected (reconnect backoff & attempt count)
 * - Safety rule (Invariant 7): Terminal is rendering/input only; NEVER scrape bytes for data!
 */

export class TerminalPanel {
  constructor(options = {}) {
    this.mountId = options.mountId || "terminal-panel";
    this.containerId = options.containerId || "terminal-container";
    this.term = null;
    this.socket = null;
    this.agent = null;
    this.isReadOnly = true;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectTimer = null;
    this.lastOutputTime = null;
    this.staleCheckInterval = null;

    this.state = "empty"; // loading | empty | error | stale | disconnected | connected
  }

  init() {
    if (this.term || typeof window.Terminal === "undefined") return;

    // Exact 120x32 geometry per LLD-session & SPEC.md §6
    this.term = new window.Terminal({
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

    const container = document.getElementById(this.containerId);
    if (container) {
      this.term.open(container);
    }

    // Safety Rule (Invariant 7 & SPEC.md §5): Terminal bytes are rendering and user input ONLY.
    // NEVER scrape terminal bytes for presence or replies!
    this.term.onData((data) => {
      if (!this.isReadOnly && this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(data);
      }
    });

    this._bindControls();
    this._startStaleChecker();
  }

  _bindControls() {
    const toggleBtn = document.getElementById("toggle-input-mode");
    if (toggleBtn) {
      toggleBtn.onclick = () => this.toggleInputMode();
    }
    const reconnectBtn = document.getElementById("reconnect-terminal");
    if (reconnectBtn) {
      reconnectBtn.onclick = () => {
        if (this.agent) this.connect(this.agent, true);
      };
    }
  }

  toggleInputMode() {
    this.isReadOnly = !this.isReadOnly;
    this.updateModeUI();
  }

  updateModeUI() {
    const badge = document.getElementById("terminal-mode-badge");
    const btn = document.getElementById("toggle-input-mode");
    if (!badge || !btn) return;

    if (this.isReadOnly) {
      badge.textContent = "READ-ONLY";
      badge.className = "badge mode-readonly";
      btn.textContent = "Enable Typing";
    } else {
      badge.textContent = "INTERACTIVE (TYPING)";
      badge.className = "badge mode-interactive";
      btn.textContent = "Disable Typing";
    }
  }

  setPanelStatus(statusText, statusClass = "muted") {
    const statusEl = document.getElementById("terminal-status-text");
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.className = `terminal-status ${statusClass}`;
    }
  }

  _startStaleChecker() {
    if (this.staleCheckInterval) clearInterval(this.staleCheckInterval);
    this.staleCheckInterval = setInterval(() => {
      if (this.state === "connected" && this.lastOutputTime) {
        const ageSec = Math.floor((Date.now() - this.lastOutputTime) / 1000);
        if (ageSec > 30) {
          this.setPanelStatus(`Stale (last output ${ageSec}s ago)`, "stale");
        } else {
          this.setPanelStatus("Live", "connected");
        }
      }
    }, 5000);
  }

  connect(agentName, isManualRetry = false) {
    if (!agentName) {
      this.state = "empty";
      this.setPanelStatus("No agent selected", "muted");
      return;
    }

    this.init();
    if (!this.term) return;

    if (isManualRetry) {
      this.reconnectAttempts = 0;
      if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    }

    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
      this.socket = null;
    }

    this.agent = agentName;
    this.state = "loading";
    this.setPanelStatus(`Connecting to ${agentName}...`, "loading");
    this.term.reset();
    this.term.writeln(`\x1b[36m--- Terminal Window for ${agentName} (120x32) ---\x1b[0m`);
    this.term.writeln(`\x1b[90mConnecting to /session?agent=${encodeURIComponent(agentName)}...\x1b[0m\r\n`);

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${location.host}/session?agent=${encodeURIComponent(agentName)}`;

    try {
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        this.state = "connected";
        this.reconnectAttempts = 0;
        this.lastOutputTime = Date.now();
        this.setPanelStatus("Live", "connected");
        this.term.writeln(`\x1b[32m--- Connected [120x32, ${this.isReadOnly ? "read-only" : "interactive"}] ---\x1b[0m\r\n`);
      };

      ws.onmessage = (event) => {
        this.lastOutputTime = Date.now();
        if (this.state === "stale") {
          this.state = "connected";
          this.setPanelStatus("Live", "connected");
        }
        if (typeof event.data === "string") {
          this.term.write(event.data);
        } else if (event.data instanceof ArrayBuffer) {
          this.term.write(new Uint8Array(event.data));
        }
      };

      ws.onclose = (event) => {
        this.socket = null;
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++;
          this.state = "disconnected";
          const delaySec = Math.min(2 * Math.pow(1.5, this.reconnectAttempts), 15);
          this.setPanelStatus(`Disconnected. Reconnecting in ${Math.round(delaySec)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})...`, "disconnected");
          this.term.writeln(`\r\n\x1b[33m--- Disconnected. Reconnecting in ${Math.round(delaySec)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})... ---\x1b[0m`);

          this.reconnectTimer = setTimeout(() => {
            this.connect(agentName);
          }, delaySec * 1000);
        } else {
          this.state = "error";
          this.setPanelStatus("Connection failed (max retries reached). Click Reconnect.", "error");
          this.term.writeln(`\r\n\x1b[31m--- Connection failed after ${this.maxReconnectAttempts} attempts. Click Reconnect to retry. ---\x1b[0m`);
        }
      };

      ws.onerror = () => {
        // Handled by onclose
      };

      this.socket = ws;
    } catch (err) {
      this.state = "error";
      this.setPanelStatus(`Error: ${err.message}`, "error");
      this.term.writeln(`\r\n\x1b[31mFailed to create WebSocket: ${err.message}\x1b[0m`);
    }
  }

  destroy() {
    if (this.staleCheckInterval) clearInterval(this.staleCheckInterval);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
    }
    if (this.term) {
      try { this.term.dispose(); } catch (_) {}
    }
  }
}
