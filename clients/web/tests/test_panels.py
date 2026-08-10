"""Static contract checks for the zero-build console panel assets."""

from pathlib import Path


WEB_DIR = Path(__file__).resolve().parent.parent


def test_token_not_in_browser_assets():
    for path in [WEB_DIR / "index.html", WEB_DIR / "app.js", WEB_DIR / "style.css", *sorted((WEB_DIR / "ui").glob("*.js"))]:
        content = path.read_text(encoding="utf-8")
        assert "API_TOKEN" not in content
        assert "Authorization" not in content


def test_panel_modules_and_required_states_ship_without_a_build_step():
    for name in ("agents", "alerts", "boards", "activity", "messages", "terminal"):
        assert (WEB_DIR / "ui" / f"{name}.js").exists()
    shared = (WEB_DIR / "ui" / "shared.js").read_text(encoding="utf-8")
    for state in ("loading", "empty", "error", "stale", "disconnected"):
        assert state in shared
    assert not (WEB_DIR / "package.json").exists()


def test_accessible_panel_mounts_and_terminal_controls():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for panel in ("agents-panel", "alerts-panel", "boards-panel", "terminal-panel"):
        assert f'id="{panel}"' in html
    for element in ("terminal-container", "terminal-mode-badge", "terminal-live-announcer", "toggle-input-mode"):
        assert f'id="{element}"' in html
    assert 'aria-live="assertive"' in html
