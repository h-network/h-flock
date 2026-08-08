import sys
import types

import pytest

from flock.bus import prefix
from flock.control import deliver_one, start_agent, stop_agent
from flock.control import runner


class RecordingRedis:
    def __init__(self, events):
        self.events = events

    def hset(self, key, field, value):
        self.events.append(("hset", key, field, value))

    def set(self, key, value):
        self.events.append(("set", key, value))

    def hdel(self, key, field):
        self.events.append(("hdel", key, field))

    def delete(self, key):
        self.events.append(("delete", key))


def test_start_agent_orders_roster_launch_then_window():
    events = []
    r = RecordingRedis(events)
    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "codex"}},
        create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
    )
    assert events == [
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("create_window", "dave", "codex"),
    ]


def test_start_agent_defaults_cli_to_claude():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave"}},
        create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
    )
    assert events[-2:] == [
        ("set", prefix("acme", "hq", "dave", "launch"), "claude"),
        ("create_window", "dave", "claude"),
    ]


def test_stop_agent_orders_roster_launch_then_window():
    events = []
    r = RecordingRedis(events)
    stop_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave"}},
        kill_window=lambda agent: events.append(("kill_window", agent)),
    )
    assert events == [
        ("hdel", prefix("acme", "hq", resource="roster"), "dave"),
        ("delete", prefix("acme", "hq", "dave", "launch")),
        ("kill_window", "dave"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent": "all"},
        {"agent": "BadName"},
        {"agent": "dave", "cli": ""},
        {"agent": "dave", "cli": 42},
    ],
)
def test_start_agent_rejects_invalid_payload_before_mutation(payload):
    events = []
    with pytest.raises((KeyError, ValueError)):
        start_agent(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            envelope={"payload": payload},
            create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
        )
    assert events == []


def test_stop_agent_rejects_invalid_target_before_mutation():
    events = []
    with pytest.raises(KeyError):
        stop_agent(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "all"}},
            kill_window=lambda agent: events.append(("kill_window", agent)),
        )
    assert events == []


@pytest.mark.parametrize(
    ("kind", "expected_tmux"),
    [
        (
            "StartAgent",
            (
                "create",
                "hq",
                "dave",
                ["env", "AGENT_NAME=dave", "claude"],
                "/tmp/tmux.sock",
            ),
        ),
        ("StopAgent", ("kill", "hq", "dave", "/tmp/tmux.sock")),
    ],
)
def test_deliver_one_dispatches_control_kinds(monkeypatch, kind, expected_tmux):
    events = []
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.create_window = lambda session, agent, command=None, socket=None: (
        events.append(("create", session, agent, command, socket)) or (0, "", "")
    )
    fake_tmux.kill_window = lambda session, agent, socket=None: (
        events.append(("kill", session, agent, socket)) or (0, "", "")
    )
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    def fake_receive(r, **kwargs):
        kwargs["openers"][kind]({"payload": {"agent": "dave"}})

    monkeypatch.setattr(runner, "receive", fake_receive)
    deliver_one(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        agent="host",
        session_name="hq",
        socket="/tmp/tmux.sock",
    )
    assert events[-1] == expected_tmux


def test_tmux_failure_raises_after_desired_state_is_written(monkeypatch):
    events = []
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.create_window = lambda *args, **kwargs: (1, "", "no server")
    fake_tmux.kill_window = lambda *args, **kwargs: (0, "", "")
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    def fake_receive(r, **kwargs):
        kwargs["openers"]["StartAgent"]({"payload": {"agent": "dave"}})

    monkeypatch.setattr(runner, "receive", fake_receive)
    with pytest.raises(RuntimeError, match="create-window failed"):
        deliver_one(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            agent="host",
            session_name="hq",
        )
    assert events == [
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("set", prefix("acme", "hq", "dave", "launch"), "claude"),
    ]
