import json
import pathlib
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from flock.adapter.openers import add_ticket_opener, message_opener, command_opener, get_tmux_windows
from flock.adapter.cli import main as cli_main
from flock.adapter.runner import run_adapter
from flock.bus import DeadLetter, build as build_envelope


class MockRedis:
    def __init__(self):
        self.lists = {}
        self.hashes = {}
        self.kv = {}
        self.streams = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value):
        self.kv[key] = value

    def rpush(self, key, value):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].append(value)

    def blpop(self, key, timeout=0):
        if key in self.lists and self.lists[key]:
            val = self.lists[key].pop(0)
            return (key, val)
        return None

    def hset(self, key, field, value):
        if key not in self.hashes:
            self.hashes[key] = {}
        self.hashes[key][field] = value

    def hsetnx(self, key, field, value):
        if key not in self.hashes:
            self.hashes[key] = {}
        if field in self.hashes[key]:
            return 0
        self.hashes[key][field] = value
        return 1

    def hexists(self, key, field):
        return field in self.hashes.get(key, {})

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hdel(self, key, field):
        if key in self.hashes and field in self.hashes[key]:
            del self.hashes[key][field]

    def xadd(self, name, fields, id="*", maxlen=None, approximate=True):
        if name not in self.streams:
            self.streams[name] = []
        stream_id = f"{len(self.streams[name]) + 1}-0"
        self.streams[name].append((stream_id, fields))
        if maxlen and len(self.streams[name]) > maxlen:
            self.streams[name] = self.streams[name][-maxlen:]
        return stream_id


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_window_exists(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("load-buffer" in cmd for cmd in cmd_args)
    assert any("paste-buffer" in cmd for cmd in cmd_args)
    assert any("send-keys" in cmd for cmd in cmd_args)
    assert any("delete-buffer" in cmd for cmd in cmd_args)

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "[message from alice] hello\n"


@patch("flock.adapter.openers.list_windows")
def test_message_opener_window_missing(mock_list_windows):
    mock_list_windows.return_value = {"alice"}

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})

    with pytest.raises(DeadLetter, match="window_missing"):
        message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    assert "pod:acme:tenant:hq:agent:bob:dead" not in r.lists


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_broadcast(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob", "carol"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="all", payload={"text": "broadcast message"})

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_command_opener_bare_paste(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="Command", producer="alice", recipient="bob", payload={"text": "touch /tmp/it-ran"})

    command_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    assert input_data == "touch /tmp/it-ran\n"
    assert "[message from" not in input_data


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_writes_v1_ticket(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(
        kind="AddTicket",
        producer="architect",
        recipient="backend",
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


def test_assign_task_is_no_longer_a_kind():
    """The compatibility alias is gone. Build 11 said "remove it in the build
    after"; it survived four. An unknown kind now dead-letters with a reason,
    which is the correct answer and a visible one."""
    from flock.adapter import runner

    assert not hasattr(runner, "assign_task_opener")
    assert "AssignTask" not in pathlib.Path(runner.__file__).read_text()


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_appends_to_task_record(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "tasks.jsonl")
        with patch.dict(os.environ, {"TASK_RECORD": log_file}):
            r = MockRedis()
            env = build_envelope(
                kind="AddTicket",
                producer="architect",
                recipient="backend",
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


@patch("flock.adapter.runner.redis.Redis.from_url")
@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_run_adapter_kicked_one_shot(mock_run_tmux, mock_list_windows, mock_redis_cls):
    mock_r = MockRedis()
    mock_redis_cls.return_value = mock_r
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "kicked message"})
    mock_r.rpush(ingress_key, json.dumps(env))

    run_adapter(agent="bob", pod="acme", tenant="hq", session_name="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0

    delivering_key = "pod:acme:tenant:hq:delivering"
    assert not mock_r.hexists(delivering_key, "bob")

    cmd_args = [call[0] for call in mock_run_tmux.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


@patch("flock.adapter.runner.redis.Redis.from_url")
def test_run_adapter_paused_leaves_envelope_in_ingress(mock_redis_cls):
    mock_r = MockRedis()
    mock_redis_cls.return_value = mock_r

    paused_key = "pod:acme:tenant:hq:agent:bob:paused"
    mock_r.set(paused_key, "1")

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "paused message"})
    mock_r.rpush(ingress_key, json.dumps(env))

    run_adapter(agent="bob", pod="acme", tenant="hq", session_name="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 1
    delivering_key = "pod:acme:tenant:hq:delivering"
    assert not mock_r.hexists(delivering_key, "bob")


@patch("flock.adapter.cli.redis.Redis.from_url")
def test_cli_send(mock_redis_cls, monkeypatch):
    mock_r = MockRedis()
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
    pushed = json.loads(mock_r.lists[egress_key][0])
    assert pushed["producer"] == "alice"
    assert pushed["recipient"] == "bob"
    assert pushed["payload"] == {"text": "hello world"}


@patch("flock.adapter.runner.redis.Redis.from_url")
def test_run_adapter_vab_api_pops_and_writes_mailbox(mock_redis_cls):
    mock_r = MockRedis()
    mock_redis_cls.return_value = mock_r

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "api", "api")

    ingress_key = "pod:acme:tenant:hq:agent:api:ingress"
    env = build_envelope(kind="Message", producer="alice", recipient="api", payload={"text": "reply"})
    mock_r.rpush(ingress_key, json.dumps(env))

    run_adapter(agent="api", pod="acme", tenant="hq", session_name="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0
    inbox_key = "pod:acme:tenant:hq:agent:api:inbox"
    assert inbox_key in mock_r.streams
    assert len(mock_r.streams[inbox_key]) == 1
    stream_id, fields = mock_r.streams[inbox_key][0]
    assert "envelope" in fields
    stored_env = json.loads(fields["envelope"])
    assert stored_env["producer"] == "alice"
    assert stored_env["recipient"] == "api"
    assert stored_env["payload"] == {"text": "reply"}


@patch("flock.adapter.runner.redis.Redis.from_url")
def test_run_adapter_unroutable_vab_pops_and_dead_letters(mock_redis_cls):
    mock_r = MockRedis()
    mock_redis_cls.return_value = mock_r

    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "host", "custom_vab")

    ingress_key = "pod:acme:tenant:hq:agent:host:ingress"
    env = build_envelope(kind="Message", producer="alice", recipient="host", payload={"text": "test"})
    mock_r.rpush(ingress_key, json.dumps(env))

    run_adapter(agent="host", pod="acme", tenant="hq", session_name="hq")

    assert len(mock_r.lists.get(ingress_key, [])) == 0
    dead_key = "pod:acme:tenant:hq:agent:host:dead"
    assert len(mock_r.lists.get(dead_key, [])) == 1


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_writes_pending_verify_marker_for_claude(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    r.set("pod:acme:tenant:hq:agent:bob:launch", "claude")
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert verify_key in r.streams
    assert len(r.streams[verify_key]) == 1
    _, fields = r.streams[verify_key][0]
    assert fields["stream_id"] == "12345-0"
    assert "ts" in fields


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_skips_pending_verify_marker_for_agy(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    launch_key = "pod:acme:tenant:hq:agent:bob:launch"
    r.set(launch_key, "agy")
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:bob:pending.verify"
    assert verify_key not in r.streams


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_add_ticket_opener_skips_pending_verify_marker(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"architect", "backend"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="AddTicket", producer="architect", recipient="backend", payload={"title": "task"})
    env["stream_id"] = "12345-0"

    add_ticket_opener(r, pod="acme", tenant="hq", agent="backend", envelope=env, session_name="hq")

    verify_key = "pod:acme:tenant:hq:agent:backend:pending.verify"
    assert verify_key not in r.streams


@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_mark_delivery_pending_swallows_redis_exceptions(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    class FaultyRedis(MockRedis):
        def xadd(self, *args, **kwargs):
            raise RuntimeError("Redis stream error")

    r = FaultyRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})
    env["stream_id"] = "12345-0"

    # Must complete cleanly without raising exception
    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")



@patch("flock.adapter.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_no_marker_for_a_window_running_no_cli(mock_run_tmux, mock_list_windows):
    """A bare shell writes no session file, so a delivery to it can never be
    confirmed. Marking it reported unverified forever.

    Measured: with a denylist that skipped only agy, three of the first four
    unverified records in a live run were bash windows.
    """
    mock_list_windows.return_value = {"alice", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    r = MockRedis()  # no launch key at all
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hi"})
    env["stream_id"] = "12345-0"

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    assert "pod:acme:tenant:hq:agent:bob:pending.verify" not in r.streams
