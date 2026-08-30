from conftest import FakeRespRedis
import json
import pathlib
import os
import signal
import subprocess
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from flock.port.openers import add_ticket_opener, attachment_opener, message_opener, messages_opener, command_opener, get_tmux_windows
from flock.port.send import main as cli_main
from flock.port.deliver import run_port
from flock.bus import DeadLetter, build as build_envelope, encode, parse, prefix, receive


def test_port_entrypoint_restores_waitable_children(monkeypatch):
    """A switch child must not inherit the switch's false-zero wait behavior."""
    from flock.port import __main__ as port_entrypoint

    previous = signal.getsignal(signal.SIGCHLD)
    observed = {}

    def probe_run_port(**_kwargs):
        observed["disposition"] = signal.getsignal(signal.SIGCHLD)
        observed["returncode"] = subprocess.run(["/bin/sh", "-c", "exit 1"]).returncode

    monkeypatch.setattr(port_entrypoint, "run_port", probe_run_port)
    monkeypatch.setattr(sys, "argv", ["flock.port", "alice"])
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        port_entrypoint.main()
    finally:
        signal.signal(signal.SIGCHLD, previous)

    assert observed == {"disposition": signal.SIG_DFL, "returncode": 1}



@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_window_exists(mock_run_tmux, mock_list_windows, capsys):
    mock_list_windows.return_value = {"alice", "bob"}
    buffer_present = False

    def stateful_tmux(*args, **kwargs):
        nonlocal buffer_present
        if args[0] == "load-buffer":
            buffer_present = True
            return 0, "", ""
        if args[0] == "paste-buffer":
            assert buffer_present
            assert "-d" in args
            buffer_present = False
            return 0, "", ""
        if args[0] == "delete-buffer":
            if not buffer_present:
                return 1, "", "unknown buffer"
            buffer_present = False
        return 0, "", ""

    mock_run_tmux.side_effect = stateful_tmux

    r = FakeRespRedis()
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    ingress_key = prefix("acme", "hq", agent="bob", resource="ingress")
    r.rpush(ingress_key, encode(env))

    receive(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        openers={
            "Message": lambda envelope: message_opener(
                r,
                pod="acme",
                tenant="hq",
                agent="bob",
                envelope=envelope,
                session_name="hq",
            )
        },
        timeout=0,
        blocking=False,
    )

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("load-buffer" in cmd for cmd in cmd_args)
    assert any("paste-buffer" in cmd for cmd in cmd_args)
    assert any("send-keys" in cmd for cmd in cmd_args)
    assert not any("delete-buffer" in cmd for cmd in cmd_args)
    assert not buffer_present
    assert [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()] == [
        "received",
        "opened",
    ]

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "[message from alice] hello\n"


@patch("flock.port.openers.list_windows")
def test_message_opener_window_missing(mock_list_windows):
    mock_list_windows.return_value = {"alice"}

    r = FakeRespRedis()
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})

    with pytest.raises(DeadLetter, match="window_missing"):
        message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    assert "pod:acme:tenant:hq:agent:bob:dead" not in r.lists


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_broadcast(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob", "carol"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(kind="Message", source="alice", destination="all", payload={"text": "broadcast message"})

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_command_opener_bare_paste(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(kind="Command", source="alice", destination="bob", payload={"text": "touch /tmp/it-ran"})

    command_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "touch /tmp/it-ran\n"
    assert "[message from" not in input_data


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_writes_v1_ticket(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "review the auth change", "description": "check auth middleware", "priority": "high"},
    )

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    todo_key = "pod:acme:tenant:hq:agent:backend:tasks.todo"
    assert todo_key in r.lists
    assert len(r.lists[todo_key]) == 1
    ticket_data = json.loads(r.lists[todo_key][0])
    assert ticket_data["v"] == 1
    assert ticket_data["title"] == "review the auth change"
    assert ticket_data["description"] == "check auth middleware"
    assert ticket_data["created_by"] == "architect"
    assert ticket_data["priority"] == "high"
    assert ticket_data["status"] == "todo"

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 0


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_stores_related_and_drops_non_strings(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "follow-up", "related": ["abc12345", "def67890", 42, None]},
    )

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    todo_key = "pod:acme:tenant:hq:agent:backend:tasks.todo"
    ticket_data = json.loads(r.lists[todo_key][0])
    assert ticket_data["related"] == ["abc12345", "def67890"]


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_omits_related_when_absent(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "no relations"},
    )

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    todo_key = "pod:acme:tenant:hq:agent:backend:tasks.todo"
    ticket_data = json.loads(r.lists[todo_key][0])
    assert "related" not in ticket_data


