import ast
import json
import tomllib
from pathlib import Path

import pytest

from flock.office import cli


class MockRedis:
    def __init__(self):
        self.roster = {"frontend": "tmux", "backend": "tmux", "api": "api", "host": "control"}
        self.lists = {}
        self.moves = []

    def hkeys(self, key):
        return {name.encode() for name in self.roster}

    def hget(self, key, field):
        value = self.roster.get(field)
        return value.encode() if value else None

    def hexists(self, key, field):
        return field in self.roster

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
    ):
        assert command in output


@pytest.mark.parametrize(
    "command",
    ["send", "broadcast", "peers", "hire", "letGo", "pause", "resume", "list", "take", "done", "cancel", "hold", "delete", "add"],
)
def test_every_subcommand_has_environment_free_help(monkeypatch, command):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: pytest.fail("help connected to Redis"))
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])
    assert exc.value.code == 0


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


def test_take_normalizes_old_ticket_prints_and_logs_task_id(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    raw = b'{"id":"a1","title":"opaque: --flag"}'
    office_env.lists[_task("frontend", "todo")] = [raw]
    cli.main(["take"])
    lines = capsys.readouterr().out.splitlines()
    record = json.loads(lines[0])
    assert record["module"] == "office"
    assert record["event"] == "task_taken"
    assert record["task_id"] == "a1"
    ticket = json.loads(lines[1])
    assert ticket["status"] == "doing"
    assert ticket["created_by"] == "unknown"
    event = json.loads((tmp_path / "tasks.jsonl").read_text())
    assert event["event"] == "take" and event["id"] == "a1"


def test_done_moves_open_task_and_logs_task_id(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TASK_RECORD", str(tmp_path / "tasks.jsonl"))
    raw = b'{"id":"b2","title":"finish"}'
    office_env.lists[_task("frontend", "doing")] = [raw]
    cli.main(["done"])
    lines = capsys.readouterr().out.splitlines()
    record = json.loads(lines[0])
    assert record["event"] == "task_done"
    assert record["task_id"] == "b2"
    assert json.loads(lines[1])["status"] == "done"
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
