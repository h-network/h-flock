"""Tests for clients/web/ (the Build 33 console UI & terminal panel)."""

import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent


def test_token_not_in_browser_assets():
    """Security check (SPEC.md §6 & §8): API token MUST NOT be in browser JS/HTML/CSS."""
    for relative_path in (
        "index.html",
        "app.js",
        "ui/terminal.js",
        "style.css",
        "terminal.css",
        "vendor/xterm.js",
        "vendor/xterm.css",
    ):
        file_path = WEB_DIR / relative_path
        assert file_path.exists(), f"Missing web asset: {relative_path}"
        content = file_path.read_text(encoding="utf-8")
        assert "API_TOKEN" not in content, f"API_TOKEN reference found in browser asset {relative_path}"
        assert "Authorization" not in content, f"Authorization header reference found in browser asset {relative_path}"


def test_xterm_and_terminal_js_vendored():
    """Verify xterm.js, terminal.js and stylesheets are present in clients/web/."""
    assert (WEB_DIR / "vendor" / "xterm.js").exists()
    assert (WEB_DIR / "vendor" / "xterm.css").exists()
    assert (WEB_DIR / "ui" / "terminal.js").exists()
    assert (WEB_DIR / "terminal.css").exists()
    js_content = (WEB_DIR / "vendor" / "xterm.js").read_text(encoding="utf-8")
    assert "Terminal" in js_content, "xterm.js does not export Terminal"


def test_index_html_terminal_panel_elements_and_aria():
    """Verify index.html contains terminal panel markup, ARIA roles, and screen reader live region."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="terminal-panel"' in html
    assert 'aria-label="Watch agent terminal"' in html
    assert 'id="watch-agent"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="terminal-container"' in html
    assert 'id="terminal-mode-badge"' in html
    assert 'id="terminal-live-announcer"' in html
    assert 'aria-live="polite"' in html
    assert 'id="toggle-input-mode"' in html
    assert 'href="vendor/xterm.css"' in html
    assert 'href="terminal.css"' in html
    assert 'src="vendor/xterm.js"' in html
    assert 'src="app.js"' in html


def test_terminal_js_safety_accessibility_and_themes():
    """Verify ui/terminal.js implements 120x32 geometry, 5 panel states, Escape key handling, and prefers-color-scheme."""
    js = (WEB_DIR / "ui" / "terminal.js").read_text(encoding="utf-8")
    assert "cols: 120" in js
    assert "rows: 32" in js
    assert "this.isReadOnly = true" in js
    assert "READ-ONLY" in js
    assert "INTERACTIVE (TYPING)" in js

    # 5 panel states
    assert "loading" in js
    assert "empty" in js
    assert "error" in js
    assert "stale" in js
    assert "disconnected" in js

    # Accessibility & Keyboard Escape handling
    assert "attachCustomKeyEventHandler" in js
    assert "Escape" in js
    assert "_announce" in js

    # Prefers color scheme support
    assert "prefers-color-scheme: light" in js
    assert "lightTheme" in js
    assert "darkTheme" in js


def test_terminal_js_readonly_guarantee_and_bypass_protection():
    """Security audit check: Prove read-only guarantee cannot be bypassed via disableStdin or onData."""
    js = (WEB_DIR / "ui" / "terminal.js").read_text(encoding="utf-8")
    # Dual-layer protection: xterm engine level + application logic level
    assert "disableStdin: this.isReadOnly" in js
    assert "this.term.options.disableStdin = this.isReadOnly" in js
    assert "if (!this.isReadOnly && this.socket && this.socket.readyState === WebSocket.OPEN && this.agent)" in js
    assert 'mode: initialMode' in js or 'mode: mode' in js


def test_terminal_part_ii_overengineering_features():
    """SPEC §12 Over-engineering verification: search, copy/paste protection, local storage persistence, multi-grid & recording."""
    js = (WEB_DIR / "ui" / "terminal.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # 1. Scrollback search & vendored addon
    assert (WEB_DIR / "vendor" / "xterm-addon-search.js").exists()
    assert 'src="vendor/xterm-addon-search.js"' in html
    assert "terminal-search-input" in html
    assert "searchAddon" in js
    assert "findNext" in js

    # 2. Copy/paste protection & multi-line warning modal
    assert "paste-confirm-dialog" in html
    assert "Paste blocked: Terminal is in READ-ONLY mode" in js
    assert "_showPasteConfirmationModal" in js

    # 3. LocalStorage settings persistence (font size & scrollback depth)
    assert "hflock.terminal.fontSize" in js
    assert "hflock.terminal.scrollback" in js

    # 4. Multi-terminal side-by-side grid
    assert "terminal-multi-grid" in html
    assert "term-view-single" in html
    assert "term-view-split" in html
    assert "term-view-grid" in html

    # 5. Session recording & replay player
    assert "record-session-btn" in html
    assert "session-replay-bar" in html
    assert "recordingFrames" in js
    assert "startReplay" in js
    assert "_handleRecordingCapReached" in js
    assert "res.status === 413" in js
    assert "recording-full" in js


def test_terminal_part_iii_workspace_features():
    """SPEC Part III §15-16 verification: TerminalWorkspace singleton session manager & prominent typing banner."""
    js = (WEB_DIR / "ui" / "terminal.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # 1. Prominent Typing Banner
    assert "terminal-typing-banner" in html
    assert "terminal-typing-banner-btn" in html
    assert "typing-banner" in js
    assert "READ-ONLY MODE" in js

    # 2. TerminalWorkspace persistent session manager across navigation
    assert "TerminalWorkspace" in js
    assert "globalTerminalWorkspace" in js
    assert "preserveSessions" in js


def test_terminal_part_v_demoted_watch_panel():
    """SPEC Part V §26 verification: Terminal demoted to 'watch' panel beside conversation."""
    js = (WEB_DIR / "ui" / "terminal.js").read_text(encoding="utf-8")
    assert "attachWatchPanel" in js



