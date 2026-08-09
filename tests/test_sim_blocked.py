"""Unit tests for Build 30 failure simulator cases.

Simulates the three failure modes against DeliveryVerifier:
  1. wedged_process          (SIGSTOP CLI -> no input activity -> blocked set)
  2. trust_picker            (unseeded trust -> text swallowed -> blocked set)
  3. login_prompt_known_gap  (unauthenticated CLI -> input recorded -> verified, blocked NOT set [known gap])
"""

import json
from datetime import datetime, timezone

import pytest

from flock.bus import prefix
from flock.router.verification import DeliveryVerifier


class MockSimRedis:
    def __init__(self):
        self.streams = {}
        self.hashes = {}
        self.values = {}
        self.deleted = []

    def xrange(self, key, min="-", max="+"):
        return list(self.streams.get(key, []))

    def xdel(self, key, entry_id):
        self.deleted.append((key, entry_id))
        self.streams[key] = [e for e in self.streams.get(key, []) if e[0] != entry_id]
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


def _agent_key(agent, resource):
    return prefix("acme", "hq", agent, resource)


def _marker(stream_id, ts, entry_id=b"100-0"):
    return entry_id, {b"stream_id": stream_id.encode(), b"ts": ts.encode()}


def _input_event(agent, ts, entry_id=b"200-0"):
    event = json.dumps({"v": 1, "agent": agent, "ts": ts, "kind": "input"})
    return entry_id, {b"event": event.encode()}


NOW = datetime(2026, 8, 9, 12, 0, 30, tzinfo=timezone.utc)


def test_wedged_process_unverified_blocked(capsys):
    """Case 1: wedged_process (SIGSTOP CLI).

    CLI is stopped, so no input activity event is generated after the marker.
    Verifier marks delivery unverified and sets blocked key.
    """
    r = MockSimRedis()
    agent = "sim-wedged"
    m_key = _agent_key(agent, "pending.verify")
    a_key = _agent_key(agent, "activity")
    b_key = _agent_key(agent, "blocked")

    # Marker written at 12:00:00Z, current time is 12:00:30Z (>10s threshold)
    r.streams[m_key] = [_marker("stream-wedged-1", "2026-08-09T12:00:00Z")]
    r.values[_agent_key(agent, "activity.offset")] = "observed"
    # No activity input events after marker
    r.streams[a_key] = []

    verifier = DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10)
    verifier.poll({agent}, now=NOW)

    assert r.streams[m_key] == []
    assert b_key in r.hashes
    assert r.hashes[b_key]["stream_id"] == "stream-wedged-1"
    assert r.hashes[b_key]["since"] == "2026-08-09T12:00:00Z"

    log_output = capsys.readouterr().out
    assert "delivery_unverified" in log_output
    assert "sim-wedged" in log_output


def test_trust_picker_unverified_blocked(capsys):
    """Case 2: trust_picker (unseeded trust).

    CLI is at a trust dialog picker. Delivered text is swallowed, so no input activity event is written.
    Verifier marks delivery unverified and sets blocked key.
    """
    r = MockSimRedis()
    agent = "sim-trust"
    m_key = _agent_key(agent, "pending.verify")
    a_key = _agent_key(agent, "activity")
    b_key = _agent_key(agent, "blocked")

    r.streams[m_key] = [_marker("stream-trust-1", "2026-08-09T12:00:00Z")]
    # Only old activity before marker
    r.streams[a_key] = [_input_event(agent, "2026-08-09T11:59:50Z")]

    verifier = DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10)
    verifier.poll({agent}, now=NOW)

    assert r.streams[m_key] == []
    assert b_key in r.hashes
    assert r.hashes[b_key]["stream_id"] == "stream-trust-1"

    log_output = capsys.readouterr().out
    assert "delivery_unverified" in log_output


def test_login_prompt_known_gap_verified(capsys):
    """Case 3: login_prompt_known_gap (unauthenticated CLI).

    ⚠ KNOWN GAP: A CLI at a login prompt records input into its log file without acting on it.
    Because an input activity event IS recorded, the verifier treats the delivery as verified
    and blocked is NOT set, even though the CLI remains unauthenticated.
    """
    r = MockSimRedis()
    agent = "sim-nologin"
    m_key = _agent_key(agent, "pending.verify")
    a_key = _agent_key(agent, "activity")
    b_key = _agent_key(agent, "blocked")

    r.streams[m_key] = [_marker("stream-nologin-1", "2026-08-09T12:00:00Z")]
    # Input event recorded at login prompt AFTER marker
    r.streams[a_key] = [_input_event(agent, "2026-08-09T12:00:05Z")]

    verifier = DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10)
    verifier.poll({agent}, now=NOW)

    # Delivery is verified -> marker cleared, blocked NOT set
    assert r.streams[m_key] == []
    assert b_key not in r.hashes
    assert capsys.readouterr().out == ""
