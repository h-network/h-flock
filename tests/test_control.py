import sys
import types

import pytest

from flock.bus import AGENT_STATE_RESOURCES, prefix
from flock.control import deliver_one, pause_agent, resume_agent, start_agent, stop_agent
from flock.control import runner


class RecordingRedis:
    def __init__(self, events, ingress_depth=0, roster_vab="tmux"):
        self.events = events
        self.ingress_depth = ingress_depth
        self.roster_vab = roster_vab

    def hset(self, key, field, value):
        self.events.append(("hset", key, field, value))

    def set(self, key, value):
        self.events.append(("set", key, value))

    def hdel(self, key, field):
        self.events.append(("hdel", key, field))

    def hget(self, key, field):
        self.events.append(("hget", key, field))
        return self.roster_vab

    def get(self, key):
        self.events.append(("get", key))
        return None

    def delete(self, *keys):
        self.events.append(("delete", *keys))

    def llen(self, key):
        self.events.append(("llen", key))
        return self.ingress_depth


def test_start_agent_orders_launch_roster_then_window():
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
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
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
    assert events == [
        ("set", prefix("acme", "hq", "dave", "launch"), "claude"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("create_window", "dave", "claude"),
    ]


def test_start_agent_writes_profile_before_roster_visibility():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "codex", "profile": "client-b"}},
        create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
    )
    assert events == [
        ("set", prefix("acme", "hq", "dave", "profile"), "client-b"),
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("create_window", "dave", "codex"),
    ]


@pytest.mark.parametrize("profile", [None, ""])
def test_start_agent_without_profile_writes_no_profile_key(profile):
    events = []
    payload = {"agent": "dave"}
    if profile is not None:
        payload["profile"] = profile
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": payload},
        create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
    )
    assert not any(":profile" in str(part) for event in events for part in event)


def test_start_api_client_only_writes_roster_row():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "telegram", "vab": "api"}},
        create_window=lambda agent, cli: events.append(("create_window", agent, cli)),
    )
    assert events == [
        ("hset", prefix("acme", "hq", resource="roster"), "telegram", "api"),
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
        ("hget", prefix("acme", "hq", resource="roster"), "dave"),
        ("hdel", prefix("acme", "hq", resource="roster"), "dave"),
        ("delete", *(prefix("acme", "hq", "dave", resource) for resource in sorted(AGENT_STATE_RESOURCES))),
        ("hdel", prefix("acme", "hq", resource="delivering"), "dave"),
        ("kill_window", "dave"),
    ]
    assert "profile" in AGENT_STATE_RESOURCES


def test_stop_api_client_removes_roster_and_mailbox_without_tmux():
    events = []
    stop_agent(
        RecordingRedis(events, roster_vab="api"),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "telegram"}},
        kill_window=lambda agent: events.append(("kill_window", agent)),
    )
    assert events == [
        ("hget", prefix("acme", "hq", resource="roster"), "telegram"),
        ("hdel", prefix("acme", "hq", resource="roster"), "telegram"),
        ("delete", *(prefix("acme", "hq", "telegram", resource) for resource in sorted(AGENT_STATE_RESOURCES))),
        ("hdel", prefix("acme", "hq", resource="delivering"), "telegram"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent": "all"},
        {"agent": "BadName"},
        {"agent": "dave", "cli": ""},
        {"agent": "dave", "cli": 42},
        {"agent": "dave", "vab": "control"},
        {"agent": "dave", "vab": 42},
        {"agent": "dave", "profile": "../client-b"},
        {"agent": "dave", "profile": "Client-B"},
        {"agent": "dave", "profile": 42},
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


def test_pause_agent_sets_marker_then_interrupts_without_touching_roster():
    events = []
    pause_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "backend"}},
        interrupt_window=lambda agent: events.append(("interrupt", agent)),
    )
    assert events == [
        ("set", prefix("acme", "hq", "backend", "paused"), 1),
        ("interrupt", "backend"),
    ]


