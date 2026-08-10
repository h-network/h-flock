"use strict";

/**
 * Terminal UI Panel (Build 33 / SPEC.md §4, §6, §7 - tmux lane)
 *
 * Implements xterm.js against proxied session socket (/session?agent=...)
 * Features required by SPEC.md:
 * - Read-only by default (deliberate toggle for typing)
 * - Exact 120x32 geometry matching LLD-session
 * - 5 Required Panel States: loading, empty, error (with retry), stale (update age), disconnected (reconnect backoff & attempt count)
 * - ARIA accessibility & live screen reader announcements for safety mode switches
 * - Keyboard navigation & Escape key handling (prevents xterm focus traps)
 * - Light and Dark theme support following prefers-color-scheme
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

    this.darkTheme = {
      background: "#0a0c10",
      foreground: "#d0d7de",
      cursor: "#58a6ff",
      selectionBackground: "#264f78"
    };

    this.lightTheme = {
      background: "#ffffff",
      foreground: "#1f2328",
      cursor: "#0969da",
      selectionBackground: "#b4d5fe"
    };
  }

  init() {
    if (this.term || typeof window.Terminal === "undefined") return;

    const isLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;

    // Exact 120x32 geometry per LLD-session & SPEC.md §6
    // Read-only by default: disableStdin provides engine-level input blocking (SPEC.md §6)
    this.term = new window.Terminal({
      cols: 120,
      rows: 32,
      convertEol: true,
      cursorBlink: true,
      disableStdin: this.isReadOnly,
      theme: isLight ? this.lightTheme : this.darkTheme
    });

    const container = document.getElementById(this.containerId);
    if (container) {
      this.term.open(container);
    }

    // Keyboard Accessibility & Focus Trap Prevention (SPEC.md §7):
    // xterm captures keys aggressively; handling Escape allows users to leave terminal focus cleanly.
    this.term.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && (event.key === "Escape" || event.code === "Escape")) {
        this.term.blur();
        const toggleBtn = document.getElementById("toggle-input-mode");
        if (toggleBtn) toggleBtn.focus();
        this._announce("Focus returned from terminal. Keyboard focus un-trapped.");
        return false; // Prevent xterm from swallowing Escape
      }
      return true;
    });

    // Listen for OS light/dark color scheme preference changes (SPEC.md §7)
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
        if (this.term) {
          this.term.options.theme = e.matches ? this.lightTheme : this.darkTheme;
        }
      });
    }

    // Safety Rule (Invariant 7 & SPEC.md §5): Terminal bytes are rendering and user input ONLY.
    // NEVER scrape terminal bytes for presence or replies!
    this.term.onData((data) => {
      if (!this.isReadOnly && this.socket && this.socket.readyState === WebSocket.OPEN && this.agent) {
        this.socket.send(JSON.stringify({ agent: this.agent, data: data }));
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

  _announce(message) {
    const announcer = document.getElementById("terminal-live-announcer");
    if (announcer) {
      announcer.textContent = message;
    }
  }

  toggleInputMode() {
    this.isReadOnly = !this.isReadOnly;
    this.updateModeUI();
    if (this.agent) {
      this.connect(this.agent);
    }
  }

  updateModeUI() {
    const badge = document.getElementById("terminal-mode-badge");
    const btn = document.getElementById("toggle-input-mode");
    if (this.term) {
      this.term.options.disableStdin = this.isReadOnly;
    }
    if (!badge || !btn) return;

    if (this.isReadOnly) {
      badge.textContent = "READ-ONLY";
      badge.className = "badge mode-readonly";
      btn.textContent = "Enable Typing";
      btn.setAttribute("aria-label", "Enable typing in terminal window");
      this._announce("Terminal mode changed to READ-ONLY. Typing is disabled.");
    } else {
      badge.textContent = "INTERACTIVE (TYPING)";
      badge.className = "badge mode-interactive";
      btn.textContent = "Disable Typing";
      btn.setAttribute("aria-label", "Disable typing in terminal window");
      this._announce("Terminal mode changed to INTERACTIVE (TYPING). Keystrokes will be sent to agent session.");
    }
  }

  setPanelStatus(statusText, statusClass = "muted") {
    const statusEl = document.getElementById("terminal-status-text");
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.className = `terminal-status ${statusClass}`;
      // SPEC.md §7: absolute timestamp on hover, relative text at rest
      const absTime = this.lastOutputTime ? new Date(this.lastOutputTime).toISOString() : new Date().toISOString();
      statusEl.title = `Last Output: ${absTime}`;
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
    this._announce(`Connecting terminal to agent ${agentName}`);
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
        this._announce(`Terminal connected to ${agentName} session.`);

        // SPEC §6 & Invariant 7: Enforce server-side read-only mode on Session Door backend
        const initialMode = this.isReadOnly ? "read-only" : "read-write";
        try {
          ws.send(JSON.stringify({ subscribe: [agentName], mode: initialMode }));
        } catch (_) {}

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
          this._announce(`Terminal disconnected. Reconnecting in ${Math.round(delaySec)} seconds.`);
          this.term.writeln(`\r\n\x1b[33m--- Disconnected. Reconnecting in ${Math.round(delaySec)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})... ---\x1b[0m`);

          this.reconnectTimer = setTimeout(() => {
            this.connect(agentName);
          }, delaySec * 1000);
        } else {
          this.state = "error";
          this.setPanelStatus("Connection failed (max retries reached). Click Reconnect.", "error");
          this._announce("Terminal connection failed after maximum attempts. Click Reconnect to retry.");
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
      this._announce(`Terminal error: ${err.message}`);
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
