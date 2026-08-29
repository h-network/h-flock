"""Tests for per-agent AGENT_SKIP_PERMISSIONS / AGENT_CLAUDE_TOOLS threading:
window_env, the StartAgent control opener, TmuxHost, and `office hire`.
"""

from unittest.mock import patch, MagicMock

import pytest

from conftest import FakeRedis
from flock.bus import prefix
from flock.control import start_agent
from flock.office.cli import main as office_main
from flock.tmux.ops import window_env
from flock.tmuxhost.host import TmuxHost


# ---------------------------------------------------------------------------
# window_env unit tests
# ---------------------------------------------------------------------------

def test_window_env_omits_both_vars_by_default():
    env = window_env("dave", cwd="/workdir/dave")
    assert not any(v.startswith("AGENT_SKIP_PERMISSIONS=") for v in env)
    assert not any(v.startswith("AGENT_CLAUDE_TOOLS=") for v in env)


def test_window_env_skip_permissions_true_and_false():
    assert "AGENT_SKIP_PERMISSIONS=1" in window_env("dave", cwd="/workdir/dave", skip_permissions=True)
    assert "AGENT_SKIP_PERMISSIONS=0" in window_env("dave", cwd="/workdir/dave", skip_permissions=False)


def test_window_env_claude_tools_empty_string_is_a_real_value_not_absence():
    env = window_env("dave", cwd="/workdir/dave", claude_tools="")
    assert "AGENT_CLAUDE_TOOLS=" in env
    env_none = window_env("dave", cwd="/workdir/dave", claude_tools=None)
    assert not any(v.startswith("AGENT_CLAUDE_TOOLS=") for v in env_none)


def test_window_env_claude_tools_custom_list():
    env = window_env("dave", cwd="/workdir/dave", claude_tools="Bash Read")
    assert "AGENT_CLAUDE_TOOLS=Bash Read" in env


# ---------------------------------------------------------------------------
# StartAgent control opener tests
# ---------------------------------------------------------------------------

def test_start_agent_writes_skip_permissions_true_and_false():
    events = []
    r = FakeRedis(events)
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "skip_permissions": False}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "skip-permissions"), "0") in events

    events.clear()
    r = FakeRedis(events)
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "skip_permissions": True}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "skip-permissions"), "1") in events


def test_start_agent_rejects_non_boolean_skip_permissions():
    r = FakeRedis([])
    with pytest.raises(ValueError, match="StartAgent payload.skip_permissions must be a boolean"):
        start_agent(
            r, pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave", "skip_permissions": "yes"}},
            replace_window=lambda agent: None,
        )


def test_start_agent_writes_claude_tools_including_empty_string():
    events = []
    r = FakeRedis(events)
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "claude_tools": ""}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "claude-tools"), "") in events

    events.clear()
    r = FakeRedis(events)
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "claude_tools": "Bash Read"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "claude-tools"), "Bash Read") in events


def test_start_agent_omitted_claude_tools_writes_nothing():
    events = []
    r = FakeRedis(events)
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert not any(event[0] == "set" and "claude-tools" in event[1] for event in events)


def test_start_agent_rejects_non_string_claude_tools():
    r = FakeRedis([])
    with pytest.raises(ValueError, match="StartAgent payload.claude_tools must be a string"):
        start_agent(
            r, pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave", "claude_tools": 5}},
            replace_window=lambda agent: None,
        )


def test_start_agent_skip_permissions_config_change_replaces_window():
    events = []
    skip_key = prefix("acme", "hq", "dave", "skip-permissions")
    r = FakeRedis(
        events, roster_port_type="tmux",
        data={
            prefix("acme", "hq", "dave", "launch"): b"claude",
            skip_key: b"1",
        },
    )
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "skip_permissions": False}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", skip_key, "0") in events
    assert ("replace_window", "dave") in events