@patch("flock.port.openers.list_windows")
def test_add_ticket_opener_writes_when_window_is_missing(mock_list_windows, capsys):
    mock_list_windows.return_value = {"architect"}
    r = FakeRespRedis()
    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "wait for recovery"},
    )

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    assert mock_list_windows.call_count == 0
    todo_key = "pod:acme:tenant:hq:agent:backend:tasks.todo"
    assert json.loads(r.lists[todo_key][0])["title"] == "wait for recovery"
    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "board_write_confirmed"
    assert record["destination"] == "backend"
    assert record["count"] == 1


def test_add_ticket_opener_dead_letters_unknown_board_write(capsys):

    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "cannot land"},
    )

    with pytest.raises(DeadLetter, match="board_write_unknown"):
        add_ticket_opener(
            FakeRespRedis(fails_on={"rpush": RuntimeError("board unavailable")}),
            pod="acme",
            tenant="hq",
            agent="backend",
            envelope=env,
            session_name="hq",
        )

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "board_write_unknown"
    assert record["reason"] == "board write outcome UNKNOWN after board unavailable"


def test_add_ticket_opener_rejects_acknowledged_invalid_board_depth(capsys):

    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "invalid acknowledgement"},
    )

    with pytest.raises(DeadLetter, match="board_write_failed"):
        add_ticket_opener(
            FakeRespRedis(fails_on={"rpush": lambda key, val: 0}),
            pod="acme",
            tenant="hq",
            agent="backend",
            envelope=env,
            session_name="hq",
        )

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "board_write_failed"
    assert record["reason"] == "RPUSH did not return a positive list length"


def test_failed_board_write_is_parked_once_by_receive(capsys):

    r = FakeRespRedis(fails_on={"rpush": lambda key, val: (_ for _ in ()).throw(RuntimeError("board unavailable")) if key.endswith(":tasks.todo") else None})
    env = build_envelope(
        kind="AddTicket",
        source="architect",
        destination="backend",
        payload={"title": "cannot land"},
    )
    ingress_key = prefix("acme", "hq", agent="backend", resource="ingress")
    r.rpush(ingress_key, encode(env))

    receive(
        r,
        pod="acme",
        tenant="hq",
        agent="backend",
        openers={
            "AddTicket": lambda envelope: add_ticket_opener(
                r,
                pod="acme",
                tenant="hq",
                agent="backend",
                envelope=envelope,
                session_name="hq",
            )
        },
        timeout=0,
        module="port",
    )

    events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
    assert events == ["received", "board_write_unknown", "dead_lettered"]
    dead_key = prefix("acme", "hq", agent="backend", resource="dead")
    assert len(r.lists[dead_key]) == 1


def test_assign_task_is_no_longer_a_kind():
    """The compatibility alias is gone. Build 11 said "remove it in the build
    after"; it survived four. An unknown kind now dead-letters with a reason,
    which is the correct answer and a visible one."""
    from flock.port import deliver

    assert not hasattr(deliver, "assign_task_opener")
    assert "AssignTask" not in pathlib.Path(deliver.__file__).read_text()


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_appends_to_task_record(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "tasks.jsonl")
        with patch.dict(os.environ, {"TASK_RECORD": log_file}):
            r = FakeRespRedis()
            env = build_envelope(
                kind="AddTicket",
                source="architect",
                destination="backend",
                payload={"title": "fix log issue", "description": "detail"},
            )
            add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

            assert os.path.exists(log_file)
            with open(log_file, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]
            assert len(lines) == 1
            rec = lines[0]
            assert rec["event"] == "add"
            assert rec["title"] == "fix log issue"
            assert rec["agent"] == "backend"
            assert rec["actor"] == "architect"
            assert "id" in rec
            assert "timestamp" in rec


