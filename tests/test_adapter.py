import json
import pytest
from unittest.mock import patch, MagicMock
from flock.adapter.openers import message_opener, get_tmux_windows
from flock.adapter.cli import main as cli_main
from flock.adapter.runner import run_adapter
from flock.bus import build as build_envelope


class MockRedis:
    def __init__(self):
        self.lists = {}
        self.hashes = {}

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


@patch("flock.adapter.openers.get_tmux_windows")
@patch("flock.adapter.openers.run_tmux_cmd")
def test_message_opener_window_exists(mock_run_tmux_cmd, mock_get_windows):
    mock_get_windows.return_value = {"alice", "bob"}
    mock_run_tmux_cmd.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    # Check buffer operations were invoked
    cmd_args = [call[0][0] for call in mock_run_tmux_cmd.call_args_list]
    assert any("load-buffer" in cmd for cmd in cmd_args)
    assert any("paste-buffer" in cmd for cmd in cmd_args)
    assert any("send-keys" in cmd for cmd in cmd_args)
    assert any("delete-buffer" in cmd for cmd in cmd_args)


@patch("flock.adapter.openers.get_tmux_windows")
def test_message_opener_window_missing(mock_get_windows):
    mock_get_windows.return_value = {"alice"}

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "hello"})

    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    # Should dead-letter under bob's prefix
    dead_key = "pod:acme:tenant:hq:agent:bob:dead"
    assert dead_key in r.lists
    assert len(r.lists[dead_key]) == 1


@patch("flock.adapter.openers.get_tmux_windows")
@patch("flock.adapter.openers.run_tmux_cmd")
def test_message_opener_broadcast(mock_run_tmux_cmd, mock_get_windows):
    mock_get_windows.return_value = {"alice", "bob", "carol"}
    mock_run_tmux_cmd.return_value = (0, "", "")

    r = MockRedis()
    env = build_envelope(kind="Message", producer="alice", recipient="all", payload={"text": "broadcast message"})

    # Delivered to bob's window
    message_opener(r, pod="acme", tenant="hq", agent="bob", envelope=env, session_name="hq")

    cmd_args = [call[0][0] for call in mock_run_tmux_cmd.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


@patch("flock.adapter.runner.redis.Redis.from_url")
@patch("flock.adapter.openers.get_tmux_windows")
@patch("flock.adapter.openers.run_tmux_cmd")
def test_run_adapter_kicked_one_shot(mock_run_tmux_cmd, mock_get_windows, mock_redis_cls):
    mock_r = MockRedis()
    mock_redis_cls.return_value = mock_r
    mock_get_windows.return_value = {"alice", "bob"}
    mock_run_tmux_cmd.return_value = (0, "", "")

    # Set up roster HASH
    roster_key = "pod:acme:tenant:hq:roster"
    mock_r.hset(roster_key, "bob", "tmux")

    # Put envelope in ingress queue
    ingress_key = "pod:acme:tenant:hq:agent:bob:ingress"
    env = build_envelope(kind="Message", producer="alice", recipient="bob", payload={"text": "kicked message"})
    mock_r.rpush(ingress_key, json.dumps(env))

    # Run kicked adapter for bob
    run_adapter(agent="bob", pod="acme", tenant="hq", session_name="hq")

    # Check ingress queue was popped
    assert len(mock_r.lists.get(ingress_key, [])) == 0

    # Check busy tag was cleared
    delivering_key = "pod:acme:tenant:hq:delivering"
    assert not mock_r.hexists(delivering_key, "bob")

    # Check tmux paste command ran for bob
    cmd_args = [call[0][0] for call in mock_run_tmux_cmd.call_args_list]
    assert any("paste-buffer" in cmd and "hq:bob" in cmd for cmd in cmd_args)


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