def test_resume_agent_deletes_marker_then_resumes_without_touching_roster():
    events = []
    resume_agent(
        RecordingRedis(events, ingress_depth=3),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "backend"}},
        resume_window=lambda agent: events.append(("resume", agent)),
        kick_agent=lambda agent: events.append(("kick", agent)),
    )
    assert events == [
        ("delete", prefix("acme", "hq", "backend", "paused")),
        ("resume", "backend"),
        ("llen", prefix("acme", "hq", "backend", "ingress")),
        ("kick", "backend"),
        ("kick", "backend"),
        ("kick", "backend"),
    ]


@pytest.mark.parametrize(
    ("kind", "expected_tmux"),
    [
        (
            "StartAgent",
            (
                "create",
                "hq",
                "dave",
                [
                    "env",
                    "AGENT_NAME=dave",
                    "OFFICE_TOOLS=office",
                    "AGENT_GUIDE=/workdir/dave/AGENTS.md",
                    "startAgent",
                    "claude",
                ],
                "/tmp/tmux.sock",
            ),
        ),
        ("StopAgent", ("kill", "hq", "dave", "/tmp/tmux.sock")),
        ("PauseAgent", ("keys", "send-keys", "-t", "hq:dave", "C-c", "/tmp/tmux.sock")),
        (
            "ResumeAgent",
            (
                "keys",
                "send-keys",
                "-t",
                "hq:dave",
                "startAgent --resume",
                "Enter",
                "/tmp/tmux.sock",
            ),
        ),
    ],
)
def test_deliver_one_dispatches_control_kinds(monkeypatch, kind, expected_tmux):
    events = []
    from flock.tmux.ops import window_env
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.create_window = lambda session, agent, command=None, socket=None: (
        events.append(("create", session, agent, command, socket)) or (0, "", "")
    )
    fake_tmux.kill_window = lambda session, agent, socket=None: (
        events.append(("kill", session, agent, socket)) or (0, "", "")
    )
    fake_tmux.run_tmux = lambda *args, socket=None, **kwargs: (
        events.append(("keys", *args, socket)) or (0, "", "")
    )
    fake_tmux.window_env = window_env
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
    assert expected_tmux in events


def test_tmux_failure_raises_after_desired_state_is_written(monkeypatch):
    events = []
    from flock.tmux.ops import window_env
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.create_window = lambda *args, **kwargs: (1, "", "no server")
    fake_tmux.kill_window = lambda *args, **kwargs: (0, "", "")
    fake_tmux.run_tmux = lambda *args, **kwargs: (0, "", "")
    fake_tmux.window_env = window_env
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
    # ⚠ The create path resolves everything tmuxhost resolves — profile AND
    # endpoint — because create_window is idempotent by name, so whatever this
    # builds is what the agent keeps. A later reconcile will not correct it.
    assert events == [
        ("set", prefix("acme", "hq", "dave", "launch"), "claude"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("get", prefix("acme", "hq", "dave", "profile")),
        ("get", prefix("acme", "hq", "dave", "endpoint")),
    ]


def test_deliver_one_hired_agent_with_profile(monkeypatch):
    events = []
    from flock.tmux.ops import window_env
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.create_window = lambda session, agent, command=None, socket=None: (
        events.append(("create", session, agent, command, socket)) or (0, "", "")
    )
    fake_tmux.kill_window = lambda session, agent, socket=None: (0, "", "")
    fake_tmux.run_tmux = lambda *args, socket=None, **kwargs: (0, "", "")
    fake_tmux.window_env = window_env
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    class ProfileRedis(RecordingRedis):
        def get(self, key):
            if "profile" in key:
                return b"work"
            return None

    def fake_receive(r, **kwargs):
        kwargs["openers"]["StartAgent"]({"payload": {"agent": "iris", "cli": "claude"}})

    monkeypatch.setattr(runner, "receive", fake_receive)
    deliver_one(
        ProfileRedis(events),
        pod="acme",
        tenant="hq",
        agent="host",
        session_name="hq",
        socket="/tmp/tmux.sock",
    )
    create_event = [e for e in events if e[0] == "create"][0]
    cmd = create_event[3]
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work" in cmd
    assert "CODEX_HOME=/home/ubuntu/.codex-work" in cmd
    assert "OFFICE_TOOLS=office" in cmd
    assert "AGENT_GUIDE=/workdir/iris/AGENTS.md" in cmd
