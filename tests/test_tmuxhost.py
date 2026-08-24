import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from flock.control import start_agent
from flock.tmuxhost.host import TmuxHost, generate_agents_md, write_agent_guide, ensure_claude_project_trusted


class MockRedis:
    __resp_double__ = True

    def __init__(
        self, roster_agents, port_type_map=None, launch_map=None, profile_map=None,
        provider_map=None, cause_map=None,
    ):
        self.roster_agents = set(roster_agents)
        self.port_type_map = port_type_map or {a: "tmux" for a in roster_agents}
        self.launch_map = launch_map or {}
        self.profile_map = profile_map or {}
        self.provider_map = provider_map or {}
        self.cause_map = cause_map or {}

    def get(self, key):
        for agent, cause in self.cause_map.items():
            if f":agent:{agent}:window.cause" in key:
                return cause.encode("utf-8") if isinstance(cause, str) else cause
        for agent, cli in self.launch_map.items():
            if f":agent:{agent}:launch" in key:
                return cli.encode("utf-8") if isinstance(cli, str) else cli
        for agent, prof in self.profile_map.items():
            if f":agent:{agent}:profile" in key:
                return prof.encode("utf-8") if isinstance(prof, str) else prof
        for agent, provider in self.provider_map.items():
            if f":agent:{agent}:provider" in key:
                return provider.encode("utf-8") if isinstance(provider, str) else provider
        return None

    def getdel(self, key):
        for agent in list(self.cause_map):
            if f":agent:{agent}:window.cause" in key:
                value = self.cause_map.pop(agent)
                return value.encode("utf-8") if isinstance(value, str) else value
        return None

    def set(self, key, value):
        if key.endswith(":window.cause"):
            agent = key.split(":agent:", 1)[1].split(":", 1)[0]
            self.cause_map[agent] = value
        elif key.endswith(":launch"):
            agent = key.split(":agent:", 1)[1].split(":", 1)[0]
            self.launch_map[agent] = value

    def hset(self, key, field, value):
        if key.endswith(":roster"):
            self.roster_agents.add(field)
            self.port_type_map[field] = value

    def eval(self, script, numkeys, *args):
        assert numkeys == 2
        cause_key, roster_key, correlation_id, agent, agent_port_type = args
        self.set(cause_key, correlation_id)
        self.hset(roster_key, agent, agent_port_type)
        return 1

    def hkeys(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}

    def hget(self, key, field):
        val = self.port_type_map.get(field)
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
        (0, "__init__", ""),  # list-windows — create_window's idempotence check
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
def test_window_created_consumes_hire_cause_and_recovery_borrows_none(mock_run_tmux, capsys):
    mock_run_tmux.side_effect = [
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
    ]
    r = MockRedis([], cause_map={"dave": "hire-correlation"})
    host = TmuxHost(
        pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq"
    )

    assert host.create_window(r, "dave") is True
    assert host.create_window(r, "dave") is True

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    created = [record for record in records if record["event"] == "window_created"]
    assert created[0]["correlation_id"] == "hire-correlation"
    assert "correlation_id" not in created[1]
    assert r.cause_map == {}


@patch("flock.tmux.ops.run_tmux")
def test_start_acceptance_and_later_window_creation_share_correlation(mock_run_tmux, capsys):
    mock_run_tmux.side_effect = [(0, "", ""), (0, "", "")]
    r = MockRedis([])
    host = TmuxHost(
        pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq"
    )

    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"correlation_id": "hire-correlation", "payload": {"agent": "dave"}},
        replace_window=lambda _agent: None,
    )
    # The two components share only Redis. No call or timing dependency joins
    # them; this later reconciliation can happen after an arbitrary poll gap.
    assert host.create_window(r, "dave") is True

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    accepted = next(record for record in records if record["event"] == "start_agent_accepted")
    created = next(record for record in records if record["event"] == "window_created")
    assert accepted["correlation_id"] == "hire-correlation"
    assert created["correlation_id"] == accepted["correlation_id"]
    assert r.cause_map == {}


@patch("flock.tmux.ops.run_tmux")
def test_existing_window_discards_unconsumed_cause_without_emitting_join(mock_run_tmux, capsys):
    mock_run_tmux.side_effect = [
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "alice", ""),
        (0, "alice", ""),
    ]
    r = MockRedis(["alice"], cause_map={"alice": "stale-correlation"})
    host = TmuxHost(
        pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq"
    )

    host.reconcile_once(r)

    assert r.cause_map == {}
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not any(record["event"] == "window_created" for record in records)


