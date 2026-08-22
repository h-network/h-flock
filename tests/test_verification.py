import json
from datetime import datetime, timezone

import pytest

from flock.bus import prefix
from flock.switch.service import Switch
from flock.watchdog import verification
from flock.watchdog.verification import DeliveryVerifier


class VerifyRedis:
    def __init__(self):
        self.streams = {}
        self.deleted = []
        self.hashes = {}
        self.values = {}
        self.xrange_calls = []

    def xrange(self, key, min="-", max="+"):
        self.xrange_calls.append((key, min, max))
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

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll(
        {"sme-2"}, now=NOW
    )

    assert r.streams[_key("pending.verify")] == []
    assert _key("blocked") not in r.hashes
    assert capsys.readouterr().out == ""


def test_later_output_verifies_and_drops_marker_without_log(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("delivered", "2026-08-09T12:00:00Z")]
    r.streams[_key("activity")] = [_activity("output", "2026-08-09T12:00:05Z")]
    r.hashes[_key("blocked")] = {"since": "old", "stream_id": "old"}

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({"sme-2"}, now=NOW)

    assert r.streams[_key("pending.verify")] == []
    assert _key("blocked") not in r.hashes
    assert capsys.readouterr().out == ""


def test_no_activity_after_marker_is_surfaced_and_not_retried(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("not-confirmed", "2026-08-09T12:00:00Z")]
    r.values[_key("activity.offset")] = "observed"

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll(
        {"sme-2"}, now=NOW
    )

    record = json.loads(capsys.readouterr().out)
    assert record["module"] == "switch"
    assert record["event"] == "delivery_unverified"
    assert record["stream_id"] == "not-confirmed"
    assert record["destination"] == "sme-2"
    assert record["waited"] == 20
    assert record["reason"] == (
        "not confirmed by a later CLI activity event; "
        "not retried because verification cannot distinguish loss from a landed paste"
    )
    assert "lost" not in json.dumps(record)
    assert r.streams[_key("pending.verify")] == []
    assert r.hashes[_key("blocked")] == {
        "since": "2026-08-09T12:00:00Z",
        "stream_id": "not-confirmed",
    }


def test_activity_before_marker_does_not_verify(capsys):
    r = VerifyRedis()
    r.streams[_key("pending.verify")] = [_marker("ordered", "2026-08-09T12:00:00Z")]
    r.streams[_key("activity")] = [_activity("tool", "2026-08-09T11:59:59Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll(
        {"sme-2"}, now=NOW
    )

    assert json.loads(capsys.readouterr().out)["event"] == "delivery_unverified"
    assert r.hashes[_key("blocked")]["stream_id"] == "ordered"


def test_activity_read_starts_at_earliest_eligible_marker():
    r = VerifyRedis()
    marker_time = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    r.streams[_key("activity")] = [_activity("output", "2026-08-09T12:00:01Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq")._input_times("sme-2", marker_time)

    assert r.xrange_calls == [(_key("activity"), "1786276800000-0", "+")]


def test_input_only_negative_control_flips_output_evidence(monkeypatch, capsys):
    """The widened-evidence control fails at the evidence reader's locus."""
    r = VerifyRedis()
    marker_time = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    r.streams[_key("activity")] = [_activity("output", "2026-08-09T12:00:01Z")]
    verifier = DeliveryVerifier(r, pod="acme", tenant="hq")

    assert verifier._input_times("sme-2", marker_time) == [
        datetime(2026, 8, 9, 12, 0, 1, tzinfo=timezone.utc)
    ]
    monkeypatch.setattr(verification, "VERIFICATION_ACTIVITY_KINDS", frozenset(("input",)))
    assert verifier._input_times("sme-2", marker_time) == []

    r.streams[_key("pending.verify")] = [_marker("control", "2026-08-09T12:00:00Z")]
    verifier.verify_after_seconds = 10
    verifier.poll({"sme-2"}, now=NOW)
    assert json.loads(capsys.readouterr().out)["event"] == "delivery_unverified"


def test_default_verification_window_is_two_minutes():
    assert DeliveryVerifier(object(), pod="acme", tenant="hq").verify_after_seconds == 120.0


def test_first_unverified_delivery_preserves_blocked_since_and_stream_id(capsys):
    r = VerifyRedis()
    r.values[_key("activity.offset")] = "observed"
    r.hashes[_key("blocked")] = {"since": "2026-08-09T11:00:00Z", "stream_id": "first"}
    r.streams[_key("pending.verify")] = [_marker("second", "2026-08-09T12:00:00Z")]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll(
        {"sme-2"}, now=NOW
    )

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
        "module": "switch",
        "event": "delivery_unjudged",
        "writer": "switch",
        "stream_id": "first",
        "destination": "sme-2",
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

    Pinned here because the adapter writes this key and the switch reads it —
    two lanes, two files. They briefly disagreed, each with passing tests.
    """
    assert _key("pending.verify") == "pod:acme:tenant:hq:agent:sme-2:pending.verify"


def test_switch_no_longer_runs_the_observers():
    """⚠ Activity, presence and verification moved to the watchdog.

    They observe AGENTS; the watchdog is their only consumer — it reads the
    `presence` and `blocked` hashes they write. Leaving them on the forwarding
    thread put file I/O and stream scans in the one component that must not
    block. This test is the old contract inverted: the switch must now refuse
    them rather than accept them.
    """
    switch = Switch(object(), pod="acme", tenant="hq")
    with pytest.raises(TypeError):
        switch.run(delivery_verifier=object())
    with pytest.raises(TypeError):
        switch.run(activity_tailer=object())


def test_watchdog_observers_each_get_their_own_try():
    """One failing observer must not silence the others.

    ⚠ In the switch all five shared a single try, so a throw in the first
    skipped the rest of the pass, and the record named only the exception class
    — from a five-job block, which was close to undiagnosable.
    """
    from flock.watchdog.service import run_observers

    calls, errors = [], []

    class Boom:
        def poll(self, agents):
            calls.append("boom")
            raise RuntimeError("nope")

    class Fine:
        def __init__(self, name):
            self.name = name

        def poll(self, agents):
            calls.append(self.name)

    class Recorder:
        def _error(self, job, exc):
            errors.append((job, str(exc)))

    failed = run_observers(
        Recorder(),
        (("activity", Boom()), ("presence", Fine("presence")), ("verification", Fine("verify"))),
        {"sme-2"},
    )

    assert calls == ["boom", "presence", "verify"], "a throw must not skip the rest"
    assert failed == ["activity"]
    assert errors == [("activity", "nope")], "the failing job is named, not just its class"
