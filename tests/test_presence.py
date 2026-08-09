import json
from datetime import datetime, timezone

from flock.bus import prefix
from flock.router.presence import PresenceSampler


class PresenceRedis:
    def __init__(self):
        self.streams = {}
        self.hashes = {}
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def xrevrange(self, key, max="+", min="-", count=None):
        return list(reversed(self.streams.get(key, [])))[:count]

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, key, mapping):
        self.hashes[key] = mapping


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


def test_agy_is_unknown_even_when_an_old_activity_stream_exists():
    r = PresenceRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    r.streams[prefix("acme", "hq", "sme-2", "activity")] = [
        _activity("sme-2", "2026-08-09T12:00:59Z", "1-0")
    ]
    PresenceSampler(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)
    assert _presence(r, "sme-2")["state"] == "unknown"
    assert _presence(r, "sme-2")["last_activity"] == ""