@patch("flock.tmux.ops.run_tmux")
def test_failed_window_creation_retains_cause_for_retry(mock_run_tmux, capsys):
    mock_run_tmux.side_effect = [(0, "", ""), (1, "", "tmux rejected window")]
    r = MockRedis([], cause_map={"dave": "hire-correlation"})
    host = TmuxHost(
        pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq"
    )

    assert host.create_window(r, "dave") is False

    assert r.cause_map == {"dave": "hire-correlation"}
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not any(record["event"] == "window_created" for record in records)


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
def test_tmuxhost_initial_session_resolves_agent_provider(mock_run_tmux, monkeypatch):
    mock_run_tmux.side_effect = [
        (1, "", "no server running"),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "alice", ""),
        (0, "alice", ""),
    ]
    monkeypatch.setenv("PROVIDER_GPU_URL", "http://model.test:8000")
    monkeypatch.setenv("PROVIDER_GPU_MODEL", "served-model")
    r = MockRedis(
        ["alice"],
        launch_map={"alice": "claude"},
        provider_map={"alice": "gpu"},
    )

    TmuxHost(
        pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq"
    ).reconcile_once(r)

    new_session = next(call.args for call in mock_run_tmux.call_args_list if "new-session" in call.args)
    command = " ".join(new_session)
    # ⚠ The provider intent, not the CLI variables — `startAgent` translates.
    assert "AGENT_PROVIDER_URL=http://model.test:8000" in command
    assert "AGENT_PROVIDER_MODEL=served-model" in command


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_filters_non_tmux_port_type(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "alice", ""),  # list-windows 1
        (0, "alice", ""),  # list-windows 2
    ]

    r = MockRedis(["alice", "api"], port_type_map={"alice": "tmux", "api": "api"})
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    assert not any("api" in c for c in calls)


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_replaces_last_stale_window_with_placeholder(mock_run_tmux):
    """An empty tmux roster must still retire the last real agent window."""
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "retired", ""),  # list-windows 1
        (0, "retired", ""),  # list-windows 2
        (0, "retired", ""),  # create_window idempotence check
        (0, "", ""),  # create placeholder
        (0, "", ""),  # kill retired
    ]

    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(MockRedis([]))

    calls = [" ".join(call.args) for call in mock_run_tmux.call_args_list]
    assert any("new-window" in call and "__init__" in call for call in calls)
    assert any("kill-window" in call and "hq:retired" in call for call in calls)