@patch("flock.port.deliver.redis.Redis.from_url")
@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_run_port_kicked_one_shot(mock_run_tmux, mock_list_windows, mock_redis_cls, monkeypatch):
    monkeypatch.delenv("TMUX_SESSION", raising=False)
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "kicked message"})
    mock_r.rpush(ingress_key, encode(env))

    run_port(agent="bob", pod="acme", tenant="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0

    delivering_key = "pod:acme:tenant:hq:delivering"
    assert not mock_r.hexists(delivering_key, "bob")

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


@patch("flock.port.deliver.redis.Redis.from_url")
def test_run_port_paused_leaves_envelope_in_ingress(mock_redis_cls):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r

    paused_key = "pod:acme:tenant:hq:agent:bob:paused"
    mock_r.set(paused_key, "1")

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "paused message"})
    mock_r.rpush(ingress_key, encode(env))

    run_port(agent="bob", pod="acme", tenant="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 1
    delivering_key = "pod:acme:tenant:hq:delivering"
    assert not mock_r.hexists(delivering_key, "bob")


@patch("flock.port.send.redis.Redis.from_url")
def test_cli_send(mock_redis_cls, monkeypatch):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r

    monkeypatch.setenv("AGENT_NAME", "alice")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")

    test_args = ["send", "bob", "hello", "world"]
    monkeypatch.setattr("sys.argv", test_args)

    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 0

    egress_key = "pod:acme:tenant:hq:agent:alice:egress"
    assert egress_key in mock_r.lists
    assert len(mock_r.lists[egress_key]) == 1
    pushed = parse(mock_r.lists[egress_key][0])
    assert pushed["l2"] == {"source": "alice", "destination": "bob"}
    assert pushed["l3"] == {
        "source": "acme:hq:alice",
        "destination": "acme:hq:bob",
    }
    assert pushed["payload"] == {"text": "hello world"}


@patch("flock.port.deliver.redis.Redis.from_url")
def test_run_port_port_type_api_pops_and_writes_mailbox(mock_redis_cls):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "api", "api")

    ingress_key = "pod:acme:tenant:hq:agent:api:ingress"
    env = build_envelope(kind="Message", source="alice", destination="api", payload={"text": "reply"})
    mock_r.rpush(ingress_key, encode(env))

    run_port(agent="api", pod="acme", tenant="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0
    inbox_key = "pod:acme:tenant:hq:agent:api:inbox"
    assert inbox_key in mock_r.streams
    assert len(mock_r.streams[inbox_key]) == 1
    stream_id, fields = mock_r.streams[inbox_key][0]
    assert "envelope" in fields
    stored_env = json.loads(fields["envelope"])
    assert stored_env["l2"]["source"] == "alice"
    assert stored_env["l2"]["destination"] == "api"
    assert stored_env["payload"] == {"text": "reply"}


@patch("flock.port.deliver.redis.Redis.from_url")
def test_run_port_unroutable_broadcast_records_actual_recipient(mock_redis_cls, capsys):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "host", "custom_port_type")

    ingress_key = "pod:acme:tenant:hq:agent:host:ingress"
    env = build_envelope(kind="Message", source="alice", destination="all", payload={"text": "test"})
    mock_r.rpush(ingress_key, encode(env))

    run_port(agent="host", pod="acme", tenant="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0
    dead_key = "pod:acme:tenant:hq:agent:host:dead"
    assert len(mock_r.lists.get(dead_key, [])) == 1
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["event"] for record in records] == ["received", "dead_lettered"]
    assert [record["destination"] for record in records] == ["host", "host"]
    assert records[-1]["stream_id"] == env["stream_id"]


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_writes_pending_verify_marker_for_claude(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.set("pod:acme:tenant:hq:agent:bob:launch", "claude")
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert verify_key in r.streams
    assert len(r.streams[verify_key]) == 1
    _, fields = r.streams[verify_key][0]
    assert fields["stream_id"] == "12345-0"
    assert "ts" in fields


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_marks_pending_verify_marker_for_agy(mock_run_tmux, mock_list_windows):
    """agy joined VERIFIABLE_CLIS once history.jsonl was wired into
    ActivityTailer (watchdog/activity.py's _agy_events) — same as claude."""
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    launch_key = "pod:acme:tenant:hq:agent:bob:launch"
    r.set(launch_key, "agy")
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert verify_key in r.streams
    assert len(r.streams[verify_key]) == 1
    _, fields = r.streams[verify_key][0]
    assert fields["stream_id"] == "12345-0"


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_skips_pending_verify_marker(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    env = build_envelope(kind="AddTicket", source="architect", destination="backend", payload={"title": "task"})
    env["stream_id"] = "12345-0"

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:backend:pending.verify"
    assert verify_key not in r.streams


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_mark_delivery_pending_swallows_redis_exceptions(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")


    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    r = FakeRespRedis(fails_on={"xadd": RuntimeError("Redis stream error")})
    # Must complete cleanly without raising exception
    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")



@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_no_marker_for_a_window_running_no_cli(mock_run_tmux, mock_list_windows):
    """A bare shell writes no session file, so a delivery to it can never be
    confirmed. Marking it reported unverified forever.

    Measured: with a denylist that skipped only agy, three of the first four
    unverified records in a live run were bash windows.
    """
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()  # no launch key at all
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hi"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    assert "pod:acme:tenant:hq:agent:bob:pending.verify" not in r.streams


@patch("flock.port.deliver.redis.Redis.from_url")
@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_port_batches_consecutive_messages_into_single_paste(mock_run_tmux, mock_list_windows, mock_redis_cls, capsys):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"alice", "bob", "carol"}
    mock_run_tmux.return_value = (0, "", "")

    mock_r.set("pod:acme:tenant:hq:agent:bob:launch", "claude")
    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env1 = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "first message"})
    env2 = build_envelope(kind="Message", source="carol", destination="bob", payload={"text": "second message"})
    env3 = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "third message"})
    mock_r.rpush(ingress_key, encode(env1), encode(env2), encode(env3))

    run_port(agent="bob", pod="acme", tenant="hq")

    # Ingress drained
    assert len(mock_r.lists.get(ingress_key, [])) == 0

    # Exactly 1 paste cycle
    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == (
        "[message from alice] first message\n"
        "[message from carol] second message\n"
        "[message from alice] third message\n"
    )

    # 3 pending.verify markers
    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert len(mock_r.streams.get(verify_key, [])) == 3
    verify_ids = [fields["stream_id"] for _, fields in mock_r.streams[verify_key]]
    assert verify_ids == [env1["stream_id"], env2["stream_id"], env3["stream_id"]]

    # Custody records: 3 received, 3 opened
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in records] == ["received", "received", "received", "opened", "opened", "opened"]
    assert [r["stream_id"] for r in records] == [
        env1["stream_id"], env2["stream_id"], env3["stream_id"],
        env1["stream_id"], env2["stream_id"], env3["stream_id"],
    ]


