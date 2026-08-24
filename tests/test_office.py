from conftest import FakeRespRedis as MockRedis
import ast
import io
import json
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flock.bus import prefix
from flock.office import cli



@pytest.fixture
def office_env(monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "frontend")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    r = MockRedis(roster={"frontend": "tmux", "backend": "tmux", "api": "api", "host": "control"})
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
        "let-go",
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
        "clone-to-all",
    ):
        assert command in output


@pytest.mark.parametrize(
    "command",
    ["send", "broadcast", "peers", "status", "hire", "letGo", "let-go", "pause", "resume", "list", "take", "done", "cancel", "hold", "delete", "add", "cloneToAll", "clone-to-all"],
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
    cli.main(["send", "-a", "backend", "run: office send -a frontend hi"])
    assert calls == [
        {
            "pod": "acme",
            "tenant": "hq",
            "source": "frontend",
            "destination": "backend",
            "payload": {"text": "run: office send -a frontend hi"},
            "kind": "Message",
            "module": "port",
        }
    ]
    assert capsys.readouterr().out.strip() == "sent to backend: 31 bytes (stream-one)"


def test_send_preserves_a_quoted_body_containing_office_flags(office_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream-one")

    cli.main([
        "send",
        "-a",
        "backend",
        "a body that contains --stdin and --file and -a inside it",
    ])

    assert calls[0]["payload"] == {
        "text": "a body that contains --stdin and --file and -a inside it"
    }


def test_send_reads_stdin_and_reports_utf8_bytes(office_env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream-stdin")
    monkeypatch.setattr("sys.stdin", io.StringIO("line one\nλ\n"))

    cli.main(["send", "--agent=backend", "--stdin"])

    assert calls[0]["payload"] == {"text": "line one\nλ\n"}
    assert capsys.readouterr().out.strip() == "sent to backend: 12 bytes (stream-stdin)"


def test_send_reads_file_without_shell_parsing(office_env, monkeypatch, tmp_path, capsys):
    report = tmp_path / "hardware report.txt"
    report.write_text("show --stdin\n-a stays data\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream-file")

    cli.main(["send", "-a", "backend", "--file", str(report)])

    assert calls[0]["payload"] == {"text": "show --stdin\n-a stays data\n"}
    assert capsys.readouterr().out.strip() == "sent to backend: 27 bytes (stream-file)"


def test_send_refuses_mixed_or_empty_input(office_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "send", lambda *args, **kwargs: pytest.fail("refused input was sent"))

    monkeypatch.setattr("sys.stdin", io.StringIO("from pipe"))
    with pytest.raises(SystemExit) as mixed:
        cli.main(["send", "-a", "backend", "--stdin", "positional"])
    assert mixed.value.code == 1
    assert "exactly one" in capsys.readouterr().err

    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as empty:
        cli.main(["send", "-a", "backend", "--stdin"])
    assert empty.value.code == 1
    assert "received no message text" in capsys.readouterr().err


def test_send_double_dash_allows_literal_option_body(office_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream")

    cli.main(["send", "-a", "backend", "--", "--stdin"])

    assert calls[0]["payload"] == {"text": "--stdin"}


@pytest.mark.parametrize("command", ["letGo", "let-go"])
def test_let_go_aliases_share_the_control_contract(office_env, monkeypatch, command):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream")

    cli.main([command, "backend"])

    assert calls[0]["kind"] == "StopAgent"
    assert calls[0]["payload"] == {"agent": "backend"}


@pytest.mark.parametrize("command", ["cloneToAll", "clone-to-all"])
def test_clone_to_all_aliases_share_the_parser(office_env, command, capsys):
    cli.main([command, "git@example.test:team/project.git", "--dry-run"])

    assert "would clone" in capsys.readouterr().out


def test_broadcast_resolves_tmux_peers_without_self_or_plumbing(office_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: calls.append(kwargs) or "stream")
    cli.main(["broadcast", "standup", "now"])
    assert [call["destination"] for call in calls] == ["backend"]
    assert calls[0]["payload"] == {"text": "standup now"}


def test_peers_prints_only_other_tmux_agents(office_env, capsys):
    cli.main(["peers"])
    assert capsys.readouterr().out.strip() == "backend"


def test_peers_verbose_distinguishes_framework_profile_and_current_task(
    office_env, capsys
):
    office_env.roster = {
        "frontend": "tmux",
        "claude-peer": "tmux",
        "codex-peer": "tmux",
        "agy-peer": "tmux",
    }
    office_env.values.update(
        {
            "pod:acme:tenant:hq:agent:claude-peer:launch": "claude",
            "pod:acme:tenant:hq:agent:claude-peer:profile": "work",
            "pod:acme:tenant:hq:agent:codex-peer:launch": "codex",
            "pod:acme:tenant:hq:agent:agy-peer:launch": "agy",
        }
    )
    office_env.lists["pod:acme:tenant:hq:agent:codex-peer:tasks.doing"] = [
        json.dumps({"id": "task-1", "title": "Review the fabric"}).encode()
    ]

    cli.main(["peers", "--verbose"])

    assert capsys.readouterr().out.splitlines() == [
        "agy-peer: framework=agy",
        "claude-peer: framework=claude, profile=work",
        'codex-peer: framework=codex, task="Review the fabric"',
    ]


def test_peers_plain_output_contract_is_unchanged_with_enriched_state(
    office_env, capsys
):
    office_env.values["pod:acme:tenant:hq:agent:backend:launch"] = "agy"
    office_env.values["pod:acme:tenant:hq:agent:backend:profile"] = "work"
    office_env.lists["pod:acme:tenant:hq:agent:backend:tasks.doing"] = [
        json.dumps({"id": "task-1", "title": "Busy"}).encode()
    ]

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


def test_status_names_agy_agent_not_collected(office_env, capsys):
    """Build 105 §2: office status names agy agents as not collected."""
    office_env.values["pod:acme:tenant:hq:agent:frontend:launch"] = b"agy"
    cli.main(["status", "frontend"])
    out = capsys.readouterr().out
    assert "frontend" in out
    assert "not collected (agy)" in out


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
    assert calls[0]["destination"] == "host"
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
    # agent's pane. The record goes to the window log the switch tails.
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
            "source": "frontend",
            "destination": "backend",
            "payload": {"title": "explain office send", "description": "full brief", "priority": "high"},
            "kind": "AddTicket",
            "module": "port",
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
    assert "flock.port" in scripts
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





def test_hire_carries_a_profile_into_the_start_agent_payload(office_env, monkeypatch, capsys):
    """⚠ StartAgent always accepted a profile; only this command could not say it.

    Without it, every agent hired into a multi-account tenant landed on the
    default config dir — and since the OAuth work, on the default account's
    credential — with nothing reporting that it had happened.
    """
    sent = {}
    monkeypatch.setattr(cli, "send", lambda r, **kw: sent.update(kw) or "stream-1")
    monkeypatch.setattr(cli, "available_profiles", lambda r, **kwargs: ("default", "work"))

    cli.main(["hire", "dave", "--cli", "codex", "--profile", "work"])

    assert sent["kind"] == "StartAgent"
    assert sent["payload"]["agent"] == "dave"
    assert sent["payload"]["cli"] == "codex"
    assert sent["payload"]["profile"] == "work"


def test_hire_without_a_profile_sends_none_rather_than_an_empty_one(office_env, monkeypatch, capsys):
    """Absent means the tenant's default, which openers.py already handles.

    An empty string would fail its segment validation and dead-letter the hire.
    """
    sent = {}
    monkeypatch.setattr(cli, "send", lambda r, **kw: sent.update(kw) or "stream-1")

    cli.main(["hire", "dave"])

    assert "profile" not in sent["payload"]


def test_hire_refuses_an_unknown_cli_at_the_prompt(office_env, capsys):
    """⚠ It used to be accepted, stored, and fail inside the window instead.

    `startAgent <typo>` produces a window that opens and never speaks — the same
    signature as a login prompt or a first-run dialog, and nothing logs an error.
    """
    with pytest.raises(SystemExit) as exc:
        cli.main(["hire", "dave", "--cli", "banana"])
    assert exc.value.code == 2
    assert "banana" in capsys.readouterr().err


def test_hire_refuses_unknown_profile_at_client_with_available_accounts(
    office_env, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "available_profiles", lambda r, **kwargs: ("default", "work"))
    sent = []
    monkeypatch.setattr(cli, "send", lambda *args, **kwargs: sent.append(kwargs))
    with pytest.raises(SystemExit) as exc:
        cli.main(["hire", "dave", "--profile", "typo"])
    assert exc.value.code == 2
    assert sent == []
    assert "unknown account 'typo'; available accounts: default, work" in capsys.readouterr().err


def test_hire_reads_canonical_accounts_from_redis(office_env, monkeypatch, capsys):
    office_env.sets[prefix("acme", "hq", resource="accounts")] = {b"default", b"work"}
    sent = []
    monkeypatch.setattr(cli, "send", lambda *args, **kwargs: sent.append(kwargs))
    with pytest.raises(SystemExit) as exc:
        cli.main(["hire", "dave", "--profile", "stale-dir"])
    assert exc.value.code == 2
    assert sent == []
    assert "available accounts: default, work" in capsys.readouterr().err


def test_hire_legacy_tenant_without_accounts_key_remains_permissive(
    office_env, monkeypatch, capsys
):
    sent = {}
    monkeypatch.setattr(cli, "send", lambda r, **kwargs: sent.update(kwargs) or "stream-1")
    cli.main(["hire", "dave", "--profile", "legacy"])
    assert sent["payload"]["profile"] == "legacy"
