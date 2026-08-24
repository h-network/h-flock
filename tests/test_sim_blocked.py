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
from flock.watchdog.verification import DeliveryVerifier
from conftest import FakeRedis as MockSimRedis


def _agent_key(agent, resource):
    return prefix("acme", "hq", agent, resource)


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
    off_key = _agent_key(agent, "activity.offset")

    r.streams[m_key] = [("1-0", {"stream_id": "wedged-1", "ts": "2026-08-09T12:00:00Z"})]
    r.values[off_key] = "observed"

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({agent}, now=NOW)

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "delivery_unverified"
    assert record["destination"] == agent
    assert record["stream_id"] == "wedged-1"
    assert r.hashes[b_key] == {"since": "2026-08-09T12:00:00Z", "stream_id": "wedged-1"}
    assert r.streams[m_key] == []


def test_trust_picker_unverified_blocked(capsys):
    """Case 2: trust_picker (unseeded trust).

    CLI is at a trust dialog picker. Delivered text is swallowed, so no input activity event is written.
    Verifier marks delivery unverified and sets blocked key.
    """
    r = MockSimRedis()
    agent = "sim-trust"
    m_key = _agent_key(agent, "pending.verify")
    b_key = _agent_key(agent, "blocked")
    off_key = _agent_key(agent, "activity.offset")

    r.streams[m_key] = [("2-0", {"stream_id": "trust-1", "ts": "2026-08-09T12:00:00Z"})]
    r.values[off_key] = "observed"

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({agent}, now=NOW)

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "delivery_unverified"
    assert record["destination"] == agent
    assert record["stream_id"] == "trust-1"
    assert r.hashes[b_key] == {"since": "2026-08-09T12:00:00Z", "stream_id": "trust-1"}
    assert r.streams[m_key] == []


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

    r.streams[m_key] = [("3-0", {"stream_id": "nologin-1", "ts": "2026-08-09T12:00:00Z"})]
    r.streams[a_key] = [
        ("3-1", {"event": json.dumps({"v": 1, "agent": agent, "ts": "2026-08-09T12:00:01Z", "kind": "input"})})
    ]

    DeliveryVerifier(r, pod="acme", tenant="hq", verify_after_seconds=10).poll({agent}, now=NOW)

    assert capsys.readouterr().out == ""
    assert b_key not in r.hashes
    assert r.streams[m_key] == []