def test_start_agent_claude_tools_config_change_replaces_window():
    events = []
    tools_key = prefix("acme", "hq", "dave", "claude-tools")
    r = FakeRedis(
        events, roster_port_type="tmux",
        data={
            prefix("acme", "hq", "dave", "launch"): b"claude",
            tools_key: b"",
        },
    )
    start_agent(
        r, pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "claude_tools": "Bash"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", tools_key, "Bash") in events
    assert ("replace_window", "dave") in events


# ---------------------------------------------------------------------------
# TmuxHost threading tests
# ---------------------------------------------------------------------------

@patch("flock.tmux.ops.create_window")
def test_tmuxhost_create_window_threads_skip_permissions_and_claude_tools(mock_create_window):
    mock_create_window.return_value = (0, "", "")
    r = FakeRedis([])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    host.create_window(r, "dave", skip_permissions=False, claude_tools="")

    created_cmd = mock_create_window.call_args[1]["command"]
    assert "AGENT_SKIP_PERMISSIONS=0" in created_cmd
    assert "AGENT_CLAUDE_TOOLS=" in created_cmd


@patch("flock.tmux.ops.create_window")
def test_tmuxhost_create_window_omits_vars_when_unset(mock_create_window):
    mock_create_window.return_value = (0, "", "")
    r = FakeRedis([])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    host.create_window(r, "dave")

    created_cmd = mock_create_window.call_args[1]["command"]
    assert not any(v.startswith("AGENT_SKIP_PERMISSIONS=") for v in created_cmd)
    assert not any(v.startswith("AGENT_CLAUDE_TOOLS=") for v in created_cmd)


def test_tmuxhost_get_agent_skip_permissions_absent_vs_set():
    r = FakeRedis([])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    assert host.get_agent_skip_permissions(r, "dave") is None

    r.values[prefix("acme", "hq", "dave", "skip-permissions")] = b"0"
    assert host.get_agent_skip_permissions(r, "dave") is False

    r.values[prefix("acme", "hq", "dave", "skip-permissions")] = b"1"
    assert host.get_agent_skip_permissions(r, "dave") is True


def test_tmuxhost_get_agent_claude_tools_absent_vs_empty():
    r = FakeRedis([])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    assert host.get_agent_claude_tools(r, "dave") is None

    r.values[prefix("acme", "hq", "dave", "claude-tools")] = b""
    assert host.get_agent_claude_tools(r, "dave") == ""

    r.values[prefix("acme", "hq", "dave", "claude-tools")] = b"Bash Read"
    assert host.get_agent_claude_tools(r, "dave") == "Bash Read"


@patch("flock.tmux.ops.create_window")
def test_tmuxhost_reconcile_reads_per_agent_permissions_and_tools(mock_create_window):
    mock_create_window.return_value = (0, "", "")
    r = FakeRedis([], roster_agents=["dave"], port_type_map={"dave": "tmux"})
    r.values[prefix("acme", "hq", "dave", "launch")] = "claude"
    r.values[prefix("acme", "hq", "dave", "resume")] = b"0"
    r.values[prefix("acme", "hq", "dave", "skip-permissions")] = b"0"
    r.values[prefix("acme", "hq", "dave", "claude-tools")] = b""
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    with patch.object(host, "get_windows", return_value=set()), \
         patch.object(host, "ensure_server_and_session"):
        host.reconcile_once(r)

    created_cmd = mock_create_window.call_args[1]["command"]
    assert "AGENT_SKIP_PERMISSIONS=0" in created_cmd
    assert "AGENT_CLAUDE_TOOLS=" in created_cmd


# ---------------------------------------------------------------------------
# office hire CLI tests
# ---------------------------------------------------------------------------

@patch("flock.office.cli.send")
@patch("flock.office.cli._context")
def test_office_hire_skip_permissions_flags(mock_context, mock_send):
    mock_context.return_value = (MagicMock(), "acme", "hq", "architect")
    mock_send.return_value = "stream-123"

    office_main(["hire", "worker-1", "--cli", "claude"])
    payload = mock_send.call_args[1]["payload"]
    assert "skip_permissions" not in payload

    office_main(["hire", "worker-1", "--cli", "claude", "--skip-permissions"])
    payload = mock_send.call_args[1]["payload"]
    assert payload["skip_permissions"] is True

    office_main(["hire", "worker-1", "--cli", "claude", "--no-skip-permissions"])
    payload = mock_send.call_args[1]["payload"]
    assert payload["skip_permissions"] is False


@patch("flock.office.cli.send")
@patch("flock.office.cli._context")
def test_office_hire_claude_tools_flag_including_empty(mock_context, mock_send):
    mock_context.return_value = (MagicMock(), "acme", "hq", "architect")
    mock_send.return_value = "stream-123"

    office_main(["hire", "worker-1", "--cli", "claude"])
    payload = mock_send.call_args[1]["payload"]
    assert "claude_tools" not in payload

    office_main(["hire", "worker-1", "--cli", "claude", "--claude-tools", ""])
    payload = mock_send.call_args[1]["payload"]
    assert payload["claude_tools"] == ""

    office_main(["hire", "worker-1", "--cli", "claude", "--claude-tools", "Bash Read"])
    payload = mock_send.call_args[1]["payload"]
    assert payload["claude_tools"] == "Bash Read"


@patch("flock.office.cli.send")
@patch("flock.office.cli._context")
def test_office_hire_skip_permissions_mutually_exclusive(mock_context, mock_send, capsys):
    mock_context.return_value = (MagicMock(), "acme", "hq", "architect")
    with pytest.raises(SystemExit):
        office_main(
            ["hire", "worker-1", "--cli", "claude", "--skip-permissions", "--no-skip-permissions"]
        )
    assert "not allowed" in capsys.readouterr().err