@patch("flock.port.deliver.redis.Redis.from_url")
@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_port_preserves_order_with_interleaved_commands_and_tickets(mock_run_tmux, mock_list_windows, mock_redis_cls, capsys):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"architect", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    msg1 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "msg1"})
    msg2 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "msg2"})
    cmd1 = build_envelope(kind="Command", source="architect", destination="bob", payload={"text": "echo running"})
    msg3 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "msg3"})
    ticket1 = build_envelope(kind="AddTicket", source="architect", destination="bob", payload={"title": "ticket1"})
    msg4 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "msg4"})
    msg5 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "msg5"})

    mock_r.rpush(ingress_key, encode(msg1), encode(msg2), encode(cmd1), encode(msg3), encode(ticket1), encode(msg4), encode(msg5))

    run_port(agent="bob", pod="acme", tenant="hq")

    # Check load-buffer inputs in order
    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 4
    # Call 1: batched msg1 + msg2
    assert load_buffer_calls[0][1]["input_data"] == "[message from architect] msg1\n[message from architect] msg2\n"
    # Call 2: cmd1
    assert load_buffer_calls[1][1]["input_data"] == "echo running\n"
    # Call 3: msg3
    assert load_buffer_calls[2][1]["input_data"] == "[message from architect] msg3\n"
    # Call 4: batched msg4 + msg5
    assert load_buffer_calls[3][1]["input_data"] == "[message from architect] msg4\n[message from architect] msg5\n"

    # Check ticket written to tasks.todo
    todo_key = "pod:acme:tenant:hq:agent:bob:tasks.todo"
    assert len(mock_r.lists.get(todo_key, [])) == 1
    assert json.loads(mock_r.lists[todo_key][0])["title"] == "ticket1"


