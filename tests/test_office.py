import ast
import json
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flock.office import cli


class MockRedis:
    def __init__(self):
        self.roster = {"frontend": "tmux", "backend": "tmux", "api": "api", "host": "control"}
        self.lists = {}
        self.moves = []
        self.kv = {}
        # Two lanes wrote this mock independently, one calling it kv and one
        # values. Same dict under both names rather than rewriting either
        # lane's tests to match the other's spelling.
        self.values = self.kv

    def get(self, key):
        val = self.kv.get(key)
        return val.encode() if isinstance(val, str) else val

    def set(self, key, value):
        self.kv[key] = value

    def hkeys(self, key):
        return {name.encode() for name in self.roster}

    def hget(self, key, field):
        value = self.roster.get(field)
        return value.encode() if value else None

    def hgetall(self, key):
        return self.values.get(key, {})

    def hexists(self, key, field):
        return field in self.roster

    def get(self, key):
        return self.values.get(key)

    def lrange(self, key, start, end):
        return self.lists.get(key, [])

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lmove(self, source, destination, wherefrom, whereto):
        self.moves.append((source, destination, wherefrom, whereto))
        values = self.lists.get(source, [])
        if not values:
            return None
        value = values.pop(0)
        self.lists.setdefault(destination, []).append(value)
        return value

    def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        try:
            values.remove(value)
        except ValueError:
            return 0
        return 1


@pytest.fixture
def office_env(monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "frontend")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    r = MockRedis()
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: r)
    return r


def test_root_help_lists_whole_surface_without_environment_or_redis(monkeypatch, capsys):
    for name in ("AGENT_NAME", "POD", "TENANT", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: pytest.fail("help connected to Redis"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "send",
        "broadcast",
        "peers",
        "status",
        "hire",
        "letGo",
        "pause",
        "resume",
        "list",
        "take",
        "done",
        "cancel",
        "hold",
        "delete",
        "add",
        "cloneToAll",
    ):
        assert command in output


@pytest.mark.parametrize(
    "command",
    ["send", "broadcast", "peers", "status", "hire", "letGo", "pause", "resume", "list", "take", "done", "cancel", "hold", "delete", "add", "cloneToAll"],
)
def test_every_subcommand_has_environment_free_help(monkeypatch, command):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: pytest.fail("help connected to Redis"))
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])
    assert exc.value.code == 0


