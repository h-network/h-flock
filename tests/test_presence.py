from conftest import FakeRedis as PresenceRedis
import json
from datetime import datetime, timezone

from flock.bus import prefix
from flock.watchdog.presence import PresenceSampler



def _activity(agent, timestamp, entry_id):
    event = json.dumps({"v": 1, "agent": agent, "ts": timestamp, "kind": "tool", "tool": "Read"})
    return entry_id, {"event": event}


def _presence(r, agent):
    return r.hashes[prefix("acme", "hq", agent, "presence")]


NOW = datetime(2026, 8, 9, 12, 1, 0, tzinfo=timezone.utc)


def test_presence_samples_working_idle_and_unknown():
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "working", "launch")] = "claude"
    r.values[prefix("acme", "hq", "idle", "launch")] = "codex"
    r.streams[prefix("acme", "hq", "working", "activity")] = [
        _activity("working", "2026-08-09T12:00:50Z", "1-0")
    ]
    r.streams[prefix("acme", "hq", "idle", "activity")] = [
        _activity("idle", "2026-08-09T11:59:00Z", "1-0")
    ]

    PresenceSampler(r, pod="acme", tenant="hq", working_seconds=30).poll(
        {"working", "idle", "unknown"}, now=NOW
    )

    assert _presence(r, "working") == {
        "state": "working",
        "since": "2026-08-09T12:00:50.000Z",
        "last_activity": "2026-08-09T12:00:50.000Z",
    }
    assert _presence(r, "idle") == {
        "state": "idle",
        "since": "2026-08-09T11:59:30.000Z",
        "last_activity": "2026-08-09T11:59:00.000Z",
    }
    assert _presence(r, "unknown") == {
        "state": "unknown",
        "since": "2026-08-09T12:01:00.000Z",
        "last_activity": "",
    }


def test_presence_since_changes_only_on_state_transition():
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "claude"
    key = prefix("acme", "hq", "sme-2", "activity")
    r.streams[key] = [_activity("sme-2", "2026-08-09T12:00:50Z", "1-0")]
    sampler = PresenceSampler(r, pod="acme", tenant="hq", working_seconds=30)
    sampler.poll({"sme-2"}, now=NOW)

    r.streams[key].append(_activity("sme-2", "2026-08-09T12:01:05Z", "2-0"))
    sampler.poll({"sme-2"}, now=datetime(2026, 8, 9, 12, 1, 10, tzinfo=timezone.utc))

    assert _presence(r, "sme-2")["since"] == "2026-08-09T12:00:50.000Z"
    assert _presence(r, "sme-2")["last_activity"] == "2026-08-09T12:01:05.000Z"


def test_malformed_latest_activity_falls_back_to_last_valid_event():
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "claude"
    key = prefix("acme", "hq", "sme-2", "activity")
    r.streams[key] = [
        _activity("sme-2", "2026-08-09T12:00:50Z", "1-0"),
        ("2-0", {"event": "not-json"}),
    ]
    PresenceSampler(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)
    assert _presence(r, "sme-2")["state"] == "working"
    assert r.reverse_counts == [10]


def test_agy_reads_working_from_its_own_activity_stream():
    """agy joined `_tailable`'s CLI set once history.jsonl was confirmed live
    and wired into ActivityTailer — an agy agent now reads real presence off
    the same activity stream claude/codex populate, not a permanent `unknown`.
    """
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    r.streams[prefix("acme", "hq", "sme-2", "activity")] = [
        _activity("sme-2", "2026-08-09T12:00:59Z", "1-0")
    ]
    PresenceSampler(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)
    assert _presence(r, "sme-2")["state"] == "working"
    assert _presence(r, "sme-2")["last_activity"] == "2026-08-09T12:00:59.000Z"


def test_agy_with_no_activity_yet_is_idle_not_unknown():
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    PresenceSampler(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)
    assert _presence(r, "sme-2")["state"] == "idle"


def test_a_fresh_tailable_agent_is_idle_not_unknown():
    """A freshly hired claude agent has no activity yet — that is idle.

    ⚠ Only an agent whose activity could never be seen is unknown. Without the
    distinction a ready agent and a bare shell give a client the same answer,
    and it cannot tell "nothing seen yet" from "nothing to see".
    """
    r = PresenceRedis()
    r.values["pod:acme:tenant:hq:agent:fresh:launch"] = "claude"   # tailable, no activity
    # 'shell' has no launch key at all

    PresenceSampler(r, pod="acme", tenant="hq").poll({"fresh", "shell"})

    assert r.hashes["pod:acme:tenant:hq:agent:fresh:presence"]["state"] == "idle"
    assert r.hashes["pod:acme:tenant:hq:agent:shell:presence"]["state"] == "unknown"