@patch("flock.port.deliver.redis.Redis.from_url")
@patch("flock.port.openers.list_windows")
def test_port_batch_missing_window_dead_letters_all_envelopes(mock_list_windows, mock_redis_cls, capsys):
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"architect"}  # bob is missing

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    msg1 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "m1"})
    msg2 = build_envelope(kind="Message", source="architect", destination="bob", payload={"text": "m2"})
    mock_r.rpush(ingress_key, encode(msg1), encode(msg2))

    run_port(agent="bob", pod="acme", tenant="hq")

    dead_key = "pod:acme:tenant:hq:agent:bob:dead"
    assert len(mock_r.lists.get(dead_key, [])) == 2

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in records] == ["received", "received", "dead_lettered", "dead_lettered"]
    assert all(r["reason"] == "window_missing" for r in records if r["event"] == "dead_lettered")


@patch("flock.port.deliver.redis.Redis.from_url")
@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_port_burst_repro_twenty_envelopes_batched_cleanly(mock_run_tmux, mock_list_windows, mock_redis_cls, capsys):
    """Reconstructs the BURSTD001/BURSTZ003 burst scenario:
    20 envelopes sent simultaneously into an agent.
    All 20 are drained in one atomic snapshot, combined into one physical paste,
    recording 20 received, 20 opened, and 20 verify markers with zero duplicates."""
    mock_r = FakeRespRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"architect", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    mock_r.set("pod:acme:tenant:hq:agent:bob:launch", "claude")
    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    envelopes = [
        build_envelope(
            kind="Message",
            source="architect",
            destination="bob",
            payload={"text": f"BURSTD{i:03d} body"},
        )
        for i in range(1, 21)
    ]
    for i, env in enumerate(envelopes, 1):
        env["stream_id"] = f"{i:032x}"
    mock_r.rpush(ingress_key, *[encode(e) for e in envelopes])

    run_port(agent="bob", pod="acme", tenant="hq")

    # Ingress drained
    assert len(mock_r.lists.get(ingress_key, [])) == 0

    # Exactly 1 paste call
    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    for i in range(1, 21):
        assert f"[message from architect] BURSTD{i:03d} body\n" in input_data

    # 20 verify markers
    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert len(mock_r.streams.get(verify_key, [])) == 20
    marker_stream_ids = [fields["stream_id"] for _, fields in mock_r.streams[verify_key]]
    assert marker_stream_ids == [e["stream_id"] for e in envelopes]

    # 20 received + 20 opened = 40 records
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    received_events = [r for r in records if r["event"] == "received"]
    opened_events = [r for r in records if r["event"] == "opened"]
    assert len(received_events) == 20
    assert len(opened_events) == 20


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_attachment_opener_success(mock_run_tmux, mock_list_windows, tmp_path):
    mock_list_windows.return_value = {"architect", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.set("pod:acme:tenant:hq:agent:bob:launch", "claude")

    import base64
    raw_content = b"fake image bytes \x00\x01\x02"
    b64_content = base64.b64encode(raw_content).decode("ascii")

    envelope = {
        "kind": "Attachment",
        "stream_id": "0123456789abcdef0123456789abcdef",
        "correlation_id": "corr-123",
        "l2": {"source": "architect", "destination": "bob"},
        "payload": {
            "filename": "diagram.png",
            "mime_type": "image/png",
            "content_base64": b64_content,
            "caption": "system architecture diagram",
        },
    }

    attachment_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelope=envelope,
        session_name="hq",
        workdir_root=str(tmp_path),
    )

    # Verify file content written to disk
    expected_file = tmp_path / "bob" / "attachments" / "0123456789abcdef0123456789abcdef" / "diagram.png"
    assert expected_file.exists()
    assert expected_file.read_bytes() == raw_content

    # Verify pending markers written
    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    markers_key = "pod:acme:tenant:hq:agent:bob:delivery.markers"
    assert len(r.streams.get(verify_key, [])) == 1
    assert r.streams[verify_key][0][1]["stream_id"] == "0123456789abcdef0123456789abcdef"
    assert r.streams[verify_key][0][1]["correlation_id"] == "corr-123"
    assert len(r.streams.get(markers_key, [])) == 1

    # Verify paste notice formatted properly
    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert f"[attachment from architect] saved to {expected_file} (image/png, {len(raw_content)} bytes)\n" in input_data
    assert "[attachment caption] system architecture diagram\n" in input_data


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_attachment_opener_no_caption_and_idempotent_replay(mock_run_tmux, mock_list_windows, tmp_path):
    mock_list_windows.return_value = {"architect", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.set("pod:acme:tenant:hq:agent:bob:launch", "codex")

    import base64
    raw_content = b"plain text data"
    b64_content = base64.b64encode(raw_content).decode("ascii")

    envelope = {
        "kind": "Attachment",
        "stream_id": "stream-abc",
        "l2": {"source": "architect", "destination": "bob"},
        "payload": {
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "content_base64": b64_content,
        },
    }

    # First delivery
    attachment_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelope=envelope,
        session_name="hq",
        workdir_root=str(tmp_path),
    )

    expected_file = tmp_path / "bob" / "attachments" / "stream-abc" / "notes.txt"
    assert expected_file.exists()
    assert expected_file.read_bytes() == raw_content

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert f"[attachment from architect] saved to {expected_file} (text/plain, {len(raw_content)} bytes)\n" in input_data
    assert "[attachment caption]" not in input_data

    # Idempotent replay: deliver second time with modified payload content
    new_content = b"updated text data"
    envelope["payload"]["content_base64"] = base64.b64encode(new_content).decode("ascii")
    attachment_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelope=envelope,
        session_name="hq",
        workdir_root=str(tmp_path),
    )
    assert expected_file.read_bytes() == new_content


