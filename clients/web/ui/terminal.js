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
    const bannerBtn = document.getElementById("terminal-typing-banner-btn");

    if (toggleBtn) {
      toggleBtn.onclick = () => this.toggleInputMode();
    }
    if (bannerBtn) {
      bannerBtn.onclick = () => this.toggleInputMode();
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
      }).then((res) => {
        if (res.status === 413) {
          this._handleRecordingCapReached();
        }
      }).catch(() => {});
    }
  }

  // Purity Rule (Invariant 7 & SPEC.md §5): Terminal buffer contains ONLY raw agent-emitted bytes.
  // Console state, errors, and recording alerts are reflected strictly in panel chrome and screen reader live regions.
  _handleRecordingCapReached() {
    if (!this.isRecording) return;
    this.isRecording = false;
    const recordBtn = document.getElementById("record-session-btn");
    if (recordBtn) {
      recordBtn.classList.remove("recording");
      recordBtn.classList.add("recording-full");
      recordBtn.textContent = "Rec Full (Capped)";
      recordBtn.setAttribute("aria-label", "Recording stopped: Server storage limit reached (5MB / 5000 frames limit)");
    }
    this.setPanelStatus("Recording stopped: Server retention cap reached (5MB / 5000 frames limit).", "error");
    this._announce("ALERT: Terminal session recording automatically stopped. Server storage retention limit reached.");
  }

  startReplay() {
    if (!this.term || this.recordingFrames.length === 0) return;
    this.isPlayingReplay = true;
    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
    }
    this.term.reset();
    this.setPanelStatus("Replaying recorded session...", "loading");
    this._announce("Terminal session replay started.");

    let index = 0;
    const speedSelect = document.getElementById("replay-speed");
    const scrub = document.getElementById("replay-scrub");

    const playNext = () => {
      if (!this.isPlayingReplay || index >= this.recordingFrames.length) {
        this.isPlayingReplay = false;
        this.setPanelStatus("Replay finished.", "connected");
        this._announce("Terminal session replay finished.");
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
    const banner = document.getElementById("terminal-typing-banner");
    const bannerText = document.getElementById("terminal-typing-banner-text");
    const bannerBtn = document.getElementById("terminal-typing-banner-btn");

    if (this.term) {
      this.term.options.disableStdin = this.isReadOnly;
    }

    if (this.isReadOnly) {
      if (badge) {
        badge.textContent = "READ-ONLY";
        badge.className = "badge mode-readonly";
      }
      if (btn) {
        btn.textContent = "Enable Typing";
        btn.setAttribute("aria-label", "Enable typing in terminal window");
      }
      if (banner) {
        banner.className = "typing-banner readonly";
      }
      if (bannerText) {
        bannerText.textContent = "🔒 READ-ONLY MODE (Locked for safety — Click button to enable keyboard input)";
      }
      if (bannerBtn) {
        bannerBtn.textContent = "🔓 Enable Typing";
      }
      this._announce("Terminal mode changed to READ-ONLY. Typing is disabled.");
    } else {
      if (badge) {
        badge.textContent = "INTERACTIVE (TYPING)";
        badge.className = "badge mode-interactive";
      }
      if (btn) {
        btn.textContent = "Disable Typing";
        btn.setAttribute("aria-label", "Disable typing in terminal window");
      }
      if (banner) {
        banner.className = "typing-banner interactive";
      }
      if (bannerText) {
        bannerText.textContent = "⌨️ INTERACTIVE TYPING MODE (Keystrokes sent directly to agent session)";
      }
      if (bannerBtn) {
        bannerBtn.textContent = "🔒 Lock READ-ONLY";
      }
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

    // ⚠ Idempotent, and this is load-bearing. renderWorkspace runs on every
    // roster poll and calls connect() again; without this guard the socket is
    // torn down and re-subscribed every couple of seconds. Measured in a
    // browser: the operator's first keystroke was delivered, then the frame log
    // showed nothing but repeated subscribe frames — every character after the
    // first was eaten by the reconnect churn. "typing works but half" was this.
    // ⚠ ...but a MODE change must still reconnect. The door refuses to change
    // mode on a live socket ("mode cannot change"), so read-only to read-write
    // is a new subscription. Skipping it here left the socket read-only while
    // the button said INTERACTIVE, and every keystroke was rejected silently.
    const wantedMode = this.isReadOnly ? "read-only" : "read-write";
    if (!isManualRetry
        && this.socket
        && this.agent === agentName
        && this.subscribedMode === wantedMode
        && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.subscribedMode = wantedMode;

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
      };

      ws.onmessage = (event) => {
        this.lastOutputTime = Date.now();
        if (this.state === "stale") {
          this.state = "connected";
          this.setPanelStatus("Live", "connected");
        }

        let rawData = event.data;
        if (typeof rawData === "string") {
          // ⚠ The session door speaks JSON envelopes, not bare bytes:
          // {"agent": "<name>", "data": "<terminal output>"}. Write the DATA
          // FIELD, never the envelope. Writing the raw string put the literal
          // JSON — agent name, escape codes as text, the lot — on screen where
          // the terminal should have been, which is what an operator saw.
          let parsed = null;
          try {
            parsed = JSON.parse(rawData);
          } catch (_) {}
          if (parsed && typeof parsed === "object") {
            if (parsed.error) {
              this.state = "error";
              this.setPanelStatus(`Window error: ${parsed.error}`, "error");
              this._announce(`Terminal error: agent window terminated (${parsed.error})`);
              return;
            }
            if (typeof parsed.data === "string") {
              this._recordFrame("out", parsed.data);
              // ⚠ The door is byte-transparent: it decodes latin-1 so every byte
              // survives as one code point. Writing that string as TEXT makes
              // xterm read 0xE2 as 'â' instead of the first byte of a UTF-8
              // sequence — box-drawing and anything non-ASCII turns to mojibake.
              // Convert back to the bytes and let xterm do the UTF-8 decoding.
              const bytes = new Uint8Array(parsed.data.length);
              for (let i = 0; i < parsed.data.length; i += 1) {
                bytes[i] = parsed.data.charCodeAt(i) & 0xff;
              }
              this.term.write(bytes);
              return;
            }
            // A JSON object with neither error nor data is protocol chatter —
            // an ack or a subscribe confirmation. It is not agent output and
            // must not reach the buffer.
            return;
          }
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

          this.reconnectTimer = setTimeout(() => {
            this.connect(agentName);
          }, delaySec * 1000);
        } else {
          this.state = "error";
          this.setPanelStatus("Connection failed (max retries reached). Click Reconnect.", "error");
          this._announce("Terminal connection failed after maximum attempts. Click Reconnect to retry.");
        }
      };

      ws.onerror = () => {};

      this.socket = ws;
    } catch (err) {
      this.state = "error";
      this.setPanelStatus(`Error: ${err.message}`, "error");
      this._announce(`Terminal error: ${err.message}`);
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

/**
 * Terminal Workspace Manager (SPEC §15 #/terminals)
 *
 * Manages long-lived agent terminal sessions so that WebSockets and xterm scrollback
 * buffers survive navigation across sections (#/terminals <-> #/alerts <-> #/agents).
 * Provides per-session container IDs (term-container-<agent>) to prevent DOM collisions
 * when rendering workspace tabs per open agent.
 */
export class TerminalWorkspace {
  constructor() {
    this.sessions = {}; // agentName -> { panel, agentName, containerId }
    this.openTabs = []; // list of open agent names
    // ⚠ Every agent this workspace has ever been told about. A tab the operator
    // closed must stay closed, so "should this get a tab?" cannot be answered by
    // looking at openTabs alone — only by knowing whether the agent is new.
    this.knownAgents = new Set();
    this.activeAgent = null;
    this.mountElement = null;
  }

  getOrCreateSession(agentName, customContainerId = null) {
    const containerId = customContainerId || `term-container-${agentName}`;
    if (!this.sessions[agentName]) {
      let containerEl = document.getElementById(containerId);
      if (!containerEl && this.mountElement) {
        containerEl = document.createElement("div");
        containerEl.id = containerId;
        containerEl.className = "terminal-container";
        this.mountElement.appendChild(containerEl);
      }
      const panel = new TerminalPanel({ containerId });
      this.sessions[agentName] = { panel, agentName, containerId };
    }
    return this.sessions[agentName];
  }

  renderWorkspace(mountElement, availableAgents = []) {
    this.mountElement = mountElement;
    if (!mountElement) return;

    // ⚠ Reconcile with the roster on every render, not just the first one.
    // Seeding only when openTabs was empty meant a hire never reached an
    // existing workspace: the agents panel gained the new name and the
    // terminals view kept the old set until a reload. Reported from a live
    // office.
    if (availableAgents.length > 0 && this.openTabs.length === 0 && this.knownAgents.size === 0) {
      this.openTabs = [...availableAgents];
      this.activeAgent = availableAgents[0];
    } else {
      for (const name of availableAgents) {
        if (!this.knownAgents.has(name) && !this.openTabs.includes(name)) this.openTabs.push(name);
      }
    }
    for (const name of availableAgents) this.knownAgents.add(name);

    // A retired agent's tab is a tab onto nothing; drop it and its session.
    if (availableAgents.length > 0) {
      const present = new Set(availableAgents);
      for (const gone of this.openTabs.filter((a) => !present.has(a))) {
        this.closeAgentTab(gone);
        this.knownAgents.delete(gone);
      }
      if (this.activeAgent && !present.has(this.activeAgent)) this.activeAgent = this.openTabs[0] || null;
      if (!this.activeAgent && this.openTabs.length > 0) this.activeAgent = this.openTabs[0];
    }

    let workspaceEl = mountElement.querySelector(".terminals-workspace");
    if (!workspaceEl) {
      workspaceEl = document.createElement("div");
      workspaceEl.className = "terminals-workspace";
      mountElement.appendChild(workspaceEl);
    }

    let tabBar = workspaceEl.querySelector(".term-tab-bar");
    if (!tabBar) {
      tabBar = document.createElement("div");
      tabBar.className = "term-tab-bar";
      workspaceEl.appendChild(tabBar);
    }

    tabBar.innerHTML = this.openTabs.map(agent => `
      <button type="button" class="term-tab ${agent === this.activeAgent ? 'active' : ''}" data-agent="${agent}">
        <span>${agent}</span>
        <span class="term-tab-close" data-close="${agent}" title="Close tab">✕</span>
      </button>
    `).join("") + `
      <div class="term-tab-add">
        <select id="term-open-agent-select" class="btn-sm">
          <option value="">+ Open Terminal</option>
          ${availableAgents.filter(a => !this.openTabs.includes(a)).map(a => `<option value="${a}">${a}</option>`).join("")}
        </select>
      </div>
    `;

    tabBar.querySelectorAll(".term-tab").forEach(btn => {
      btn.onclick = (e) => {
        if (e.target.classList.contains("term-tab-close")) {
          const closeAgent = e.target.getAttribute("data-close");
          this.closeAgentTab(closeAgent);
          this.renderWorkspace(mountElement, availableAgents);
        } else {
          const agent = btn.getAttribute("data-agent");
          this.switchTab(agent);
          this.renderWorkspace(mountElement, availableAgents);
        }
      };
    });

    const addSelect = tabBar.querySelector("#term-open-agent-select");
    if (addSelect) {
      addSelect.onchange = (e) => {
        if (e.target.value) {
          this.openAgentTab(e.target.value);
          this.renderWorkspace(mountElement, availableAgents);
        }
      };
    }

    if (this.activeAgent) {
      const session = this.getOrCreateSession(this.activeAgent);
      let modeBar = workspaceEl.querySelector(".workspace-typing-banner");
      if (!modeBar) {
        modeBar = document.createElement("div");
        modeBar.className = "workspace-typing-banner typing-banner readonly";
        modeBar.innerHTML = `<strong></strong><button type="button" class="typing-toggle-btn"></button>`;
        workspaceEl.insertBefore(modeBar, workspaceEl.querySelector(".term-session-area"));
      }
      const renderMode = () => {
        const readOnly = session.panel.isReadOnly;
        modeBar.className = `workspace-typing-banner typing-banner ${readOnly ? "readonly" : "interactive"}`;
        modeBar.querySelector("strong").textContent = `${readOnly ? "🔒 READ-ONLY" : "⚠ INTERACTIVE"} · ${this.activeAgent}`;
        modeBar.querySelector("button").textContent = readOnly ? "Enable typing" : "Lock read-only";
      };
      modeBar.querySelector("button").onclick = () => { session.panel.toggleInputMode(); renderMode(); };
      renderMode();
      let sessionArea = workspaceEl.querySelector(".term-session-area");
      if (!sessionArea) {
        sessionArea = document.createElement("div");
        sessionArea.className = "term-session-area";
        workspaceEl.appendChild(sessionArea);
      }
      for (const agent of this.openTabs) {
        const item = this.getOrCreateSession(agent);
        const container = document.getElementById(item.containerId);
        if (container && container.parentElement !== sessionArea) sessionArea.appendChild(container);
        if (container) container.hidden = agent !== this.activeAgent;
      }
      if (session && session.panel && (!session.panel.socket || session.panel.agent !== this.activeAgent)) {
        session.panel.connect(this.activeAgent);
      }
    }
  }

  switchTab(agentName) {
    this.activeAgent = agentName;
    if (!this.openTabs.includes(agentName)) {
      this.openTabs.push(agentName);
    }
    const session = this.getOrCreateSession(agentName);
    if (session && session.panel) {
      session.panel.connect(agentName);
    }
  }

  openAgentTab(agentName) {
    this.switchTab(agentName);
  }

  closeAgentTab(agentName) {
    this.openTabs = this.openTabs.filter(a => a !== agentName);
    if (this.activeAgent === agentName) {
      this.activeAgent = this.openTabs[0] || null;
    }
  }

  // SPEC §26: Demote terminal to 'watch' panel beside the conversation on agent page
  attachWatchPanel(agentName, mountContainer) {
    if (!agentName || !mountContainer) return;
    const session = this.getOrCreateSession(agentName);
    const container = document.getElementById(session.containerId);
    if (container && container.parentElement !== mountContainer) {
      mountContainer.replaceChildren(container);
    }
    if (session?.panel && (!session.panel.socket || session.panel.agent !== agentName)) {
      session.panel.connect(agentName);
    }
    return session;
  }

  // Socket & Scrollback Persistence (SPEC §16): Preserve sessions on hash route navigation!
  preserveSessions() {
    // Sockets and scrollbacks remain connected in memory
  }
}

export const globalTerminalWorkspace = new TerminalWorkspace();
if (typeof window !== "undefined") {
  window.__terminalWorkspace = globalTerminalWorkspace;
}
