"""Static contract checks for the zero-build console panel assets."""

from pathlib import Path


WEB_DIR = Path(__file__).resolve().parent.parent


def test_token_not_in_browser_assets():
    for path in [WEB_DIR / "index.html", WEB_DIR / "app.js", WEB_DIR / "style.css", *sorted((WEB_DIR / "ui").glob("*.js"))]:
        content = path.read_text(encoding="utf-8")
        assert "API_TOKEN" not in content
        assert "Authorization" not in content


def test_panel_modules_and_required_states_ship_without_a_build_step():
    for name in ("agents", "alerts", "boards", "activity", "messages", "lifecycle", "terminal"):
        assert (WEB_DIR / "ui" / f"{name}.js").exists()
    shared = (WEB_DIR / "ui" / "shared.js").read_text(encoding="utf-8")
    for state in ("loading", "empty", "error", "stale", "disconnected"):
        assert state in shared
    assert "!isNewCursor(cursorValue, previous)" in shared
    assert not (WEB_DIR / "package.json").exists()


def test_accessible_panel_mounts_and_terminal_controls():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for panel in ("agents-panel", "alerts-panel", "boards-panel", "terminal-panel"):
        assert f'id="{panel}"' in html
    for element in ("terminal-container", "terminal-mode-badge", "terminal-live-announcer", "toggle-input-mode"):
        assert f'id="{element}"' in html
    assert 'aria-live="assertive"' in html


def test_lifecycle_uses_control_envelopes_and_safe_name_validation():
    lifecycle = (WEB_DIR / "ui" / "lifecycle.js").read_text(encoding="utf-8")
    for kind in ("StartAgent", "StopAgent", "PauseAgent", "ResumeAgent"):
        assert kind in lifecycle
    assert 'api("/agents/host/envelopes"' in lifecycle
    assert "(?![0-9]+$)" in lifecycle
    assert "queues and boards retained" in lifecycle
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert "Queues and boards survive" in html
    assert 'id="retire-confirm"' in html


def test_alert_load_is_capped_batched_and_layout_is_reserved():
    alerts = (WEB_DIR / "ui" / "alerts.js").read_text(encoding="utf-8")
    styles = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    readme = (WEB_DIR / "README.md").read_text(encoding="utf-8")
    assert "requestAnimationFrame" in alerts
    assert "document.createDocumentFragment" in alerts
    assert "root.children.length > 300" in alerts
    assert "content-visibility: auto" in styles
    assert "scrollbar-gutter: stable" in styles
    assert "capped at the newest 300" in readme


def test_keyboard_focus_and_relative_timestamp_contracts():
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    agents = (WEB_DIR / "ui" / "agents.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in app
    for key in ("ArrowDown", "ArrowUp", "Home", "End"):
        assert key in agents
    assert '$("detail-title").focus()' in app
    assert 'role="tablist"' in html
    assert 'role="listbox"' in html
    for module in ("activity.js", "messages.js", "alerts.js"):
        content = (WEB_DIR / "ui" / module).read_text(encoding="utf-8")
        assert "relativeTime(" in content
        assert "absoluteTime(" in content


def test_http_500_degrades_panels_without_claiming_network_failure():
    shared = (WEB_DIR / "ui" / "shared.js").read_text(encoding="utf-8")
    readme = (WEB_DIR / "README.md").read_text(encoding="utf-8")
    assert "error.status = response.status" in shared
    assert "if (hasData) status.stale" in shared
    assert "else status.error(error)" in shared
    assert "An HTTP 500 is not treated as a network drop" in readme
    assert "EventSource does not expose an SSE response status" in readme