@patch("flock.port.openers.list_windows")
def test_attachment_opener_validation_errors(mock_list_windows, tmp_path):
    mock_list_windows.return_value = {"architect", "bob"}
    r = FakeRespRedis()

    def make_env(payload, stream_id="str-1"):
        return {
            "kind": "Attachment",
            "stream_id": stream_id,
            "l2": {"source": "architect", "destination": "bob"},
            "payload": payload,
        }

    import base64
    valid_b64 = base64.b64encode(b"ok").decode("ascii")

    # Extra key
    with pytest.raises(DeadLetter):
        attachment_opener(r, "acme", "hq", "bob", make_env({
            "filename": "f.txt", "mime_type": "text/plain", "content_base64": valid_b64, "extra": "bad"
        }), "hq", workdir_root=str(tmp_path))

    # Missing required key
    with pytest.raises(DeadLetter):
        attachment_opener(r, "acme", "hq", "bob", make_env({
            "filename": "f.txt", "mime_type": "text/plain"
        }), "hq", workdir_root=str(tmp_path))

    # Invalid filenames
    for bad_name in [".", "..", "foo/bar", "foo\\bar", "foo\x00bar", "foo\x1fbar", "foo\x7fbar", "", "a" * 256]:
        with pytest.raises(DeadLetter):
            attachment_opener(r, "acme", "hq", "bob", make_env({
                "filename": bad_name, "mime_type": "text/plain", "content_base64": valid_b64
            }), "hq", workdir_root=str(tmp_path))

    # Invalid mime types
    for bad_mime in ["", "text", "text/plain; charset=utf-8", "image/*", "text/plain ", " text/plain", "a" * 256]:
        with pytest.raises(DeadLetter):
            attachment_opener(r, "acme", "hq", "bob", make_env({
                "filename": "f.txt", "mime_type": bad_mime, "content_base64": valid_b64
            }), "hq", workdir_root=str(tmp_path))

    # Invalid base64 (whitespace, url-safe, bad padding, invalid chars)
    for bad_b64 in ["aGVsbG8=\n", "aGVsbG8-", "aGVsbG8", "aGVsbG8==", "bad!char"]:
        with pytest.raises(DeadLetter):
            attachment_opener(r, "acme", "hq", "bob", make_env({
                "filename": "f.txt", "mime_type": "text/plain", "content_base64": bad_b64
            }), "hq", workdir_root=str(tmp_path))

    # Window missing
    mock_list_windows.return_value = {"architect"}
    with pytest.raises(DeadLetter, match="window_missing"):
        attachment_opener(r, "acme", "hq", "bob", make_env({
            "filename": "f.txt", "mime_type": "text/plain", "content_base64": valid_b64
        }), "hq", workdir_root=str(tmp_path))


