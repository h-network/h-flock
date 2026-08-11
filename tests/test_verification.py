import json
from datetime import datetime, timezone

import pytest

from flock.bus import prefix
from flock.router.service import Router
from flock.router.verification import DeliveryVerifier


class VerifyRedis:
    def __init__(self):
        self.streams = {}
        self.deleted = []
        self.hashes = {}
        self.values = {}

    def xrange(self, key, min="-", max="+"):
        return list(self.streams.get(key, []))

    def xdel(self, key, entry_id):
        self.deleted.append((key, entry_id))
        self.streams[key] = [entry for entry in self.streams.get(key, []) if entry[0] != entry_id]
        return 1

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)

    def delete(self, key):
        self.hashes.pop(key, None)

    def exists(self, key):
        return int(key in self.values or key in self.streams or key in self.hashes)

    def xlen(self, key):
        return len(self.streams.get(key, []))


def _key(resource):
    return prefix("acme", "hq", "sme-2", resource)


def _marker(stream_id, timestamp, entry_id=b"1-0"):
    return entry_id, {b"stream_id": stream_id.encode(), b"ts": timestamp.encode()}


def _activity(kind, timestamp, entry_id=b"2-0"):
    event = json.dumps({"v": 1, "agent": "sme-2", "ts": timestamp, "kind": kind})
    return entry_id, {b"event": event.encode()}


NOW = datetime(2026, 8, 9, 12, 0, 20, tzinfo=timezone.utc)


def test_later_input_verifies_and_drops_marker_without_log(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("delivered", "2026-08-09T12:00:00Z")]
    r.streams[_key("activity")] = [_activity("input", "2026-08-09T12:00:01Z")]
    r.hashes[_key("blocked")] = {"since": "old", "stream_id": "old"}

    DeliveryVerifier(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)

    assert r.streams[_key("pending.verify")] == []
    assert _key("blocked") not in r.hashes
    assert capsys.readouterr().out == ""


def test_missing_later_input_is_surfaced_and_not_retried(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("not-confirmed", "2026-08-09T12:00:00Z")]
    r.streams[_key("activity")] = [
        _activity("input", "2026-08-09T11:59:59Z", b"1-0"),
        _activity("output", "2026-08-09T12:00:05Z", b"2-0"),
    ]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({"sme-2"}, now=NOW)

    record = json.loads(capsys.readouterr().out)
    assert record["module"] == "router"
    assert record["event"] == "delivery_unverified"
    assert record["stream_id"] == "not-confirmed"
    assert record["recipient"] == "sme-2"
    assert record["waited"] == 20
    assert record["reason"] == (
        "not confirmed by a later input activity event; "
        "not retried because verification cannot distinguish loss from a landed paste"
    )
    assert "lost" not in json.dumps(record)
    assert r.streams[_key("pending.verify")] == []
    assert r.hashes[_key("blocked")] == {
        "since": "2026-08-09T12:00:00Z",
        "stream_id": "not-confirmed",
    }


def test_first_unverified_delivery_preserves_blocked_since_and_stream_id(capsys):
    r = VerifyRedis()
    r.values[_key("activity.offset")] = "observed"
    r.hashes[_key("blocked")] = {"since": "2026-08-09T11:00:00Z", "stream_id": "first"}
    r.streams[_key("pending.verify")] = [_marker("second", "2026-08-09T12:00:00Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq").poll({"sme-2"}, now=NOW)

    assert r.hashes[_key("blocked")] == {"since": "2026-08-09T11:00:00Z", "stream_id": "first"}
    capsys.readouterr()


def test_first_delivery_without_activity_history_is_dropped_unjudged(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("first", "2026-08-09T12:00:00Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll(
        {"sme-2"}, now=NOW
    )

    record = json.loads(capsys.readouterr().out)
    assert record == {
        "ts": record["ts"],
        "module": "router",
        "event": "delivery_unjudged",
        "stream_id": "first",
        "recipient": "sme-2",
        "reason": "agent has no activity history; first delivery is not judged",
        "waited": 20,
    }
    assert r.streams[_key("pending.verify")] == []
    assert _key("blocked") not in r.hashes


def test_marker_younger_than_threshold_remains_pending(capsys):
    r = VerifyRedis()
    marker = _marker("young", "2026-08-09T12:00:15Z")
    r.streams[_key("pending.verify")] = [marker]
    r.streams[_key("activity")] = [_activity("input", "2026-08-09T12:00:16Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({"sme-2"}, now=NOW)

    assert r.streams[_key("pending.verify")] == [marker]
    assert r.deleted == []
    assert capsys.readouterr().out == ""


def test_pending_verify_key_follows_the_dotted_resource_convention():
    """Resources compose with a dot, like tasks.todo and activity.offset.

    Pinned here because the adapter writes this key and the router reads it —
    two lanes, two files. They briefly disagreed, each with passing tests.
    """
    assert _key("pending.verify") == "pod:acme:tenant:hq:agent:sme-2:pending.verify"


def test_router_tails_then_verifies_same_roster_in_existing_pass():
    events = []
    agents = {"architect", "sme-2"}

    class Tailer:
        def poll(self, observed_agents):
            events.append(("tail", observed_agents))

    class Verifier:
        def poll(self, observed_agents):
            events.append(("verify", observed_agents))

    router = Router(object(), pod="acme", tenant="hq")
    router._agents = lambda: agents
    router.step = lambda timeout=None: (_ for _ in ()).throw(StopIteration)

    with pytest.raises(StopIteration):
        router.run(Tailer(), delivery_verifier=Verifier())

    assert events == [("tail", agents), ("verify", agents)]