def test_clone_to_all_help_uses_no_hardcoded_agent_names(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: pytest.fail("help connected to Redis"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["cloneToAll", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "AGENT,..." in output
    assert "ALICE" not in output
    assert "BOB" not in output


def test_send_treats_inner_flags_as_literal_message(office_env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream-one")
    cli.main(["send", "-a", "backend", "run:", "office", "send", "-a", "frontend", "hi"])
    assert calls == [
        {
            "pod": "acme",
            "tenant": "hq",
            "producer": "frontend",
            "recipient": "backend",
            "payload": {"text": "run: office send -a frontend hi"},
            "kind": "Message",
            "module": "adapter",
        }
    ]
    assert capsys.readouterr().out.strip() == "stream-one"


def test_broadcast_resolves_tmux_peers_without_self_or_plumbing(office_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream")
    cli.main(["broadcast", "standup", "now"])
    assert [call["recipient"] for call in calls] == ["backend"]
    assert calls[0]["payload"] == {"text": "standup now"}


def test_peers_prints_only_other_tmux_agents(office_env, capsys):
    cli.main(["peers"])
    assert capsys.readouterr().out.strip() == "backend"


def test_peers_marks_lead_agent(office_env, capsys):
    # ⚠ zeus deliberately does NOT sort first — that is the whole point of the
    # lead being the first agent created rather than sorted(...)[0].
    office_env.roster = {"zeus": "tmux", "backend": "tmux", "frontend": "tmux"}
    office_env.set("pod:acme:tenant:hq:lead", "zeus")
    cli.main(["peers"])
    assert capsys.readouterr().out.strip() == "backend, zeus (lead)"


def test_peers_reads_configured_first_agent_instead_of_sorting(office_env, capsys):
    office_env.roster = {"zeus": "tmux", "alpha": "tmux", "frontend": "tmux"}
    office_env.values["pod:acme:tenant:hq:lead"] = b"zeus"
    cli.main(["peers"])
    assert capsys.readouterr().out.strip() == "alpha, zeus (lead)"


def test_status_lists_tmux_agents_with_presence_ticket_and_activity(office_env, monkeypatch, capsys):
    office_env.values["pod:acme:tenant:hq:agent:frontend:presence"] = {
        b"state": b"working",
        b"since": b"2026-08-09T13:59:56.000Z",
        b"last_activity": b"2026-08-09T13:59:56.000Z",
    }
    office_env.values["pod:acme:tenant:hq:agent:backend:presence"] = {
        b"state": b"idle",
        b"since": b"2026-08-09T13:55:30.000Z",
        b"last_activity": b"2026-08-09T13:54:00.000Z",
    }
    office_env.lists[_task("frontend", "doing")] = [
        b'{"id":"work","title":"review the auth change","started_ts":"2026-08-09T13:46:00.000Z"}'
    ]

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 9, 14, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(cli, "datetime", FixedDateTime)
    before_values = dict(office_env.values)
    before_lists = {key: list(values) for key, values in office_env.lists.items()}

    cli.main(["status"])

    assert capsys.readouterr().out.splitlines() == [
        "  backend     idle      —                                  last activity 6m ago",
        '  frontend    working   "review the auth change" 14m       last activity 4s ago',
    ]
    assert office_env.values == before_values
    assert office_env.lists == before_lists


def test_status_unknown_feed_and_optional_blocked_override(office_env, monkeypatch, capsys):
    office_env.values["pod:acme:tenant:hq:agent:backend:presence"] = {
        b"state": b"working",
        b"since": b"2026-08-09T13:59:00.000Z",
        b"last_activity": b"2026-08-09T13:59:00.000Z",
    }
    cli.main(["status", "frontend"])
    assert capsys.readouterr().out == "  frontend    unknown   —                                  no activity feed\n"

    office_env.values["pod:acme:tenant:hq:agent:backend:blocked"] = b"watchdog reason"
    cli.main(["status", "backend"])
    assert "backend     blocked" in capsys.readouterr().out


def test_status_rejects_non_tmux_or_unknown_agent(office_env, capsys):
    for agent in ("api", "missing"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["status", agent])
        assert exc.value.code == 1
        assert f"unknown tmux agent '{agent}'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "kind", "payload"),
    [
        (["hire", "redis"], "StartAgent", {"agent": "redis", "cli": "claude"}),
        (["hire", "redis", "--cli", "codex"], "StartAgent", {"agent": "redis", "cli": "codex"}),
        (["letGo", "redis"], "StopAgent", {"agent": "redis"}),
        (["pause", "redis"], "PauseAgent", {"agent": "redis"}),
        (["resume", "redis"], "ResumeAgent", {"agent": "redis"}),
    ],
)
def test_lifecycle_commands_send_to_host(office_env, monkeypatch, argv, kind, payload):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "control-stream")
    cli.main(argv)
    assert calls[0]["recipient"] == "host"
    assert calls[0]["kind"] == kind
    assert calls[0]["payload"] == payload


def _task(agent, state):
    return f"pod:acme:tenant:hq:agent:{agent}:tasks.{state}"


def test_list_prints_short_ids_and_titles_for_all_four_lists(office_env, capsys):
    office_env.lists = {
        _task("frontend", "todo"): [b'{"id":"a1","title":"next"}'],
        _task("frontend", "doing"): [b'{"id":"b2","title":"now"}'],
        _task("frontend", "hold"): [b'{"id":"d4","title":"later","description":"secret"}'],
        _task("frontend", "done"): [b'{"id":"c3","title":"finished"}'],
    }
    cli.main(["list"])
    output = capsys.readouterr().out
    assert "a1  next" in output
    assert "b2  now" in output
    assert "d4  later" in output
    assert "c3  finished" in output
    assert "secret" not in output


def test_take_refuses_when_doing_is_nonempty_without_moving(office_env, capsys):
    office_env.lists[_task("frontend", "doing")] = [b'{"id":"open"}']
    office_env.lists[_task("frontend", "todo")] = [b'{"id":"next"}']
    with pytest.raises(SystemExit) as exc:
        cli.main(["take"])
    assert exc.value.code == 1
    assert "already have one open" in capsys.readouterr().err
    assert office_env.lists[_task("frontend", "todo")] == [b'{"id":"next"}']


def test_take_distinguishes_empty_todo(office_env, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["take"])
    assert exc.value.code == 1
    assert "your todo is empty" in capsys.readouterr().err
    assert office_env.lists.get(_task("frontend", "doing"), []) == []


def test_board_keys_preserve_hyphenated_agent_name(office_env, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_NAME", "sme-2")
    office_env.lists[_task("sme-2", "todo")] = [b'{"id":"hyphen","title":"review names"}']
    cli.main(["take"])
    capsys.readouterr()
    assert office_env.lists[_task("sme-2", "todo")] == []
    assert json.loads(office_env.lists[_task("sme-2", "doing")][0])["id"] == "hyphen"


def test_take_normalizes_old_ticket_prints_and_logs_task_id(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    # ⚠ Telemetry goes to the window log, not the agent's screen.
    window_log = tmp_path / "window.jsonl"
    monkeypatch.setenv("FLOCK_LOG_FILE", str(window_log))
    raw = b'{"id":"a1","title":"opaque: --flag"}'
    office_env.lists[_task("frontend", "todo")] = [raw]
    cli.main(["take"])
    lines = capsys.readouterr().out.splitlines()
    record = json.loads(window_log.read_text().splitlines()[0])
    assert record["module"] == "office"
    assert record["event"] == "task_taken"
    assert record["task_id"] == "a1"
    ticket = json.loads(lines[0])
    assert ticket["status"] == "doing"
    assert ticket["created_by"] == "unknown"
    event = json.loads((tmp_path / "tasks.jsonl").read_text())
    assert event["event"] == "take" and event["id"] == "a1"


def test_done_moves_open_task_and_logs_task_id(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    # ⚠ `office` no longer prints bus telemetry to stdout — its stdout is an
    # agent's pane. The record goes to the window log the router tails.
    window_log = tmp_path / "window.jsonl"
    monkeypatch.setenv("FLOCK_LOG_FILE", str(window_log))
    raw = b'{"id":"b2","title":"finish"}'
    office_env.lists[_task("frontend", "doing")] = [raw]
    cli.main(["done"])
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["status"] == "done"
    record = json.loads(window_log.read_text().splitlines()[0])
    assert record["event"] == "task_done"
    assert record["task_id"] == "b2"
    assert json.loads((tmp_path / "tasks.jsonl").read_text())["event"] == "done"


def test_add_sends_envelope_and_never_writes_recipient_board(office_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "assignment-stream")
    cli.main(["add", "-a", "backend", "-t", "explain office send", "-d", "full brief", "-p", "high"])
    assert calls == [
        {
            "pod": "acme",
            "tenant": "hq",
            "producer": "frontend",
            "recipient": "backend",
            "payload": {"title": "explain office send", "description": "full brief", "priority": "high"},
            "kind": "AddTicket",
            "module": "adapter",
        }
    ]
    assert office_env.moves == []


def test_clone_to_all_fetches_once_then_resets_every_origin(office_env, monkeypatch, tmp_path, capsys):
    office_env.roster["worker"] = "tmux"
    workdir = tmp_path / "workdir"
    for agent in ("backend", "frontend", "worker"):
        (workdir / agent).mkdir(parents=True)
    upstream = tmp_path / "upstream" / "project.git"
    upstream.parent.mkdir()
    subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True)
    monkeypatch.setattr(cli, "_WORKDIR_ROOT", workdir)

    real_run = subprocess.run
    clone_sources = []

    def recording_run(command, **kwargs):
        if command[:2] == ["git", "clone"]:
            clone_sources.append(command[2])
        return real_run(command, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", recording_run)
    cli.main(["cloneToAll", str(upstream)])

    first = workdir / "backend" / "project"
    assert clone_sources == [str(upstream), str(first), str(first)]
    for agent in ("backend", "frontend", "worker"):
        target = workdir / agent / "project"
        remote = real_run(
            ["git", "-C", str(target), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert remote.stdout.strip() == str(upstream)
    assert "summary: cloned=3 skipped=0 failed=0" in capsys.readouterr().out

    clone_sources.clear()
    cli.main(["cloneToAll", str(upstream)])
    assert clone_sources == []
    assert "summary: cloned=0 skipped=3 failed=0" in capsys.readouterr().out


def test_clone_to_all_dry_run_filters_roster_and_writes_nothing(office_env, monkeypatch, tmp_path, capsys):
    workdir = tmp_path / "workdir"
    (workdir / "backend" / "project").mkdir(parents=True)
    monkeypatch.setattr(cli, "_WORKDIR_ROOT", workdir)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("dry-run invoked git"))

    cli.main(["cloneToAll", "git@example.test:team/project.git", "--dry-run"])

    output = capsys.readouterr().out
    assert "backend: exists, would skip" in output
    assert "frontend: would clone" in output
    assert "api" not in output
    assert "host" not in output
    assert not (workdir / "frontend").exists()


def test_clone_to_all_subset_accepts_only_tmux_agents(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_WORKDIR_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["cloneToAll", "project.git", "-a", "backend,api"])
    assert exc.value.code == 1
    assert "not a tmux agent: api" in capsys.readouterr().err


def test_clone_to_all_preserves_hyphenated_agent_path(office_env, monkeypatch, tmp_path, capsys):
    office_env.roster["sme-2"] = "tmux"
    monkeypatch.setattr(cli, "_WORKDIR_ROOT", tmp_path)
    cli.main(["cloneToAll", "git@example.test:team/project.git", "-a", "sme-2", "--dry-run"])
    assert capsys.readouterr().out.splitlines() == [
        "sme-2: would clone",
        "summary: cloned=0 skipped=0 failed=0",
    ]


def test_clone_to_all_removes_partial_directory_after_failure(office_env, monkeypatch, tmp_path, capsys):
    workdir = tmp_path / "workdir"
    (workdir / "backend").mkdir(parents=True)
    monkeypatch.setattr(cli, "_WORKDIR_ROOT", workdir)

    def failed_clone(command, **kwargs):
        Path(command[3]).mkdir()
        return subprocess.CompletedProcess(command, 1, "", "network unavailable")

    monkeypatch.setattr(cli.subprocess, "run", failed_clone)
    with pytest.raises(SystemExit) as exc:
        cli.main(["cloneToAll", "git@example.test:team/project.git", "-a", "backend"])
    assert exc.value.code == 1
    assert not (workdir / "backend" / "project").exists()
    output = capsys.readouterr()
    assert "summary: cloned=0 skipped=0 failed=1" in output.out
    assert "1 clone operation(s) failed" in output.err


def test_hold_then_take_by_prefix(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    office_env.lists[_task("frontend", "doing")] = [b'{"id":"abcdef12","title":"wait"}']
    cli.main(["hold"])
    capsys.readouterr()
    cli.main(["take", "abcd"])
    output = capsys.readouterr().out.splitlines()
    assert json.loads(output[-1])["status"] == "doing"
    assert office_env.lists[_task("frontend", "hold")] == []


def test_cancel_lands_in_done_with_cancelled_status(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    office_env.lists[_task("frontend", "doing")] = [b'{"id":"cancel-me","title":"nope"}']
    cli.main(["cancel"])
    ticket = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert ticket["status"] == "cancelled"
    assert json.loads(office_env.lists[_task("frontend", "done")][0])["status"] == "cancelled"


def test_delete_requires_id_without_connecting_to_redis(monkeypatch):
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: pytest.fail("connected to Redis"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["delete"])
    assert exc.value.code == 2


def test_task_record_failure_never_breaks_board_command(office_env, monkeypatch, capsys):
    office_env.lists[_task("frontend", "doing")] = [b'{"id":"safe","title":"finish"}']
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read only")))
    cli.main(["done"])
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "done"


def test_office_imports_no_other_flock_module_than_bus():
    tree = ast.parse(Path("src/flock/office/cli.py").read_text())
    flock_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("flock"):
            flock_imports.append(node.module)
        elif isinstance(node, ast.Import):
            flock_imports.extend(alias.name for alias in node.names if alias.name.startswith("flock"))
    assert flock_imports == ["flock.bus"]


def test_only_office_agent_command_is_packaged():
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["office"] == "flock.office:main"
    assert "flock.adapter" in scripts
    for old in ("sendMessage", "sendBroadcast", "peers", "hire", "letGo", "pause", "resume"):
        assert old not in scripts


def test_status_survives_a_blocked_key_of_the_wrong_type(office_env, capsys):
    """A read-only view must not crash on data it did not write.

    ⚠ Measured: `blocked` planted as a HASH — the shape the spec describes —
    against a reader using GET raised WRONGTYPE and took the whole command down.
    The watchdog owns that key and writes it in a later build; status must
    tolerate whatever it finds and treat nonsense as "not blocked".
    """
    office_env.roster = {"architect": "tmux", "worker": "tmux"}

    office_env.values["pod:acme:tenant:hq:agent:worker:blocked"] = {"since": "now"}
    cli.main(["status", "worker"])
    assert "worker" in capsys.readouterr().out