@patch("flock.port.deliver.attachment_opener")
@patch("flock.port.deliver.messages_opener")
def test_attachment_burst_isolation(mock_messages, mock_attachment):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "bob", "tmux")
    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"

    env_msg1 = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "msg1"})
    env_att = build_envelope(kind="Attachment", source="alice", destination="bob", payload={"filename": "a.txt", "mime_type": "text/plain", "content_base64": "YQ=="})
    env_msg2 = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "msg2"})

    r.rpush(ingress_key, encode(env_msg1), encode(env_att), encode(env_msg2))

    from flock.port.deliver import deliver_one
    deliver_one(r, "acme", "hq", "bob")

    # Ingress drained
    assert len(r.lists.get(ingress_key, [])) == 0

    # messages_opener was called twice (msg1 flushed before attachment, msg2 flushed at end)
    assert mock_messages.call_count == 2
    assert mock_messages.call_args_list[0].kwargs["envelopes"][0]["payload"]["text"] == "msg1"
    assert mock_messages.call_args_list[1].kwargs["envelopes"][0]["payload"]["text"] == "msg2"

    # attachment_opener called once individually
    assert mock_attachment.call_count == 1


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_messages_opener_client_reply_trailer(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "telegram", "api")

    env = build_envelope(kind="Message", source="telegram", destination="bob", payload={"text": "status check"})
    messages_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelopes=[env],
        session_name="hq",
    )

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "[message from telegram] status check\n[reply to telegram]\n"


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_messages_opener_peer_no_trailer(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "alice", "tmux")

    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "peer msg"})
    messages_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelopes=[env],
        session_name="hq",
    )

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "[message from alice] peer msg\n"
    assert "[reply to" not in input_data


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_messages_opener_mixed_batch_trailer(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "telegram", "api")
    r.hset("pod:acme:tenant:hq:roster", "web", "api")
    r.hset("pod:acme:tenant:hq:roster", "alice", "tmux")

    envelopes = [
        build_envelope(kind="Message", source="telegram", destination="bob", payload={"text": "from telegram 1"}),
        build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "from alice"}),
        build_envelope(kind="Message", source="telegram", destination="bob", payload={"text": "from telegram 2"}),
        build_envelope(kind="Message", source="web", destination="bob", payload={"text": "from web"}),
    ]

    messages_opener(
        r,
        pod="acme",
        tenant="hq",
        agent="bob",
        envelopes=envelopes,
        session_name="hq",
    )

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    expected = (
        "[message from telegram] from telegram 1\n"
        "[reply to telegram]\n"
        "[message from alice] from alice\n"
        "[message from telegram] from telegram 2\n"
        "[reply to telegram]\n"
        "[message from web] from web\n"
        "[reply to web]\n"
    )
    assert input_data == expected
