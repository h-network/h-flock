"""Tests for session history detection, StartAgent resume handling, and tmux_reconciler resume commands."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from conftest import FakeRedis
from flock.bus import prefix
from flock.control import start_agent, stop_agent
from flock.office.cli import main as office_main
from flock.tmux.ops import has_session_history, start_agent_command
from flock.tmux_reconciler.service import TmuxReconciler


# ---------------------------------------------------------------------------
# has_session_history unit tests
# ---------------------------------------------------------------------------

def test_has_session_history_claude(tmp_path):
    agent = "worker-1"
    # 1. No project directory
    assert has_session_history(agent, "claude", home_root=tmp_path) is False

    # 2. Empty project directory
    proj_dir = tmp_path / ".claude" / "projects" / f"-workdir-{agent}"
    proj_dir.mkdir(parents=True)
    assert has_session_history(agent, "claude", home_root=tmp_path) is False

    # 3. Project directory with 0-byte jsonl
    empty_file = proj_dir / "empty.jsonl"
    empty_file.write_text("")
    assert has_session_history(agent, "claude", home_root=tmp_path) is False

    # 4. Project directory with valid non-empty jsonl
    session_file = proj_dir / "session-123.jsonl"
    session_file.write_text('{"type": "message", "text": "hello"}\n')
    assert has_session_history(agent, "claude", home_root=tmp_path) is True


def test_has_session_history_claude_profiled(tmp_path):
    agent = "worker-prof"
    profile = "custom-account"

    # Default .claude has nothing
    assert has_session_history(agent, "claude", profile=profile, home_root=tmp_path) is False

    # Profile directory has session
    proj_dir = tmp_path / f".claude-{profile}" / "projects" / f"-workdir-{agent}"
    proj_dir.mkdir(parents=True)
    (proj_dir / "session-abc.jsonl").write_text('{"type": "init"}\n')

    assert has_session_history(agent, "claude", profile=profile, home_root=tmp_path) is True
    # Without profile parameter, checks default .claude (which is empty) -> False
    assert has_session_history(agent, "claude", profile=None, home_root=tmp_path) is False


def test_has_session_history_codex(tmp_path):
    agent = "worker-codex"
    # 1. No sessions directory
    assert has_session_history(agent, "codex", home_root=tmp_path) is False

    # 2. Sessions directory with rollout belonging to another agent
    sessions_dir = tmp_path / ".codex" / "sessions" / "2026" / "08" / "27"
    sessions_dir.mkdir(parents=True)
    other_rollout = sessions_dir / "rollout-other.jsonl"
    other_rollout.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"cwd": "/workdir/other-agent"}
    }) + "\n")
    assert has_session_history(agent, "codex", home_root=tmp_path) is False

    # 3. Rollout belonging to this agent
    my_rollout = sessions_dir / "rollout-mine.jsonl"
    my_rollout.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"cwd": f"/workdir/{agent}"}
    }) + "\n")
    assert has_session_history(agent, "codex", home_root=tmp_path) is True


def test_has_session_history_codex_profiled(tmp_path):
    agent = "worker-codex-prof"
    profile = "special"

    sessions_dir = tmp_path / f".codex-{profile}" / "sessions" / "2026" / "08"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "rollout-1.jsonl").write_text(json.dumps({
        "type": "session_meta",
        "payload": {"cwd": f"/workdir/{agent}"}
    }) + "\n")

    assert has_session_history(agent, "codex", profile=profile, home_root=tmp_path) is True
    assert has_session_history(agent, "codex", profile=None, home_root=tmp_path) is False


def test_has_session_history_agy(tmp_path):
    agent = "worker-agy"
    # 1. No history.jsonl
    assert has_session_history(agent, "agy", home_root=tmp_path) is False

    # 2. history.jsonl with lines for other workspaces
    agy_dir = tmp_path / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True)
    hist_file = agy_dir / "history.jsonl"
    hist_file.write_text(json.dumps({"workspace": "/workdir/other", "text": "foo"}) + "\n")
    assert has_session_history(agent, "agy", home_root=tmp_path) is False

    # 3. history.jsonl with matching workspace line
    with hist_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"workspace": f"/workdir/{agent}", "text": "bar"}) + "\n")
    assert has_session_history(agent, "agy", home_root=tmp_path) is True


# ---------------------------------------------------------------------------
# start_agent_command unit tests
# ---------------------------------------------------------------------------

def test_start_agent_command_fresh():
    assert start_agent_command("claude", resume=False) == ["startAgent", "claude"]
    assert start_agent_command("codex", resume=False) == ["startAgent", "codex"]
    assert start_agent_command("agy", resume=False) == ["startAgent", "agy"]


def test_start_agent_command_resume():
    assert start_agent_command("claude", resume=True) == ["startAgent", "claude", "--resume"]
    assert start_agent_command("codex", resume=True) == ["startAgent", "codex", "resume", "--last"]
    assert start_agent_command("agy", resume=True) == ["startAgent", "agy", "--continue"]


# ---------------------------------------------------------------------------
# StartAgent control opener tests
# ---------------------------------------------------------------------------

def test_start_agent_with_explicit_resume_true():
    events = []
    r = FakeRedis(events)
    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "resume": True}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "resume"), "1") in events


def test_start_agent_with_explicit_resume_false():
    events = []
    r = FakeRedis(events)
    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "resume": False}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", prefix("acme", "hq", "dave", "resume"), "0") in events


def test_start_agent_rejects_invalid_resume_type():
    r = FakeRedis([])
    with pytest.raises(ValueError, match="StartAgent payload.resume must be a boolean"):
        start_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "resume": "invalid"}},
            replace_window=lambda agent: None,
        )


def test_start_agent_resume_config_change_replaces_window():
    events = []
    resume_key = prefix("acme", "hq", "dave", "resume")
    r = FakeRedis(
        events,
        roster_port_type="tmux",
        data={
            prefix("acme", "hq", "dave", "launch"): b"claude",
            resume_key: b"0",
        },
    )
    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "claude", "resume": True}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert ("set", resume_key, "1") in events
    assert ("replace_window", "dave") in events


# ---------------------------------------------------------------------------
# TmuxReconciler window creation & resume auto-detection tests
# ---------------------------------------------------------------------------

@patch("flock.tmux.ops.create_window")
@patch("flock.tmux.ops.has_session_history")
def test_tmux_reconciler_auto_detects_and_resumes_when_history_exists(mock_has_history, mock_create_window):
    mock_has_history.return_value = True
    mock_create_window.return_value = (0, "", "")

    r = FakeRedis([])
    host = TmuxReconciler(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    # resume is None in Redis -> triggers auto-detection
    host.create_window(r, "dave", cli="claude")

    mock_has_history.assert_called_once_with("dave", "claude", profile=None)
    created_cmd = mock_create_window.call_args[1]["command"]
    assert "startAgent" in created_cmd
    assert "--resume" in created_cmd


@patch("flock.tmux.ops.create_window")
@patch("flock.tmux.ops.has_session_history")
def test_tmux_reconciler_auto_detects_and_starts_fresh_when_no_history(mock_has_history, mock_create_window):
    mock_has_history.return_value = False
    mock_create_window.return_value = (0, "", "")

    r = FakeRedis([])
    host = TmuxReconciler(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    host.create_window(r, "dave", cli="claude")

    mock_has_history.assert_called_once_with("dave", "claude", profile=None)
    created_cmd = mock_create_window.call_args[1]["command"]
    assert "--resume" not in created_cmd
    assert created_cmd[-2:] == ["startAgent", "claude"]


@patch("flock.tmux.ops.create_window")
@patch("flock.tmux.ops.has_session_history")
def test_tmux_reconciler_explicit_fresh_overrides_existing_history(mock_has_history, mock_create_window):
    mock_create_window.return_value = (0, "", "")

    r = FakeRedis([])
    host = TmuxReconciler(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    # Explicit resume=False passed (or read from resume key = '0')
    host.create_window(r, "dave", cli="claude", resume=False)

    mock_has_history.assert_not_called()
    created_cmd = mock_create_window.call_args[1]["command"]
    assert "--resume" not in created_cmd
    assert created_cmd[-2:] == ["startAgent", "claude"]


@patch("flock.tmux.ops.create_window")
@patch("flock.tmux.ops.has_session_history")
def test_tmux_reconciler_reconcile_handles_codex_and_agy_resume(mock_has_history, mock_create_window):
    mock_has_history.return_value = True
    mock_create_window.return_value = (0, "", "")

    r = FakeRedis([])
    host = TmuxReconciler(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")

    # Codex resume
    host.create_window(r, "codex-bot", cli="codex")
    codex_cmd = mock_create_window.call_args[1]["command"]
    assert codex_cmd[-4:] == ["startAgent", "codex", "resume", "--last"]

    # Agy resume
    host.create_window(r, "agy-bot", cli="agy")
    agy_cmd = mock_create_window.call_args[1]["command"]
    assert agy_cmd[-3:] == ["startAgent", "agy", "--continue"]


# ---------------------------------------------------------------------------
# office hire CLI tests
# ---------------------------------------------------------------------------

@patch("flock.office.cli.send")
@patch("flock.office.cli._context")
def test_office_hire_flags(mock_context, mock_send):
    mock_context.return_value = (MagicMock(), "acme", "hq", "architect")
    mock_send.return_value = "stream-123"

    # Default hire (no resume flag)
    office_main(["hire", "worker-1", "--cli", "claude"])
    payload = mock_send.call_args[1]["payload"]
    assert payload == {"agent": "worker-1", "cli": "claude"}
    assert "resume" not in payload

    # Explicit --resume
    office_main(["hire", "worker-1", "--cli", "claude", "--resume"])
    payload_resume = mock_send.call_args[1]["payload"]
    assert payload_resume["resume"] is True

    # Explicit --fresh
    office_main(["hire", "worker-1", "--cli", "claude", "--fresh"])
    payload_fresh = mock_send.call_args[1]["payload"]
    assert payload_fresh["resume"] is False
