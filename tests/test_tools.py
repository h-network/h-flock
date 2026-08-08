import sys
import pytest
from unittest.mock import patch, MagicMock

from flock.adapter.tools import send_message_cli, send_broadcast_cli, peers_cli


class MockRedis:
    def __init__(self, roster_agents, vab_map=None):
        self.roster_agents = set(roster_agents)
        self.vab_map = vab_map or {a: "tmux" for a in roster_agents}

    def hkeys(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}

    def hget(self, key, field):
        val = self.vab_map.get(field)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val

    def hexists(self, key, field):
        return field in self.roster_agents


def test_send_message_help(capsys):
    with patch.object(sys, "argv", ["sendMessage", "--help"]):
        with pytest.raises(SystemExit) as exc:
            send_message_cli()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "sendMessage" in captured.out
        assert "-a" in captured.out


def test_send_broadcast_help(capsys):
    with patch.object(sys, "argv", ["sendBroadcast", "--help"]):
        with pytest.raises(SystemExit) as exc:
            send_broadcast_cli()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "sendBroadcast" in captured.out


def test_peers_help(capsys):
    with patch.object(sys, "argv", ["peers", "--help"]):
        with pytest.raises(SystemExit) as exc:
            peers_cli()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "peers" in captured.out


@patch("flock.adapter.tools.send_envelope")
@patch("redis.Redis.from_url")
def test_send_message_exec(mock_redis_from_url, mock_send_env, monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "alice")
    monkeypatch.setenv("POD", "default")
    monkeypatch.setenv("TENANT", "default")

    mock_r = MockRedis(["alice", "bob"])
    mock_redis_from_url.return_value = mock_r

    with patch.object(sys, "argv", ["sendMessage", "-a", "bob", "hello", "bob"]):
        with pytest.raises(SystemExit) as exc:
            send_message_cli()
        assert exc.value.code == 0

    mock_send_env.assert_called_once()
    _, kwargs = mock_send_env.call_args
    assert kwargs["producer"] == "alice"
    assert kwargs["recipient"] == "bob"
    assert kwargs["payload"] == {"text": "hello bob"}
    assert kwargs["kind"] == "Message"


@patch("flock.adapter.tools.send_envelope")
@patch("redis.Redis.from_url")
def test_send_broadcast_exec(mock_redis_from_url, mock_send_env, monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "alice")
    monkeypatch.setenv("POD", "default")
    monkeypatch.setenv("TENANT", "default")

    mock_r = MockRedis(["alice", "bob", "carol", "api"], vab_map={"alice": "tmux", "bob": "tmux", "carol": "tmux", "api": "api"})
    mock_redis_from_url.return_value = mock_r

    with patch.object(sys, "argv", ["sendBroadcast", "standup", "now"]):
        with pytest.raises(SystemExit) as exc:
            send_broadcast_cli()
        assert exc.value.code == 0

    # Should send 2 envelopes (to bob and carol), NOT recipient: all
    assert mock_send_env.call_count == 2
    recipients = [c[1]["recipient"] for c in mock_send_env.call_args_list]
    assert recipients == ["bob", "carol"]


@patch("redis.Redis.from_url")
def test_peers_exec(mock_redis_from_url, capsys, monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "alice")
    monkeypatch.setenv("POD", "default")
    monkeypatch.setenv("TENANT", "default")

    mock_r = MockRedis(["alice", "bob", "carol", "api"], vab_map={"alice": "tmux", "bob": "tmux", "carol": "tmux", "api": "api"})
    mock_redis_from_url.return_value = mock_r

    with patch.object(sys, "argv", ["peers"]):
        with pytest.raises(SystemExit) as exc:
            peers_cli()
        assert exc.value.code == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "bob, carol"
