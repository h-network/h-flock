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
    assert "this.items.slice(0, 300)" in alerts
    assert "const groups = new Map()" in alerts
    assert "repeats" in alerts
    assert "content-visibility: auto" in styles
    assert "scrollbar-gutter: stable" in styles
    assert ".alerts-panel:has(#alerts-status.state-loading)" in styles
    assert ".alerts-panel:has(#alerts-status.state-empty)" in styles
    assert "content: none; display: none" in styles
    assert "capped at the newest 300" in readme


def test_part_two_product_controls_and_preferences_ship_as_modules():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for module in ("palette", "preferences", "notifications"):
        assert (WEB_DIR / "ui" / f"{module}.js").exists()
        assert f'./ui/{module}.js' in app
    for element in (
        "global-search", "search-results-summary", "command-dialog",
        "shortcuts-dialog", "preferences-dialog", "notification-control",
    ):
        assert f'id="{element}"' in html
    assert "hflock.console.preferences.v1" in (WEB_DIR / "ui" / "preferences.js").read_text(encoding="utf-8")
    assert "API_TOKEN" not in (WEB_DIR / "ui" / "preferences.js").read_text(encoding="utf-8")


def test_global_search_filters_all_data_panels():
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "agents.setFilter(query)" in app
    assert "alerts.setFilter(query)" in app
    assert "boards.setFilter(query)" in app
    for module in ("agents.js", "alerts.js", "boards.js"):
        assert "setFilter(value)" in (WEB_DIR / "ui" / module).read_text(encoding="utf-8")


def test_composer_shortcuts_and_history_are_explicit():
    messages = (WEB_DIR / "ui" / "messages.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'event.key === "Enter" && (event.ctrlKey || event.metaKey)' in messages
    assert "this.sentHistory" in messages
    assert "a reply may never come" in html


def test_agent_page_is_a_two_sided_conversation_with_inline_safe_activity():
    messages = (WEB_DIR / "ui" / "messages.js").read_text(encoding="utf-8")
    activity = (WEB_DIR / "ui" / "activity.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert 'api(`/agents/${encodeURIComponent(agent)}/conversation`)' in messages
    assert 'envelope.direction === "outbound"' in messages
    assert 'source === this.client' in messages
    assert "unverified source" in messages
    assert "unverified client identity" in messages
    assert 'event.kind !== "tool"' in messages
    assert "event.tool" in messages
    assert "event.payload" not in messages
    assert "this.onEvent(event)" in activity
    assert "not accepting messages" in messages
    assert 'id="messages-view" class="conversation-view"' in html


def test_notification_delivery_waits_for_resolvable_alert_lifecycle():
    notifications = (WEB_DIR / "ui" / "notifications.js").read_text(encoding="utf-8")
    assert "Notification.requestPermission()" in notifications
    assert "this.muted" in notifications
    assert "alert.resolved || alert.cleared" in notifications
    assert "new Notification(" not in notifications


def test_keyboard_focus_and_relative_timestamp_contracts():
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    agents = (WEB_DIR / "ui" / "agents.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for key in ("ArrowDown", "ArrowUp", "Home", "End"):
        assert key in agents
    assert '$("detail-title").focus()' in app
    assert 'class="conversation-view"' in html
    assert 'id="watch-agent"' in html
    assert 'className = "roster-table"' in agents
    assert 'scope="col"' in agents
    assert 'data-sort=' in agents
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


def test_empty_office_and_scaled_roster_are_deliberate_states():
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    agents = (WEB_DIR / "ui" / "agents.js").read_text(encoding="utf-8")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    assert 'id="empty-office"' in html
    assert 'id="empty-office-hire"' in html
    assert '$("empty-office").hidden = summary.staffed !== 0' in app
    assert '$("empty-office-hire").onclick' in app
    assert 'detail.port_type === "tmux"' in agents
    assert '["blocked", "unknown", "pending", "working", "idle"]' in agents
    assert 'presence === "blocked" ? " · action required"' in agents
    assert "position: sticky" in styles


def test_office_summary_combines_roster_health_and_alert_count():
    app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    alerts = (WEB_DIR / "ui" / "alerts.js").read_text(encoding="utf-8")
    assert "const { working, blocked } = state.roster" in app
    assert "state.alertCount" in app
    assert "this.onCount(this.items.length)" in alerts
    assert "summary-attention" in app
