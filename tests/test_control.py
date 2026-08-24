from conftest import FakeRedis, FakeRedis as RecordingRedis
import json
import sys
import types

import pytest

from flock.bus import AGENT_STATE_RESOURCES, prefix
from flock.control import deliver_one, pause_agent, resume_agent, start_agent, stop_agent
from flock.control import runner



def test_start_agent_publishes_desired_state_without_creating_window():
    events = []
    r = RecordingRedis(events)
    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "codex"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert events == [
        ("hget", prefix("acme", "hq", resource="roster"), "dave"),
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
    ]


def test_fresh_start_publishes_window_cause_before_roster_visibility():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={
            "correlation_id": "hire-correlation",
            "payload": {"agent": "dave", "cli": "codex"},
        },
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert events == [
        ("hget", prefix("acme", "hq", resource="roster"), "dave"),
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        (
            "eval",
            2,
            prefix("acme", "hq", "dave", "window.cause"),
            prefix("acme", "hq", resource="roster"),
            "hire-correlation",
            "dave",
            "tmux",
        ),
    ]


def test_fresh_hire_cause_and_roster_are_atomic_on_real_redis(tmp_path):
    import shutil
    import socket
    import subprocess
    import time
    from pathlib import Path

    import redis

    redis_bin = shutil.which("redis-server") or "/usr/bin/redis-server"
    if not Path(redis_bin).exists():
        pytest.fail(f"redis-server binary not found at {redis_bin} - real redis test is mandatory")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        redis_port = listener.getsockname()[1]

    process = subprocess.Popen(
        [
            redis_bin,
            "--port",
            str(redis_port),
            "--dir",
            str(tmp_path),
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(50):
            try:
                client = redis.Redis(host="127.0.0.1", port=redis_port, decode_responses=True)
                if client.ping():
                    break
            except Exception:
                time.sleep(0.05)
        else:
            pytest.fail(f"could not connect to real redis-server on port {redis_port}")

        class ReplyLossRedis:
            def __getattr__(self, name):
                return getattr(client, name)

            def eval(self, *args):
                client.eval(*args)
                raise ConnectionError("reply lost after atomic publish")

        with pytest.raises(ConnectionError, match="reply lost after atomic publish"):
            start_agent(
                ReplyLossRedis(),
                pod="acme",
                tenant="hq",
                envelope={
                    "correlation_id": "hire-correlation",
                    "payload": {"agent": "dave"},
                },
                replace_window=lambda _agent: None,
            )

        assert client.get(prefix("acme", "hq", "dave", "window.cause")) == "hire-correlation"
        assert client.hget(prefix("acme", "hq", resource="roster"), "dave") == "tmux"

        # Redis scripts isolate intermediate writes but do not roll them back
        # after a command error. HSET must therefore precede SET: a corrupt
        # roster may yield no membership, but it must never strand a cause.
        from flock.control.openers import _PUBLISH_WINDOW_CAUSE_LUA

        client.flushdb()
        cause_key = prefix("acme", "hq", "dave", "window.cause")
        roster_key = prefix("acme", "hq", resource="roster")
        client.set(roster_key, "wrong-type")
        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            client.eval(
                _PUBLISH_WINDOW_CAUSE_LUA,
                2,
                cause_key,
                roster_key,
                "hire-correlation",
                "dave",
                "tmux",
            )
        assert client.get(cause_key) is None
    finally:
        process.terminate()
        process.wait(timeout=2)


def test_start_agent_defaults_cli_to_claude():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert events == [
        ("hget", prefix("acme", "hq", resource="roster"), "dave"),
        ("set", prefix("acme", "hq", "dave", "launch"), "claude"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
    ]


def test_fresh_start_accepts_desired_state_without_claiming_actual_state(capsys):
    events = []
    start_agent(
        RecordingRedis(events), pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "start_agent_accepted"
    assert not any(event[0] == "replace_window" for event in events)


def test_start_agent_writes_profile_before_roster_visibility():
    events = []
    start_agent(
        RecordingRedis(events, account_profiles={"default", "client-b"}),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "dave", "cli": "codex", "profile": "client-b"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert events == [
        ("smembers", prefix("acme", "hq", resource="accounts")),
        ("hget", prefix("acme", "hq", resource="roster"), "dave"),
        ("set", prefix("acme", "hq", "dave", "profile"), "client-b"),
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
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
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert not any(":profile" in str(part) for event in events for part in event)


def test_start_api_client_only_writes_roster_row():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": "telegram", "port_type": "api"}},
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    assert events == [
        ("hset", prefix("acme", "hq", resource="roster"), "telegram", "api"),
    ]


def test_start_agent_publishes_policy_before_roster_visibility():
    events = []
    start_agent(
        RecordingRedis(events),
        pod="acme",
        tenant="hq",
        envelope={
            "payload": {
                "agent": "telegram",
                "port_type": "api",
                "export": ["reviewers", "hq", "reviewers"],
                "import": ["hq"],
            }
        },
        replace_window=lambda agent: events.append(("replace_window", agent)),
    )
    policy_key = prefix("acme", "hq", "telegram", "tags")
    assert events == [
        ("delete", policy_key),
        ("hset", policy_key, "export", '["hq","reviewers"]'),
        ("hset", policy_key, "import", '["hq"]'),
        ("hset", prefix("acme", "hq", resource="roster"), "telegram", "api"),
    ]


@pytest.mark.parametrize("side", ["export", "import"])
def test_start_agent_rejects_invalid_policy_before_mutation(side):
    events = []
    with pytest.raises(ValueError, match=f"payload.{side}"):
        start_agent(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", side: ["valid", "NOT VALID"]}},
            replace_window=lambda agent: events.append(("replace_window", agent)),
        )
    assert events == []


def test_start_agent_rejects_unknown_payload_key_before_defaulting_port_type():
    events = []
    with pytest.raises(ValueError, match="unknown payload key 'port_typ'"):
        start_agent(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "port_typ": "api"}},
            replace_window=lambda agent: events.append(("replace_window", agent)),
        )
    assert events == []


@pytest.mark.parametrize(
    ("opener", "callback_name"),
    [
        (stop_agent, "kill_window"),
        (pause_agent, "interrupt_window"),
        (resume_agent, "resume_window"),
    ],
)
def test_target_only_lifecycle_openers_reject_unknown_payload_key(opener, callback_name):
    events = []
    kwargs = {
        "r": RecordingRedis(events),
        "pod": "acme",
        "tenant": "hq",
        "envelope": {"payload": {"agent": "dave", "force": True}},
        callback_name: lambda agent: events.append((callback_name, agent)),
    }
    if opener is resume_agent:
        kwargs["kick_agent"] = lambda agent: events.append(("kick_agent", agent))
    with pytest.raises(ValueError, match="unknown payload key 'force'"):
        opener(**kwargs)
    assert events == []


def test_stop_agent_orders_roster_launch_then_window():
    events = []
    r = RecordingRedis(events, roster_port_type="tmux")
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


def test_stop_api_client_removes_roster_but_retains_mailbox_without_tmux():
    events = []
    stop_agent(
        RecordingRedis(events, roster_port_type="api"),
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
    deleted_keys = next(event[1:] for event in events if event[0] == "delete")
    assert prefix("acme", "hq", "telegram", "inbox") not in deleted_keys
    assert "inbox" not in AGENT_STATE_RESOURCES


@pytest.mark.parametrize("agent", ["api", "host"])
def test_stop_agent_rejects_fixed_participant_before_mutation(agent):
    events = []
    with pytest.raises(ValueError, match=f"cannot stop fixed participant: {agent}"):
        stop_agent(
            RecordingRedis(events),
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": agent}},
            kill_window=lambda target: events.append(("kill_window", target)),
        )
    assert events == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent": "all"},
        {"agent": "BadName"},
        {"agent": "dave", "cli": ""},
        {"agent": "dave", "cli": 42},
        {"agent": "dave", "port_type": "control"},
        {"agent": "dave", "port_type": 42},
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
            replace_window=lambda agent: events.append(("replace_window", agent)),
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
        ("StartAgent", None),
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
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.kill_window = lambda session, agent, socket=None: (
        events.append(("kill", session, agent, socket)) or (0, "", "")
    )
    fake_tmux.run_tmux = lambda *args, socket=None, **kwargs: (
        events.append(("keys", *args, socket)) or (0, "", "")
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
    if expected_tmux is None:
        assert not any(event[0] in ("kill", "keys") for event in events)
    else:
        assert expected_tmux in events


def test_changed_existing_hire_retires_stale_window_after_desired_state(monkeypatch):
    events = []
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.kill_window = lambda session, agent, socket=None: (
        events.append(("kill", session, agent, socket)) or (0, "", "")
    )
    fake_tmux.run_tmux = lambda *args, **kwargs: (0, "", "")
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    r = FakeRedis(events, roster_port_type="tmux", data={prefix("acme", "hq", "dave", "launch"): b"claude"})
    def fake_receive(r, **kwargs):
        kwargs["openers"]["StartAgent"]({"payload": {"agent": "dave", "cli": "codex"}})

    monkeypatch.setattr(runner, "receive", fake_receive)
    deliver_one(r, pod="acme", tenant="hq", agent="host", session_name="hq")

    assert events[-3:] == [
        ("set", prefix("acme", "hq", "dave", "launch"), "codex"),
        ("hset", prefix("acme", "hq", resource="roster"), "dave", "tmux"),
        ("kill", "hq", "dave", None),
    ]


def test_fresh_hire_with_profile_and_provider_leaves_creation_to_tmuxhost(monkeypatch):
    events = []
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.kill_window = lambda session, agent, socket=None: (
        events.append(("kill", session, agent, socket)) or (0, "", "")
    )
    fake_tmux.run_tmux = lambda *args, socket=None, **kwargs: (0, "", "")
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    def fake_receive(r, **kwargs):
        kwargs["openers"]["StartAgent"]({
            "payload": {"agent": "iris", "cli": "claude", "profile": "work", "provider": "gpu"}
        })

    monkeypatch.setattr(runner, "receive", fake_receive)
    deliver_one(
        RecordingRedis(events, account_profiles={"default", "work"}),
        pod="acme",
        tenant="hq",
        agent="host",
        session_name="hq",
        socket="/tmp/tmux.sock",
    )
    assert ("set", prefix("acme", "hq", "iris", "profile"), "work") in events
    assert ("set", prefix("acme", "hq", "iris", "provider"), "gpu") in events
    assert not any(event[0] == "kill" for event in events)


@pytest.mark.parametrize(
    ("opener", "callbacks"),
    [
        (start_agent, {"replace_window": lambda agent: None}),
        (stop_agent, {"kill_window": lambda agent: None}),
        (pause_agent, {"interrupt_window": lambda agent: None}),
        (resume_agent, {"resume_window": lambda agent: None, "kick_agent": lambda agent: None}),
    ],
)
def test_control_openers_record_accepted_outcome(opener, callbacks, capsys):
    opener(
        RecordingRedis([], roster_port_type="api"), pod="acme", tenant="hq",
        envelope={"correlation_id": "corr-1", "payload": {"agent": "dave"}}, **callbacks,
    )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == f"{opener.__name__}_accepted"
    assert record["destination"] == "dave"
    assert record["correlation_id"] == "corr-1"


def test_refused_start_records_failure_before_dead_letter(capsys):
    with pytest.raises(ValueError, match="unknown payload key 'typo'"):
        start_agent(
            RecordingRedis([]), pod="acme", tenant="hq",
            envelope={"correlation_id": "corr-2", "payload": {"agent": "dave", "typo": True}},
            replace_window=lambda agent: None,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "start_agent_failed"
    assert record["destination"] == "dave"
    assert "unknown payload key" in record["reason"]


def test_start_agent_refuses_unknown_profile_and_lists_available():
    with pytest.raises(ValueError, match="unknown account 'typo'; available accounts: default, work"):
        start_agent(
            RecordingRedis([], account_profiles={"default", "work"}), pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave", "profile": "typo"}},
            replace_window=lambda agent: None,
        )


def test_start_agent_permits_profile_when_legacy_accounts_key_is_absent():
    events = []
    start_agent(
        RecordingRedis(events), pod="acme", tenant="hq",
        envelope={"payload": {"agent": "dave", "profile": "legacy"}},
        replace_window=lambda agent: None,
    )
    assert ("set", prefix("acme", "hq", "dave", "profile"), "legacy") in events


@pytest.mark.parametrize(
    ("opener", "redis", "callbacks", "committed"),
    [
        (start_agent, RecordingRedis([], roster_port_type="tmux"),
         {"replace_window": lambda agent: (_ for _ in ()).throw(RuntimeError("replace failed"))},
         "launch published, roster row published"),
        (stop_agent, RecordingRedis([], roster_port_type="tmux"),
         {"kill_window": lambda agent: (_ for _ in ()).throw(RuntimeError("kill failed"))},
         "roster row removed, agent resources purged, delivery lock cleared"),
        (pause_agent, RecordingRedis([]),
         {"interrupt_window": lambda agent: (_ for _ in ()).throw(RuntimeError("interrupt failed"))},
         "paused marker published"),
        (resume_agent, RecordingRedis([]),
         {"resume_window": lambda agent: (_ for _ in ()).throw(RuntimeError("resume failed")),
          "kick_agent": lambda agent: None},
         "paused marker removed"),
    ],
)
def test_post_commit_side_effect_failure_records_incomplete(
    opener, redis, callbacks, committed, capsys
):
    with pytest.raises(RuntimeError, match="failed"):
        opener(
            redis, pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave"}}, **callbacks,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == f"{opener.__name__}_incomplete"
    assert f"acknowledged: {committed}" in record["reason"]
    assert "outcome UNKNOWN" in record["reason"]


def test_reply_loss_after_window_kill_reports_unknown_not_failed(capsys):
    operations = []

    def kill_then_lose_reply(agent):
        operations.append(("window-killed", agent))
        raise ConnectionError("reply lost after kill")

    with pytest.raises(ConnectionError, match="reply lost after kill"):
        stop_agent(
            RecordingRedis(operations, roster_port_type="tmux"),
            pod="acme", tenant="hq", envelope={"payload": {"agent": "dave"}},
            kill_window=kill_then_lose_reply,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "stop_agent_incomplete"
    assert record["reason"] == (
        "acknowledged: roster row removed, agent resources purged, delivery lock cleared; "
        "killing the window outcome UNKNOWN after reply lost after kill"
    )
    assert operations[-1] == ("window-killed", "dave")


def test_resume_names_actual_acknowledgements_before_unknown_kick(capsys):
    operations = []

    def kick(agent):
        operations.append(("kick", agent))
        if len([item for item in operations if item[0] == "kick"]) == 2:
            raise ConnectionError("reply lost after second kick")

    with pytest.raises(ConnectionError, match="reply lost after second kick"):
        resume_agent(
            RecordingRedis(operations, ingress_depth=2),
            pod="acme", tenant="hq", envelope={"payload": {"agent": "dave"}},
            resume_window=lambda agent: operations.append(("resumed", agent)),
            kick_agent=kick,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "resume_agent_incomplete"
    assert "actual acknowledged: window resumed, kick 1" in record["reason"]
    assert "kick 2 outcome UNKNOWN after reply lost after second kick" in record["reason"]


def test_resume_provable_kick_failure_records_partially_failed_without_acknowledging_it(
    monkeypatch, capsys
):
    events = []
    fake_tmux = types.ModuleType("flock.tmux")
    fake_tmux.kill_window = lambda *args, **kwargs: (0, "", "")
    fake_tmux.run_tmux = lambda *args, **kwargs: (0, "", "")
    monkeypatch.setitem(sys.modules, "flock.tmux", fake_tmux)

    spawns = []

    def popen(command):
        spawns.append(command)
        if len(spawns) == 2:
            raise FileNotFoundError("flock.port not found")
        return object()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)

    def fake_receive(r, **kwargs):
        kwargs["openers"]["ResumeAgent"]({
            "correlation_id": "corr-resume",
            "payload": {"agent": "dave"},
        })

    monkeypatch.setattr(runner, "receive", fake_receive)
    with pytest.raises(runner.ProvableActualFailure, match="did not spawn"):
        deliver_one(
            RecordingRedis(events, ingress_depth=2),
            pod="acme", tenant="hq", agent="host", session_name="hq",
        )

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["event"] for record in records] == ["resume_agent_partially_failed"]
    assert records[0]["reason"] == (
        "acknowledged: paused marker removed; "
        "actual acknowledged: window resumed, kick 1; "
        "kick 2 failed: port process did not spawn after flock.port not found"
    )
    assert "kick 2" not in records[0]["reason"].split("; actual acknowledged: ", 1)[1].split(";", 1)[0]
    assert spawns == [["flock.port", "dave"], ["flock.port", "dave"]]


def test_stop_partial_desired_write_names_committed_subset(capsys):

    events = []
    with pytest.raises(RuntimeError, match="purge write failed"):
        stop_agent(
            FakeRedis(events, roster_port_type="tmux", fails_on={"delete": RuntimeError("purge write failed")}), pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave"}}, kill_window=lambda agent: None,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "stop_agent_incomplete"
    assert record["reason"] == (
        "acknowledged: roster row removed; agent resource purge outcome UNKNOWN after purge write failed"
    )
    assert events[1] == ("hdel", prefix("acme", "hq", resource="roster"), "dave")


def test_start_partial_desired_write_names_committed_subset(capsys):

    with pytest.raises(RuntimeError, match="roster publish failed"):
        start_agent(
            FakeRedis([], fails_on={"hset": lambda key, *a: (_ for _ in ()).throw(RuntimeError("roster publish failed")) if key == prefix("acme", "hq", resource="roster") else None}), pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave"}}, replace_window=lambda agent: None,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "start_agent_incomplete"
    assert record["reason"] == (
        "acknowledged: launch published; roster row publish outcome UNKNOWN after roster publish failed"
    )


def test_first_desired_write_exception_records_unknown_incomplete(capsys):

    with pytest.raises(RuntimeError, match="first write failed"):
        start_agent(
            FakeRedis([], fails_on={"set": RuntimeError("first write failed")}), pod="acme", tenant="hq",
            envelope={"payload": {"agent": "dave"}}, replace_window=lambda agent: None,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "start_agent_incomplete"
    assert record["reason"] == (
        "none acknowledged; launch publish outcome UNKNOWN after first write failed"
    )


def test_reply_loss_after_first_write_records_unknown_not_failed(capsys):

    events = []
    with pytest.raises(ConnectionError, match="reply lost after commit"):
        stop_agent(
            FakeRedis(events, roster_port_type="tmux", fails_on={"hdel": lambda key, field: events.append(("hdel-committed", key, field)) or (_ for _ in ()).throw(ConnectionError("reply lost after commit"))}),
            pod="acme", tenant="hq", envelope={"payload": {"agent": "dave"}},
            kill_window=lambda agent: None,
        )
    record = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert record["event"] == "stop_agent_incomplete"
    assert record["reason"] == (
        "none acknowledged; roster row removal outcome UNKNOWN after reply lost after commit"
    )
    assert events[-1] == (
        "hdel-committed", prefix("acme", "hq", resource="roster"), "dave"
    )
