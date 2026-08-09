import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from flock.tmuxhost.host import TmuxHost, generate_agents_md, write_agent_guide, ensure_claude_project_trusted


class MockRedis:
    def __init__(self, roster_agents, vab_map=None, launch_map=None, profile_map=None):
        self.roster_agents = set(roster_agents)
        self.vab_map = vab_map or {a: "tmux" for a in roster_agents}
        self.launch_map = launch_map or {}
        self.profile_map = profile_map or {}

    def get(self, key):
        for agent, cli in self.launch_map.items():
            if f":agent:{agent}:launch" in key:
                return cli.encode("utf-8") if isinstance(cli, str) else cli
        for agent, prof in self.profile_map.items():
            if f":agent:{agent}:profile" in key:
                return prof.encode("utf-8") if isinstance(prof, str) else prof
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
    assert "You have a task board." in content
    assert "office list" in content
    assert "office take" in content
    assert "office done" in content
    assert "Take a ticket *before* you start work" in content


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


@patch("flock.tmux.ops.run_tmux")
def test_create_window_directly_writes_guide_and_trust(mock_run_tmux):
    mock_run_tmux.return_value = (0, "", "")
    with tempfile.TemporaryDirectory() as tmp_workdir:
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch.dict(os.environ, {"HOME": tmp_home}):
                from flock.tmux.ops import create_window as shared_create_window
                shared_create_window("hq", "dave", command=["startAgent", "claude"], cwd=tmp_workdir)

                agents_path = os.path.join(tmp_workdir, "AGENTS.md")
                claude_path = os.path.join(tmp_workdir, "CLAUDE.md")
                assert os.path.exists(agents_path)
                assert os.path.exists(claude_path)

                config_path = os.path.join(tmp_home, ".claude.json")
                assert os.path.exists(config_path)
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                assert data["projects"][tmp_workdir]["hasTrustDialogAccepted"] is True


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_launches_cli_via_startagent(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "", ""),  # new-window dave
        (0, "__init__\ndave", ""),  # list-windows 2
        (0, "", ""),  # kill-window __init__
    ]

    r = MockRedis(["dave"], launch_map={"dave": "claude"})
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    new_window_calls = [c for c in calls if "new-window" in c]
    assert any("startAgent" in c and "claude" in c for c in new_window_calls)


def test_ensure_codex_project_trusted_hiring_twice():
    with tempfile.TemporaryDirectory() as tmp_home:
        with patch.dict(os.environ, {"HOME": tmp_home}):
            from flock.tmux.ops import ensure_codex_project_trusted

            codex_dir = os.path.join(tmp_home, ".codex")
            os.makedirs(codex_dir, exist_ok=True)
            config_path = os.path.join(codex_dir, "config.toml")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("check_for_update_on_startup = false\n")

            # Hire agent 1 (alice)
            ensure_codex_project_trusted("/workdir/alice")
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert 'check_for_update_on_startup = false' in content
            assert '[projects."/workdir/alice"]' in content
            assert 'trust_level = "trusted"' in content

            # Hire agent 2 (bob)
            ensure_codex_project_trusted("/workdir/bob")
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert '[projects."/workdir/alice"]' in content
            assert '[projects."/workdir/bob"]' in content

            # Re-hire agent 1 (alice) — verify no duplicate tables
            ensure_codex_project_trusted("/workdir/alice")
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content.count('[projects."/workdir/alice"]') == 1
            assert content.count('[projects."/workdir/bob"]') == 1


def test_ensure_agy_project_trusted_hiring_twice():
    with tempfile.TemporaryDirectory() as tmp_home:
        with patch.dict(os.environ, {"HOME": tmp_home}):
            from flock.tmux.ops import ensure_agy_project_trusted

            # Hire agent 1 (alice)
            ensure_agy_project_trusted("/workdir/alice")
            settings_path = os.path.join(tmp_home, ".gemini", "antigravity-cli", "settings.json")
            assert os.path.exists(settings_path)
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["enableTelemetry"] is False
            assert data["trustedWorkspaces"] == ["/workdir/alice"]

            # Hire agent 2 (bob)
            ensure_agy_project_trusted("/workdir/bob")
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["enableTelemetry"] is False
            assert data["trustedWorkspaces"] == ["/workdir/alice", "/workdir/bob"]

            # Re-hire agent 1 (alice) — verify no duplicate workspace entries
            ensure_agy_project_trusted("/workdir/alice")
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["trustedWorkspaces"] == ["/workdir/alice", "/workdir/bob"]


def test_write_agent_guide_trusts_all_clis():
    with tempfile.TemporaryDirectory() as tmp_workdir:
        with tempfile.TemporaryDirectory() as tmp_home:
            with patch.dict(os.environ, {"HOME": tmp_home}):
                write_agent_guide(tmp_workdir, "dave", "hq")

                # Check Claude trust
                claude_config = os.path.join(tmp_home, ".claude.json")
                assert os.path.exists(claude_config)
                with open(claude_config, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                assert cdata["projects"][tmp_workdir]["hasTrustDialogAccepted"] is True

                # Check Codex trust
                codex_config = os.path.join(tmp_home, ".codex", "config.toml")
                assert os.path.exists(codex_config)
                with open(codex_config, "r", encoding="utf-8") as f:
                    ccontent = f.read()
                assert f'[projects."{tmp_workdir}"]' in ccontent
                assert 'trust_level = "trusted"' in ccontent

                # Check AGY trust
                agy_settings = os.path.join(tmp_home, ".gemini", "antigravity-cli", "settings.json")
                assert os.path.exists(agy_settings)
                with open(agy_settings, "r", encoding="utf-8") as f:
                    adata = json.load(f)
                assert adata["enableTelemetry"] is False
                assert tmp_workdir in adata["trustedWorkspaces"]


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_reconciles_profile_env_vars_when_set(mock_run_tmux):
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

    r = MockRedis(["alice"], profile_map={"alice": "work"})
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    new_window_calls = [c for c in calls if "new-window" in c]
    cmd_str = " ".join(new_window_calls[0])
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work" in cmd_str
    assert "CODEX_HOME=/home/ubuntu/.codex-work" in cmd_str


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_omits_profile_env_vars_when_not_set(mock_run_tmux):
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
    new_window_calls = [c for c in calls if "new-window" in c]
    cmd_str = " ".join(new_window_calls[0])
    assert "CLAUDE_CONFIG_DIR" not in cmd_str
    assert "CODEX_HOME" not in cmd_str


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_reconciles_hyphenated_digit_agent_name(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "", ""),  # new-window sme-2
        (0, "__init__\nsme-2", ""),  # list-windows 2
        (0, "", ""),  # kill-window __init__
    ]

    r = MockRedis(["sme-2"], launch_map={"sme-2": "codex"}, profile_map={"sme-2": "work-2"})
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    new_window_calls = [c for c in calls if "new-window" in c]
    assert len(new_window_calls) == 1
    cmd_args = new_window_calls[0]
    assert "-n" in cmd_args and "sme-2" in cmd_args
    assert "-c" in cmd_args and "/workdir/sme-2" in cmd_args
    cmd_str = " ".join(cmd_args)
    assert "AGENT_NAME=sme-2" in cmd_str
    assert "AGENT_GUIDE=/workdir/sme-2/AGENTS.md" in cmd_str
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work-2" in cmd_str
    assert "CODEX_HOME=/home/ubuntu/.codex-work-2" in cmd_str
    assert "startAgent" in cmd_str and "codex" in cmd_str



