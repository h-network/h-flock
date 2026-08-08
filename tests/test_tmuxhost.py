import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from flock.tmuxhost.host import TmuxHost, generate_agents_md, write_agent_guide, ensure_claude_project_trusted


class MockRedis:
    def __init__(self, roster_agents, vab_map=None, launch_map=None):
        self.roster_agents = set(roster_agents)
        self.vab_map = vab_map or {a: "tmux" for a in roster_agents}
        self.launch_map = launch_map or {}

    def get(self, key):
        for agent, cli in self.launch_map.items():
            if f":agent:{agent}:launch" in key:
                return cli.encode("utf-8") if isinstance(cli, str) else cli
        return None

    def hkeys(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}

    def hget(self, key, field):
        val = self.vab_map.get(field)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val

    def smembers(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_reconciliation(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "", ""),  # new-window alice
        (0, "__init__\nalice", ""),  # list-windows 2
        (0, "", ""),  # kill-window __init__
    ]

    r = MockRedis(["alice"])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    assert any("new-window" in c for c in calls)
    assert any("kill-window" in c for c in calls)


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_ensure_session_with_roster_agent(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (1, "", "no server running"),  # has-session -> 1 (not existing)
        (0, "", ""),  # new-session -d -s hq -n alice ...
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "alice", ""),  # list-windows 1 -> alice
        (0, "alice", ""),  # list-windows 2 -> alice
    ]

    r = MockRedis(["alice"])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    assert any("new-session" in c for c in calls)


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_filters_non_tmux_vab(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "alice", ""),  # list-windows 1
        (0, "alice", ""),  # list-windows 2
    ]

    r = MockRedis(["alice", "api"], vab_map={"alice": "tmux", "api": "api"})
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    assert not any("api" in c for c in calls)


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_reconciles_office_tools_and_agent_guide_env(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "", ""),  # new-window alice
        (0, "__init__\nalice", ""),  # list-windows 2
        (0, "", ""),  # kill-window __init__
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        r = MockRedis(["alice"])
        host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
        host.reconcile_once(r)

        calls = [c[0] for c in mock_run_tmux.call_args_list]
        env_calls = [c for c in calls if "new-window" in c]
        assert any("OFFICE_TOOLS=office" in " ".join(c) for c in env_calls)
        assert any("AGENT_GUIDE=/workdir/alice/AGENTS.md" in " ".join(c) for c in env_calls)


def test_generate_agents_md():
    content = generate_agents_md("dave", "hq")
    assert "You are **dave**, an agent in this office." in content
    assert "$AGENT_NAME" in content
    assert "$TENANT" in content
    assert "$OFFICE_TOOLS" in content
    assert "office peers" in content
    assert "[message from alice] …" in content
    assert "office send" in content


def test_write_agent_guide_creates_both_files_and_trusts_claude():
    with tempfile.TemporaryDirectory() as tmp_workdir:
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch.dict(os.environ, {"HOME": tmp_home}):
                write_agent_guide(tmp_workdir, "dave", "hq")

                agents_path = os.path.join(tmp_workdir, "AGENTS.md")
                claude_path = os.path.join(tmp_workdir, "CLAUDE.md")
                assert os.path.exists(agents_path)
                assert os.path.exists(claude_path)

                with open(agents_path, "r", encoding="utf-8") as f:
                    agents_content = f.read()
                with open(claude_path, "r", encoding="utf-8") as f:
                    claude_content = f.read()

                assert agents_content == claude_content
                assert "You are **dave**, an agent in this office." in agents_content

                # Verify .claude.json pre-approval
                config_path = os.path.join(tmp_home, ".claude.json")
                assert os.path.exists(config_path)
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                assert data["projects"][tmp_workdir]["hasTrustDialogAccepted"] is True
                assert data["projects"][tmp_workdir]["hasCompletedProjectOnboarding"] is True
