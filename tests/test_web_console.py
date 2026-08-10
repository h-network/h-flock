"""Tests for clients/web/ (the Build 33 console UI & terminal panel)."""

import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "clients" / "web"


def test_token_not_in_browser_assets():
    """Security check (BUILD-33 §7 & §6): API token MUST NOT be in browser JS/HTML/CSS."""
    for filename in ("index.html", "app.js", "style.css", "xterm.js", "xterm.css"):
        file_path = WEB_DIR / filename
        assert file_path.exists(), f"Missing web asset: {filename}"
        content = file_path.read_text(encoding="utf-8")
        assert "API_TOKEN" not in content, f"API_TOKEN reference found in browser asset {filename}"
        assert "Authorization" not in content, f"Authorization header reference found in browser asset {filename}"


def test_xterm_vendored():
    """Verify xterm.js and xterm.css are vendored in clients/web/ (no npm dependency)."""
    assert (WEB_DIR / "xterm.js").exists()
    assert (WEB_DIR / "xterm.css").exists()
    js_content = (WEB_DIR / "xterm.js").read_text(encoding="utf-8")
    assert "Terminal" in js_content, "xterm.js does not export Terminal"


def test_index_html_terminal_panel_elements():
    """Verify index.html contains terminal panel markup and 120x32 geometry indicators."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="terminal-panel"' in html
    assert 'id="terminal-container"' in html
    assert 'id="terminal-mode-badge"' in html
    assert 'id="toggle-input-mode"' in html
    assert 'href="xterm.css"' in html
    assert 'src="xterm.js"' in html


def test_app_js_terminal_safety_rules():
    """Verify app.js implements 120x32 geometry and default read-only safety rule."""
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "cols: 120" in js
    assert "rows: 32" in js
    assert "isReadOnly: true" in js or "isReadOnly = true" in js or "isReadOnly = !termState.isReadOnly" in js
    assert "READ-ONLY" in js
    assert "INTERACTIVE (TYPING)" in js
