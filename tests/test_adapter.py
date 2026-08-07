import json
import pytest
from unittest.mock import patch, MagicMock
from flock.adapter.openers import message_opener, get_tmux_windows
from flock.adapter.cli import main as cli_main
from flock.bus import build as build_envelope


class MockRedis:
    def __init__(self):
        self.lists = {}

    def rpush(self, key, value):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].append(value)


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
