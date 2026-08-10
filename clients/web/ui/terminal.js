"use strict";

/**
 * Terminal UI Panel (Build 33 Part II / SPEC.md §4, §6, §7, §12 - tmux lane)
 *
 * Implements xterm.js against proxied session socket (/session?agent=...)
 * Features required by SPEC.md Part I & Part II:
 * - Read-only by default (deliberate toggle for typing)
 * - Exact 120x32 geometry matching LLD-session
 * - 5 Required Panel States: loading, empty, error (with retry), stale (update age), disconnected (reconnect backoff & attempt count)
 * - ARIA accessibility & live screen reader announcements for safety mode switches
 * - Keyboard navigation & Escape key handling (prevents xterm focus traps)
 * - Light and Dark theme support following prefers-color-scheme
 * - Safety rule (Invariant 7): Terminal is rendering/input only; NEVER scrape bytes for data!
 * - SPEC §12 Over-engineering features:
 *   1. Scrollback search with match highlighting and prev/next navigation
 *   2. Copy & paste protection (auto-copy on selection, read-only paste block, multi-line newline confirm modal)
 *   3. Persistent font size & scrollback depth in localStorage
 *   4. Viewport-aware multi-terminal grid (Single, 2-Split, 4-Grid with vertical cell fitting)
 *   5. Server-side real-time streaming session recording & replay player
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

    // Search addon instance
    this.searchAddon = null;

    // Settings (persisted in localStorage)
    this.fontSize = parseInt(localStorage.getItem("hflock.terminal.fontSize") || "14", 10);
    this.scrollback = parseInt(localStorage.getItem("hflock.terminal.scrollback") || "2000", 10);

    // Session Recording & Replay State
    this.isRecording = false;
    this.recordingSessionId = null;
    this.recordingFrames = [];
    this.recordingStartTime = null;
    this.isPlayingReplay = false;
    this.replayTimer = null;

    // Multi-terminal Layout View Mode: "single" | "split" | "grid"
    this.viewMode = "single";
    this.subTerminals = {};

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

    // Exact 120x32 geometry per LLD-session & SPEC.md §6 & §12
    this.term = new window.Terminal({
      cols: 120,
      rows: 32,
      convertEol: true,
      cursorBlink: true,
      fontSize: this.fontSize,
      scrollback: this.scrollback,
      disableStdin: this.isReadOnly,
      theme: isLight ? this.lightTheme : this.darkTheme
    });

    // SPEC §12: Scrollback search addon initialization
    if (window.SearchAddon && window.SearchAddon.SearchAddon) {
      this.searchAddon = new window.SearchAddon.SearchAddon();
      this.term.loadAddon(this.searchAddon);
    }

    const container = document.getElementById(this.containerId);
    if (container) {
      this.term.open(container);
    }

    // Keyboard Accessibility & Focus Trap Prevention (SPEC.md §7):
    this.term.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && (event.key === "Escape" || event.code === "Escape")) {
        this.term.blur();
        const toggleBtn = document.getElementById("toggle-input-mode");
        if (toggleBtn) toggleBtn.focus();
        this._announce("Focus returned from terminal. Keyboard focus un-trapped.");
        return false;
      }
      return true;
    });

    // SPEC §12: Copy on selection automatically
    if (this.term.onSelectionChange) {
      this.term.onSelectionChange(() => {
        if (this.term && this.term.hasSelection()) {
          const selectedText = this.term.getSelection();
          if (selectedText && navigator.clipboard) {
            navigator.clipboard.writeText(selectedText).catch(() => {});
          }
        }
      });
    }

    // Listen for OS light/dark color scheme preference changes (SPEC.md §7)
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
        if (this.term) {
          this.term.options.theme = e.matches ? this.lightTheme : this.darkTheme;
        }
      });
    }

    // Safety Rule (Invariant 7 & SPEC.md §5): Terminal bytes are rendering and user input ONLY.
    this.term.onData((data) => {
      if (!this.isReadOnly && this.socket && this.socket.readyState === WebSocket.OPEN && this.agent) {
        this._recordFrame("in", data);
        this.socket.send(JSON.stringify({ agent: this.agent, data: data }));
      }
    });

    this._bindControls();
    this._bindSearchControls();
    this._bindSettingsControls();
    this._bindViewControls();
    this._bindRecordingControls();
    this._bindPasteProtection();
    this._startStaleChecker();

    window.addEventListener("resize", () => this._updateViewportGridModes());
    this._updateViewportGridModes();
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

  // SPEC §12: Scrollback Search Controls
  _bindSearchControls() {
    const searchInput = document.getElementById("terminal-search-input");
    const searchPrev = document.getElementById("terminal-search-prev");
    const searchNext = document.getElementById("terminal-search-next");
    const searchResults = document.getElementById("terminal-search-results");

    if (!searchInput) return;

    const performSearch = (direction = "next") => {
      const query = searchInput.value;
      if (!query || !this.searchAddon) {
        if (searchResults) searchResults.textContent = "0 matches";
        return;
      }
      if (direction === "prev") {
        this.searchAddon.findPrevious(query, { regex: false, caseSensitive: false, incremental: false });
      } else {
        this.searchAddon.findNext(query, { regex: false, caseSensitive: false, incremental: false });
      }
    };

    searchInput.oninput = () => performSearch("next");
    searchInput.onkeydown = (e) => {
      if (e.key === "Enter") {
        performSearch(e.shiftKey ? "prev" : "next");
      }
    };
    if (searchPrev) searchPrev.onclick = () => performSearch("prev");
    if (searchNext) searchNext.onclick = () => performSearch("next");
  }

  // SPEC §12: Font Size & Scrollback Persistence in localStorage
  _bindSettingsControls() {
    const fontSizeSelect = document.getElementById("terminal-font-size");
    const scrollbackSelect = document.getElementById("terminal-scrollback-depth");

    if (fontSizeSelect) {
      fontSizeSelect.value = String(this.fontSize);
      fontSizeSelect.onchange = (e) => {
        this.fontSize = parseInt(e.target.value, 10);
        localStorage.setItem("hflock.terminal.fontSize", String(this.fontSize));
        if (this.term) this.term.options.fontSize = this.fontSize;
      };
    }

    if (scrollbackSelect) {
      scrollbackSelect.value = String(this.scrollback);
      scrollbackSelect.onchange = (e) => {
        this.scrollback = parseInt(e.target.value, 10);
        localStorage.setItem("hflock.terminal.scrollback", String(this.scrollback));
        if (this.term) this.term.options.scrollback = this.scrollback;
      };
    }
  }

  // SPEC §12: Viewport-aware Side-by-side Multi-Terminal Views (Single | 2-Split | 4-Grid)
  _bindViewControls() {
    const singleBtn = document.getElementById("term-view-single");
    const splitBtn = document.getElementById("term-view-split");
    const gridBtn = document.getElementById("term-view-grid");

    if (singleBtn) singleBtn.onclick = () => this._setView("single");
    if (splitBtn) splitBtn.onclick = () => this._setView("split");
    if (gridBtn) gridBtn.onclick = () => this._setView("grid");
  }

  _setView(mode) {
    const singleBtn = document.getElementById("term-view-single");
    const splitBtn = document.getElementById("term-view-split");
    const gridBtn = document.getElementById("term-view-grid");
    const singleContainer = document.getElementById(this.containerId);
    const multiGrid = document.getElementById("terminal-multi-grid");

    if (!singleContainer || !multiGrid) return;

    this.viewMode = mode;
    [singleBtn, splitBtn, gridBtn].forEach((btn) => {
      if (btn) {
        const isActive = btn.id === `term-view-${mode}`;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-checked", isActive ? "true" : "false");
      }
    });

    if (mode === "single") {
      singleContainer.hidden = false;
      multiGrid.hidden = true;
    } else {
      singleContainer.hidden = true;
      multiGrid.hidden = false;

      const cell3 = document.getElementById("term-cell-3");
      const cell4 = document.getElementById("term-cell-4");
      if (cell3 && cell4) {
        cell3.hidden = mode !== "grid";
        cell4.hidden = mode !== "grid";
      }
    }
    this._announce(`Terminal view mode switched to ${mode}.`);
  }

  _updateViewportGridModes() {
    const width = window.innerWidth;
    const splitBtn = document.getElementById("term-view-split");
    const gridBtn = document.getElementById("term-view-grid");

    if (gridBtn) {
      if (width < 1400) {
        gridBtn.disabled = true;
        gridBtn.title = "4-Grid requires screen width ≥1400px (current: " + width + "px)";
        if (this.viewMode === "grid") {
          this._setView("split");
        }
      } else {
        gridBtn.disabled = false;
        gridBtn.title = "4-Grid layout mode";
      }
    }

    if (splitBtn) {
      if (width < 900) {
        splitBtn.disabled = true;
        splitBtn.title = "2-Split requires screen width ≥900px (current: " + width + "px)";
        if (this.viewMode === "split") {
          this._setView("single");
        }
      } else {
        splitBtn.disabled = false;
        splitBtn.title = "2-Split layout mode";
      }
    }
  }

  // SPEC §12: Copy/Paste Protection & Multi-line Warning Modal
  _bindPasteProtection() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    container.addEventListener("paste", (e) => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text");
      if (!text) return;

      if (this.isReadOnly) {
        this.setPanelStatus("Paste blocked: Terminal is in READ-ONLY mode.", "error");
        this._announce("Paste blocked: Terminal is currently in read-only mode.");
        return;
      }

      // Check if text contains newlines (executed commands risk)
      if (text.includes("\n") || text.includes("\r")) {
        this._showPasteConfirmationModal(text);
      } else {
        this.sendKeystroke(text);
      }
    });
  }

  _showPasteConfirmationModal(text) {
    const dialog = document.getElementById("paste-confirm-dialog");
    const previewBox = document.getElementById("paste-preview-box");
    const confirmBtn = document.getElementById("paste-confirm-btn");
    const cancelBtn = document.getElementById("paste-cancel-btn");

    if (!dialog || !previewBox || !confirmBtn) {
      if (confirm(`Pasting content containing newlines will execute commands immediately in agent session:\n\n${text.slice(0, 200)}...\n\nProceed?`)) {
        this.sendKeystroke(text);
      }
      return;
    }

    const lineCount = text.split(/\r\n|\r|\n/).length;
    previewBox.textContent = `[${lineCount} Lines to Paste]:\n${text}`;
    
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.hidden = false;
    }

    const cleanup = () => {
      confirmBtn.onclick = null;
      if (cancelBtn) cancelBtn.onclick = null;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.hidden = true;
      }
    };

    confirmBtn.onclick = (e) => {
      e.preventDefault();
      this.sendKeystroke(text);
      cleanup();
    };

    if (cancelBtn) {
      cancelBtn.onclick = (e) => {
        e.preventDefault();
        cleanup();
      };
    }
  }

  sendKeystroke(data) {
    if (!this.isReadOnly && this.socket && this.socket.readyState === WebSocket.OPEN && this.agent) {
      this._recordFrame("in", data);
      this.socket.send(JSON.stringify({ agent: this.agent, data: data }));
    }
  }

  // SPEC §12: Server-Side Real-Time Session Recording Streaming & Replay
  _bindRecordingControls() {
    const recordBtn = document.getElementById("record-session-btn");
    const replayBtn = document.getElementById("replay-session-btn");
    const replayBar = document.getElementById("session-replay-bar");
    const playPauseBtn = document.getElementById("replay-play-pause");
    const closeReplayBtn = document.getElementById("replay-close");

    if (recordBtn) {
      recordBtn.onclick = () => {
        if (!this.isRecording) {
          this.isRecording = true;
          this.recordingFrames = [];
          this.recordingStartTime = Date.now();
          this.recordingSessionId = `rec_${this.agent || 'terminal'}_${Date.now()}`;
          recordBtn.classList.add("recording");
          recordBtn.textContent = "Stop Rec";
          this._announce("Terminal session recording started.");
          this.setPanelStatus("Recording session...", "connected");

          // Initialize recording entry on server.py backend
          fetch("/api/recordings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: this.recordingSessionId,
              agent: this.agent || "unknown",
              start_ts: this.recordingStartTime,
              mode: this.isReadOnly ? "read-only" : "read-write",
              chunks: []
            })
          }).catch(() => {});
        } else {
          this.isRecording = false;
          recordBtn.classList.remove("recording");
          recordBtn.textContent = "Record";

          this._announce(`Session recording stopped. ${this.recordingFrames.length} frames streamed to server.`);
          this.setPanelStatus(`Recording saved to server (${this.recordingFrames.length} frames).`, "connected");
        }
      };
    }

    if (replayBtn && replayBar) {
      replayBtn.onclick = () => {
        // Fetch server-side recordings from GET /api/recordings
        fetch("/api/recordings")
          .then((res) => res.json())
          .then((data) => {
            const list = Array.isArray(data) ? data : (data.recordings || []);
            if (list.length > 0) {
              const rec = list[list.length - 1];
              this.recordingFrames = rec.chunks || rec.frames || [];
            }
            if (this.recordingFrames.length === 0) {
              alert("No recorded session available on server. Click 'Record' first to capture a session.");
              return;
            }
            replayBar.hidden = false;
            this.startReplay();
          })
          .catch(() => {
            if (this.recordingFrames.length === 0) {
              alert("No recorded session available. Click 'Record' first to capture a session.");
              return;
            }
            replayBar.hidden = false;
            this.startReplay();
          });
      };
    }

    if (playPauseBtn) {
      playPauseBtn.onclick = () => {
        if (this.isPlayingReplay) {
          this.pauseReplay();
          playPauseBtn.textContent = "▶ Play";
        } else {
          this.startReplay();
          playPauseBtn.textContent = "❚❚ Pause";
        }
      };
    }

    if (closeReplayBtn && replayBar) {
      closeReplayBtn.onclick = () => {
        this.pauseReplay();
        replayBar.hidden = true;
        if (this.agent) this.connect(this.agent, true);
      };
    }
  }

  _recordFrame(direction, data) {
    if (!this.isRecording || !this.recordingStartTime) return;
    const deltaMs = Date.now() - this.recordingStartTime;
    const frame = { deltaMs, direction, data };
    this.recordingFrames.push(frame);

    // SPEC §12 & Architect Directive: Stream frame chunk immediately to server backend
    if (this.recordingSessionId) {
      fetch(`/api/recordings/${this.recordingSessionId}/frames`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(frame)
      }).catch(() => {});
    }
  }

  startReplay() {
    if (!this.term || this.recordingFrames.length === 0) return;
    this.isPlayingReplay = true;
    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
    }
    this.term.reset();
    this.term.writeln("\x1b[35;1m--- SESSION REPLAY STARTED ---\x1b[0m\r\n");

    let index = 0;
    const speedSelect = document.getElementById("replay-speed");
    const scrub = document.getElementById("replay-scrub");

    const playNext = () => {
      if (!this.isPlayingReplay || index >= this.recordingFrames.length) {
        this.isPlayingReplay = false;
        this.term.writeln("\r\n\x1b[35;1m--- SESSION REPLAY FINISHED ---\x1b[0m");
        return;
      }

      const frame = this.recordingFrames[index];
      const speed = parseFloat((speedSelect && speedSelect.value) || "1");

      if (typeof frame.data === "string") {
        this.term.write(frame.data);
      }

      if (scrub) {
        scrub.value = String(Math.round((index / this.recordingFrames.length) * 100));
      }

      index++;
      const nextFrame = this.recordingFrames[index];
      const delay = nextFrame ? Math.max((nextFrame.deltaMs - frame.deltaMs) / speed, 10) : 50;

      this.replayTimer = setTimeout(playNext, delay);
    };

    playNext();
  }

  pauseReplay() {
    this.isPlayingReplay = false;
    if (this.replayTimer) clearTimeout(this.replayTimer);
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

        let rawData = event.data;
        if (typeof rawData === "string") {
          try {
            const parsed = JSON.parse(rawData);
            if (parsed && typeof parsed === "object" && parsed.error) {
              this.state = "error";
              this.setPanelStatus(`Window error: ${parsed.error}`, "error");
              this._announce(`Terminal error: agent window terminated (${parsed.error})`);
              this.term.writeln(`\r\n\x1b[31;1m--- WINDOW TERMINATED: ${parsed.error} ---\x1b[0m`);
              return;
            }
          } catch (_) {}
          this._recordFrame("out", rawData);
          this.term.write(rawData);
        } else if (rawData instanceof ArrayBuffer) {
          this._recordFrame("out", rawData);
          this.term.write(new Uint8Array(rawData));
        }
      };

      ws.onclose = (event) => {
        this.socket = null;
        if (this.state === "error") {
          return;
        }
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++;
          this.state = "disconnected";
          const delaySec = Math.min(2 * Math.pow(1.5, this.reconnectAttempts), 15);
          this.setPanelStatus(`Disconnected (${event.reason || 'session closed'}). Reconnecting in ${Math.round(delaySec)}s...`, "disconnected");
          this._announce(`Terminal disconnected. Reconnecting in ${Math.round(delaySec)} seconds.`);
          this.term.writeln(`\r\n\x1b[33m--- Disconnected: ${event.reason || 'Session closed'}. Reconnecting in ${Math.round(delaySec)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})... ---\x1b[0m`);

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

      ws.onerror = () => {};

      this.socket = ws;
    } catch (err) {
      this.state = "error";
      this.setPanelStatus(`Error: ${err.message}`, "error");
      this._announce(`Terminal error: ${err.message}`);
      this.term.writeln(`\r\n\x1b[31mFailed to create WebSocket: ${err.message}\x1b[0m`);
    }
  }

  destroy() {
    this.pauseReplay();
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