@patch("flock.tmux.ops.run_tmux")
def test_tmuxhost_reconciles_office_tools_and_agent_guide_env(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # default-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "__init__", ""),  # list-windows — create_window's idempotence check
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
    assert "[message from <name>] …" in content
    assert "office send" in content
    assert "You have a task board." in content
    assert "office list" in content
    assert "office take" in content
    assert "office done" in content
    assert "Take a ticket *before* you start work" in content
    assert "lead of this office" not in content

    lead_content = generate_agents_md("zeus", "hq", lead="zeus")
    assert "You are the lead of this office. The other agents follow your direction, and yours is the account that decides when something is done." in lead_content
    assert "Before you hand out work, check `office status`. An agent that is `blocked` will not receive it — hold the work and say so. Do not try to fix the agent." in lead_content

    peer_content = generate_agents_md("dave", "hq", lead="zeus")
    assert "zeus is the lead of this office. Their direction is the office's direction." in peer_content
    assert "office status" not in peer_content


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
        (0, "__init__", ""),  # list-windows — create_window's idempotence check
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
        (0, "__init__", ""),  # list-windows — create_window's idempotence check
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





@patch("flock.tmux.ops.run_tmux")
def test_create_window_does_not_overwrite_the_lead_sentence(mock_run_tmux, tmp_path):
    """The guide is written once, by the caller that actually makes the window.

    ⚠ Measured on a live tenant: tmuxhost wrote the guide with the lead, then
    tmux_ops.create_window wrote it again without one. Only the initial window —
    created by new-session, which does not pass through create_window — kept its
    lead sentence. Every other agent's guide named nobody.
    """
    mock_run_tmux.return_value = (0, "", "")
    cwd = str(tmp_path / "zeus")

    from flock.tmux import ops as tmux_ops

    tmux_ops.create_window("hq", "zeus", cwd=cwd, lead="zeus")

    guide = (tmp_path / "zeus" / "AGENTS.md").read_text()
    assert "You are the lead of this office." in guide


@patch("flock.tmux.ops.run_tmux")
def test_create_window_is_idempotent_by_name(mock_run_tmux, tmp_path):
    """A second window with the same name makes the agent unaddressable.

    ⚠ tmux creates the duplicate happily and then refuses to resolve it —
    `tmux -t hq:<name>` answers "can't find window" on an ambiguous target, so
    every delivery to that agent fails silently from then on.

    Measured on a live tenant: hiring an existing name left three windows called
    `rehire`, and capture-pane could no longer find any of them.
    """
    from flock.tmux import ops as tmux_ops

    mock_run_tmux.return_value = (0, "rehire", "")   # the window already exists
    ret, _, _ = tmux_ops.create_window("hq", "rehire", cwd=str(tmp_path / "rehire"))

    assert ret == 0
    assert not any("new-window" in c[0] for c in mock_run_tmux.call_args_list)


def test_trust_is_written_where_the_profile_reads_it(tmp_path, monkeypatch):
    """An agent with a profile reads trust from its own config dir.

    ⚠ Measured on a live tenant: trust went to ~/.claude.json while the agent ran
    with CLAUDE_CONFIG_DIR=~/.claude-work, so it met the "Yes, I trust this
    folder" picker and sat on it — unreachable, while presence read `idle`.
    """
    from flock.tmux import ops as tmux_ops

    monkeypatch.setenv("HOME", str(tmp_path))
    tmux_ops.ensure_claude_project_trusted("/workdir/bad", profile="work")

    profiled = tmp_path / ".claude-work" / ".claude.json"
    assert profiled.exists(), "trust must land in the profile's config dir"
    assert "/workdir/bad" in json.loads(profiled.read_text())["projects"]
    assert not (tmp_path / ".claude.json").exists(), "and not in the default one"


def test_profile_dirs_are_seeded_before_trust_is_written(tmp_path, monkeypatch):
    """⚠ ORDER IS LOAD-BEARING, and the wrong order fails silently.

    `seedProfile` never overwrites an existing file. The trust helpers CREATE
    `<profile-dir>/.claude.json`, so seeding after them leaves a file carrying
    trust and no `hasCompletedOnboarding` — which seedProfile then declines to
    touch, and the agent stops on the theme picker with no error anywhere.
    """
    from flock.tmux import ops

    calls = []
    monkeypatch.setattr(ops.subprocess, "run",
                        lambda cmd, **kw: calls.append(("seedProfile", cmd[1], cmd[2]))
                        or __import__("subprocess").CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(ops, "ensure_claude_project_trusted",
                        lambda cwd, profile=None: calls.append(("trust", "claude", profile)))
    monkeypatch.setattr(ops, "ensure_codex_project_trusted",
                        lambda cwd, profile=None: calls.append(("trust", "codex", profile)))
    monkeypatch.setattr(ops, "ensure_agy_project_trusted", lambda cwd: None)
    monkeypatch.setattr(ops, "generate_agents_md", lambda *a, **k: "guide")

    ops.write_agent_guide(str(tmp_path), "dave", "hq", profile="work")

    kinds = [c[0] for c in calls]
    assert "seedProfile" in kinds, "profile dir was never seeded"
    assert kinds.index("seedProfile") < kinds.index("trust"), (
        f"trust ran before seeding, which silently loses hasCompletedOnboarding: {calls}"
    )


def test_an_unprofiled_agent_is_not_seeded(tmp_path, monkeypatch):
    """It reads ~/.claude directly, which the image already ships populated."""
    from flock.tmux import ops

    ran = []
    monkeypatch.setattr(ops.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(ops, "ensure_claude_project_trusted", lambda *a, **k: None)
    monkeypatch.setattr(ops, "ensure_codex_project_trusted", lambda *a, **k: None)
    monkeypatch.setattr(ops, "ensure_agy_project_trusted", lambda *a, **k: None)
    monkeypatch.setattr(ops, "generate_agents_md", lambda *a, **k: "guide")

    ops.write_agent_guide(str(tmp_path), "dave", "hq", profile=None)

    assert ran == [], f"an unprofiled agent should need no seeding, got {ran}"
