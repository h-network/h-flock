from conftest import FakeRedis, FakeRespRedis
"""Tests for token usage extraction, pricing, correlation, and office usage CLI."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from flock.bus import prefix
from flock.office import cli
from flock.office.pricing import calculate_cost, find_model_rates, load_pricing
from flock.tmux.openers import mark_delivery_pending
from flock.watchdog.activity import ActivityTailer



def _usage_records(r):
    key = prefix("acme", "hq", resource="usage")
    return [json.loads(entry[1]["usage"]) for entry in r.streams.get(key, [])]


def _write_lines(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_claude_fixture_extracts_four_buckets_and_exact_usd(tmp_path):
    """Verification case 1: claude fixture with known usage -> exact 4 buckets, exact USD."""
    r = FakeRedis(agents=("bus",))
    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "one.jsonl"
    _write_lines(
        session,
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:01.000Z",
                "message": {
                    "id": "msg_001",
                    "model": "claude-opus-4-8",
                    "content": [{"type": "text", "text": "analysis"}],
                    "usage": {
                        "input_tokens": 812,
                        "cache_read_input_tokens": 40311,
                        "cache_creation_input_tokens": 1902,
                        "output_tokens": 1204,
                    },
                },
            }
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    rec = records[0]
    assert rec["module"] == "watchdog"
    assert rec["event"] == "usage"
    assert rec["writer"] == "usage"
    assert rec["agent"] == "bus"
    assert rec["cli"] == "claude"
    assert rec["model"] == "claude-opus-4-8"
    assert rec["input"] == 812
    assert rec["cache_read"] == 40311
    assert rec["cache_write"] == 1902
    assert rec["output"] == 1204
    assert rec["ts"] == "2026-08-22T10:00:01.000Z"

    cost, is_priced = calculate_cost(
        rec["model"],
        input_tokens=rec["input"],
        cache_read=rec["cache_read"],
        cache_write=rec["cache_write"],
        output_tokens=rec["output"],
    )
    assert is_priced is True
    # claude-opus-4: input $15, cache_write $18.75, cache_read $1.50, output $75 per 1M tokens
    expected_cost = (812 * 15.0 + 40311 * 1.5 + 1902 * 18.75 + 1204 * 75.0) / 1_000_000.0
    assert abs(cost - expected_cost) < 1e-6
    assert abs(cost - 0.198609) < 1e-6


def test_duplicate_request_in_one_file_is_counted_once(tmp_path):
    """Verification case 2: the same request twice in one file is counted once (dedupe control)."""
    r = FakeRedis(agents=("bus",))
    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "one.jsonl"
    record_obj = {
        "type": "assistant",
        "timestamp": "2026-08-22T10:00:01.000Z",
        "message": {
            "id": "msg_duplicate_001",
            "model": "claude-opus-4-8",
            "content": [{"type": "text", "text": "first"}],
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 300,
                "output_tokens": 400,
            },
        },
    }
    _write_lines(session, [record_obj, record_obj])
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1, "Duplicate request ID was emitted more than once"
    assert records[0]["input"] == 100


def test_unpriced_model_is_flagged_unpriced_not_zero(tmp_path):
    """Verification case 3: a model absent from pricing.json -> unpriced, not 0.00."""
    r = FakeRedis(agents=("architect",))
    session = tmp_path / ".claude" / "projects" / "-workdir-architect" / "local.jsonl"
    _write_lines(
        session,
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:01.000Z",
                "message": {
                    "id": "msg_local_001",
                    "model": "nemotron-lightning",
                    "content": [{"type": "text", "text": "local reply"}],
                    "usage": {
                        "input_tokens": 2_100_000,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "output_tokens": 180_400,
                    },
                },
            }
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    rec = records[0]
    cost, is_priced = calculate_cost(
        rec["model"],
        input_tokens=rec["input"],
        cache_read=rec["cache_read"],
        cache_write=rec["cache_write"],
        output_tokens=rec["output"],
    )
    assert is_priced is False
    assert cost is None


def test_cache_buckets_are_not_decorative(tmp_path):
    """Verification case 4: cache buckets present -> included; control dropping them changes total."""
    full_cost, _ = calculate_cost(
        "claude-opus-4-8",
        input_tokens=10_000,
        cache_read=1_000_000,
        cache_write=50_000,
        output_tokens=5_000,
    )
    dropped_cache_cost, _ = calculate_cost(
        "claude-opus-4-8",
        input_tokens=10_000,
        cache_read=0,
        cache_write=0,
        output_tokens=5_000,
    )
    # Cache read contributes 1.50 USD and cache write contributes 0.9375 USD
    assert full_cost > dropped_cache_cost
    assert full_cost - dropped_cache_cost == pytest.approx(2.4375)


def test_correlation_joins_marker_and_omits_unattributable_usage(tmp_path):
    """Verification case 5: marker then usage -> stream_id attached; usage with no marker -> omitted."""
    r = FakeRedis(agents=("bus",))
    r.values[prefix("acme", "hq", "bus", "launch")] = "claude"

    # Delivery marker 1 at 10:00:00Z
    mark_delivery_pending(r, "acme", "hq", "bus", "stream-turn-1", correlation_id="corr-thread-1")
    # Tweak timestamp on marker in stream to 10:00:00Z
    markers_key = prefix("acme", "hq", "bus", "delivery.markers")
    r.streams[markers_key] = [
        ("1-0", {"stream_id": "stream-turn-1", "correlation_id": "corr-thread-1", "ts": "2026-08-22T10:00:00.000Z"})
    ]

    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "session.jsonl"
    _write_lines(
        session,
        [
            # Turn 1 usage at 10:00:05Z (after marker 1)
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:05.000Z",
                "message": {
                    "id": "msg_turn_1",
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            },
            # Turn 2 usage at 10:00:10Z (no new marker between turn 1 and turn 2)
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:10.000Z",
                "message": {
                    "id": "msg_turn_2",
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 200, "output_tokens": 80},
                },
            },
        ],
    )

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 2
    # First usage record joined with stream-turn-1
    assert records[0]["stream_id"] == "stream-turn-1"
    assert records[0]["correlation_id"] == "corr-thread-1"

    # Second usage record has NO stream_id (marker was already consumed)
    assert "stream_id" not in records[1]
    assert "correlation_id" not in records[1]


def test_codex_token_count_event_parsing(tmp_path):
    """⚠ THE REAL SHAPE, captured from a live codex session on 2026-08-23.

    This test used to construct `{"type": "token_count", "payload": {"input_tokens": ...}}`
    — flat, invented, and a shape codex has never written. It passed, and the
    extractor read `payload` directly, so every real record produced zeros under
    model `unknown`. A live agent logged 28,908 input tokens and h-flock recorded
    nothing.

    ⚠ `last_token_usage`, not `total_token_usage`: total is cumulative for the
    session. Two real records read total 14,373 then 28,908 while last read
    14,373 then 14,535, so summing total gives 43,281 for a session that used
    28,908.
    """
    r = FakeRedis(agents=("tmux",))
    r.values[prefix("acme", "hq", "tmux", "launch")] = "codex"
    session = tmp_path / ".codex" / "sessions" / "2026" / "08" / "rollout-tmux.jsonl"
    _write_lines(
        session,
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/tmux"}},
            {
                "type": "event_msg",
                "timestamp": "2026-08-23T11:58:46.354Z",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 28908, "cached_input_tokens": 22016,
                            "cache_write_input_tokens": 0, "output_tokens": 134,
                        },
                        "last_token_usage": {
                            "input_tokens": 14535, "cached_input_tokens": 11008,
                            "cache_write_input_tokens": 0, "output_tokens": 14,
                        },
                    },
                },
            },
        ],
    )

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()

    records = _usage_records(r)
    assert len(records) == 1
    rec = records[0]
    assert rec["input"] == 14535, "took the cumulative total instead of the turn"
    assert rec["cache_read"] == 11008
    assert rec["output"] == 14
    assert rec["cli"] == "codex"


def test_a_codex_token_count_with_no_tokens_is_not_a_usage_record(tmp_path):
    """⚠ codex writes these during startup and teardown.

    Measured: an agent that logged in and was retired produced nine records,
    every one all-zero under model `unknown` — which reads in a cost table
    exactly like an agent that ran and cost nothing.
    """
    r = FakeRedis(agents=("tmux",))
    r.values[prefix("acme", "hq", "tmux", "launch")] = "codex"
    session = tmp_path / ".codex" / "sessions" / "2026" / "08" / "rollout-tmux.jsonl"
    _write_lines(
        session,
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/tmux"}},
            {
                "type": "event_msg",
                "timestamp": "2026-08-23T11:58:20.000Z",
                "payload": {"type": "token_count", "info": {"last_token_usage": {
                    "input_tokens": 0, "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0, "output_tokens": 0}}},
            },
        ],
    )

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()
    assert _usage_records(r) == []

def test_office_usage_cli_table_and_json(monkeypatch, capsys):
    """office usage CLI formats table with totals, unpriced flags, and JSON."""
    r = FakeRespRedis()
    usage_key = prefix("acme", "hq", resource="usage")
    r.streams[usage_key] = [
        (
            "1-0",
            {
                "usage": json.dumps(
                    {
                        "agent": "bus",
                        "cli": "claude",
                        "model": "claude-opus-4-8",
                        "input": 12400,
                        "cache_read": 1200000,
                        "cache_write": 48100,
                        "output": 31200,
                        "ts": "2026-08-22T10:00:00.000Z",
                    }
                )
            },
        ),
        (
            "2-0",
            {
                "usage": json.dumps(
                    {
                        "agent": "tmux",
                        "cli": "codex",
                        "model": "gpt-5-codex",
                        "input": 8100,
                        "cache_read": 412000,
                        "cache_write": 0,
                        "output": 12000,
                        "ts": "2026-08-22T10:05:00.000Z",
                    }
                )
            },
        ),
        (
            "3-0",
            {
                "usage": json.dumps(
                    {
                        "agent": "architect",
                        "cli": "claude",
                        "model": "nemotron-lightning",
                        "input": 2100000,
                        "cache_read": 0,
                        "cache_write": 0,
                        "output": 180400,
                        "ts": "2026-08-22T10:10:00.000Z",
                    }
                )
            },
        ),
    ]

    monkeypatch.setattr(cli, "_context", lambda: (r, "acme", "hq", "bus"))

    # Test table output
    cli.main(["usage"])
    out = capsys.readouterr().out
    assert "agent" in out
    assert "bus" in out
    assert "claude-opus-4-8" in out
    assert "12.4k" in out
    assert "1.20M" in out
    assert "48.1k" in out
    assert "31.2k" in out
    assert "gpt-5-codex" in out
    assert "nemotron-lightning" in out
    assert "unpriced" in out

    # Test JSON output
    cli.main(["usage", "--json"])
    json_out = json.loads(capsys.readouterr().out)
    assert "rows" in json_out
    assert len(json_out["rows"]) == 3
    assert json_out["total_usd"] > 0

    # Test agent filter
    cli.main(["usage", "--agent", "bus", "--json"])
    bus_json = json.loads(capsys.readouterr().out)
    assert len(bus_json["rows"]) == 1
    assert bus_json["rows"][0]["agent"] == "bus"


def test_same_request_id_across_different_agents_is_not_suppressed(tmp_path):
    """Different agents with identical request IDs must both emit records independently."""
    r = FakeRedis(agents=("bus", "tmux"))
    bus_session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "session.jsonl"
    tmux_session = tmp_path / ".claude" / "projects" / "-workdir-tmux" / "session.jsonl"

    shared_record = {
        "type": "assistant",
        "timestamp": "2026-08-22T10:00:01.000Z",
        "message": {
            "id": "shared_request_id_123",
            "model": "claude-opus-4-8",
            "usage": {"input_tokens": 150, "output_tokens": 75},
        },
    }
    _write_lines(bus_session, [shared_record])
    _write_lines(tmux_session, [shared_record])

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 2, f"Expected 2 records (1 per agent), got {len(records)}"
    agents = {rec["agent"] for rec in records}
    assert agents == {"bus", "tmux"}


def test_truly_empty_marker_history_omits_correlation(tmp_path):
    """An agent with zero delivery markers omits stream_id and correlation_id cleanly."""
    r = FakeRedis(agents=("bus",))
    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "session.jsonl"
    _write_lines(
        session,
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:01.000Z",
                "message": {
                    "id": "msg_nomarker_001",
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 200, "output_tokens": 100},
                },
            }
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    assert "stream_id" not in records[0]
    assert "correlation_id" not in records[0]


def test_emission_failure_does_not_prematurely_commit_seen_request(tmp_path):
    """An emission failure in Redis does not mark request as seen, allowing recovery."""

    r = FakeRedis(agents=("bus",), fail_xadd=True)
    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "session.jsonl"
    _write_lines(
        session,
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-22T10:00:01.000Z",
                "message": {
                    "id": "msg_recoverable_001",
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            }
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)

    # First poll fails during xadd
    tailer.poll()
    assert len(_usage_records(r)) == 0
    assert "msg_recoverable_001" not in tailer._seen_requests["bus"]
    seen_key = prefix("acme", "hq", "bus", "usage.requests")
    assert not r.sismember(seen_key, "msg_recoverable_001")

    # Second poll with Redis recovered and fresh tailer (simulating restart replay from 0)
    r.fail_xadd = False
    r.values.pop(prefix("acme", "hq", "bus", "activity.offset"), None)
    restart_tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    restart_tailer.poll()
    assert len(_usage_records(r)) == 1
    assert "msg_recoverable_001" in restart_tailer._seen_requests["bus"]
    assert r.sismember(seen_key, "msg_recoverable_001")


def test_explicit_flock_pricing_file_missing_or_malformed_fails_loudly(tmp_path, monkeypatch):
    """An operator-specified FLOCK_PRICING_FILE must fail loudly on missing/bad JSON."""
    missing_path = tmp_path / "nonexistent_pricing.json"
    monkeypatch.setenv("FLOCK_PRICING_FILE", str(missing_path))
    with pytest.raises(FileNotFoundError, match="FLOCK_PRICING_FILE specified but not found"):
        load_pricing()

    bad_json = tmp_path / "bad_pricing.json"
    bad_json.write_text("{not valid json: 123}")
    monkeypatch.setenv("FLOCK_PRICING_FILE", str(bad_json))
    with pytest.raises(ValueError, match="FLOCK_PRICING_FILE contains invalid JSON"):
        load_pricing()


def test_office_usage_runs_against_resp_redis_client(monkeypatch, capsys):
    """office usage must execute successfully over the real flock.bus.resp.Redis client."""
    import io
    from unittest.mock import patch
    from flock.bus.resp import Redis as RespRedis

    class FakeSocket:
        def __init__(self, replies):
            self.reader = io.BytesIO(replies)
            self.requests = []

        def makefile(self, mode):
            return self.reader

        def sendall(self, request):
            self.requests.append(request)

    record_json = json.dumps({
        "agent": "bus",
        "cli": "claude",
        "model": "claude-opus-4-8",
        "input": 12400,
        "cache_read": 1200000,
        "cache_write": 48100,
        "output": 31200,
        "ts": "2026-08-22T10:00:00.000Z",
    }).encode("utf-8")

    resp_reply = (
        b"*1\r\n"
        b"*2\r\n"
        b"$3\r\n1-0\r\n"
        b"*2\r\n"
        b"$5\r\nusage\r\n"
        + f"${len(record_json)}\r\n".encode()
        + record_json
        + b"\r\n"
    )

    sock = FakeSocket(resp_reply)
    with patch("flock.bus.resp.socket.create_connection", return_value=sock):
        resp_client = RespRedis.from_url("redis://127.0.0.1:6379/0")

    monkeypatch.setattr(cli, "_context", lambda: (resp_client, "acme", "hq", "bus"))

    cli.main(["usage"])
    out = capsys.readouterr().out
    assert "bus" in out
    assert "claude-opus-4-8" in out
    assert "12.4k" in out
    assert "1.20M" in out
    assert "48.1k" in out
    assert "31.2k" in out


def test_lua_script_atomic_claim_and_replay_dedupe_on_real_redis(tmp_path):
    """Verify _EMIT_USAGE_LUA atomic claim, emission, and deduplication on real redis-server."""
    import shutil
    import socket
    import subprocess
    import time
    import uuid
    import redis

    redis_bin = shutil.which("redis-server") or "/usr/bin/redis-server"
    if not Path(redis_bin).exists():
        pytest.fail(f"redis-server binary not found at {redis_bin} - real redis test is mandatory")

    # Find free port and spin redis-server on temp port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [redis_bin, "--port", str(port), "--dir", str(tmp_path), "--save", "", "--appendonly", "no"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ready = False
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1) as sock:
                    sock.sendall(b"*1\r\n$4\r\nPING\r\n")
                    if sock.recv(1024).startswith(b"+PONG"):
                        ready = True
                        break
            except Exception:
                time.sleep(0.05)

        if not ready:
            pytest.fail(f"Could not connect to real redis-server on port {port}")

        r = redis.Redis(host="127.0.0.1", port=port, db=0, decode_responses=True)
        pod = f"pod-{uuid.uuid4().hex[:6]}"
        tenant = f"ten-{uuid.uuid4().hex[:6]}"
        tailer = ActivityTailer(r, pod=pod, tenant=tenant, home_root=tmp_path)

        req_id = "req_atomic_001"
        usage_info = {
            "cli": "claude",
            "model": "claude-opus-4-8",
            "input": 100,
            "cache_read": 0,
            "cache_write": 0,
            "output": 50,
            "request_id": req_id,
        }

        # First emission: emits record and claims request ID in Redis
        tailer._emit_usage("bus", "2026-08-22T10:00:00.000Z", usage_info)
        stream_key = prefix(pod, tenant, resource="usage")
        seen_key = prefix(pod, tenant, "bus", "usage.requests")
        assert r.xlen(stream_key) == 1
        assert r.sismember(seen_key, req_id)

        # Clear in-memory seen requests to simulate tailer restart / new pass
        tailer._seen_requests["bus"].clear()

        # Second emission: Lua atomic claim check returns 0 and suppresses duplicate emission
        tailer._emit_usage("bus", "2026-08-22T10:00:01.000Z", usage_info)
        assert r.xlen(stream_key) == 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_unresolved_markers_correlated_within_ceiling(tmp_path):
    """Pending markers are correlated with usage within the documented ceiling."""
    r = FakeRedis(agents=("bus",))
    r.values[prefix("acme", "hq", "bus", "launch")] = "claude"

    # Add markers within ceiling
    for i in range(1, 51):
        mark_delivery_pending(
            r,
            "acme",
            "hq",
            "bus",
            f"stream-turn-{i:03d}",
            correlation_id=f"corr-turn-{i:03d}",
        )

    # ⚠ RELATIVE TO THE MARKERS, NEVER A LITERAL DATE. The markers above are
    # stamped `datetime.now()` by mark_delivery_pending, and the join asks for
    # the first usage record AFTER a marker. A hardcoded timestamp is later than
    # `now` only until `now` overtakes it: this test carried
    # "2026-08-22T23:59:59.000Z", was written at 23:56, and passed for four
    # minutes before failing every run thereafter — correctly, because the usage
    # record had become older than the marker it was supposed to follow.
    after_markers = (
        datetime.now(timezone.utc) + timedelta(seconds=1)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    session = tmp_path / ".claude" / "projects" / "-workdir-bus" / "session.jsonl"
    _write_lines(
        session,
        [
            {
                "type": "assistant",
                "timestamp": after_markers,
                "message": {
                    "id": "msg_marker_preserved",
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            }
        ],
    )

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    assert records[0]["stream_id"] == "stream-turn-050"
    assert records[0]["correlation_id"] == "corr-turn-050"


def test_codex_captured_session_fixture_model_and_tokens(tmp_path):
    """Build 88: parse live captured codex rollout fixture tests/fixtures/codex-session-captured.jsonl.

    Proves:
    1. Model is resolved from turn_context ('gpt-5.6-sol'), not 'unknown'.
    2. Uses last_token_usage per turn, NEVER cumulative total_token_usage.
    3. Rate limits (used_percent, plan_type, resets_at) are extracted into usage records.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "codex-session-captured.jsonl"
    assert fixture_path.exists(), f"Fixture file {fixture_path} must exist"

    # Set up session file in agent sme-2's codex session dir
    session_file = tmp_path / ".codex" / "sessions" / "rollout-captured.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_bytes(fixture_path.read_bytes())

    r = FakeRedis(agents=("sme-2",))
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "codex"

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer._tail("sme-2", session_file, "codex")

    records = _usage_records(r)
    # The fixture contains 4 token_count records (ordinals 17, 141, 288, 414)
    assert len(records) == 4

    for rec in records:
        assert rec["cli"] == "codex"
        assert rec["model"] == "gpt-5.6-sol"
        assert "rate_limits" in rec
        assert rec["rate_limits"]["primary"]["used_percent"] == 18.0
        assert rec["rate_limits"]["plan_type"] == "prolite"
        assert rec["rate_limits"]["primary"]["resets_at"] == 1787813260

    # Record 1 (ordinal 17): last and total are both 14,132
    assert records[0]["input"] == 14132
    assert records[0]["cache_read"] == 11008
    assert records[0]["output"] == 113

    # Record 2 (ordinal 141): last is 64,831 vs total 533,066
    assert records[1]["input"] == 64831
    assert records[1]["input"] != 533066
    assert records[1]["cache_read"] == 64256
    assert records[1]["output"] == 1282

    # Record 3 (ordinal 288): last is 80,177 vs total 1,810,189
    assert records[2]["input"] == 80177
    assert records[2]["input"] != 1810189
    assert records[2]["cache_read"] == 79616
    assert records[2]["output"] == 634

    # Record 4 (ordinal 414): last is 111,751 vs total 3,332,258
    assert records[3]["input"] == 111751
    assert records[3]["input"] != 3332258
    assert records[3]["cache_read"] == 109312
    assert records[3]["output"] == 71

    # Total input across the 4 turns
    total_input = sum(rec["input"] for rec in records)
    assert total_input == 270891
    assert total_input != (14132 + 533066 + 1810189 + 3332258)


def test_codex_mid_session_model_change(tmp_path):
    """Build 88 §1: mid-session model change in turn_context is followed rather than averaged over."""
    session_file = tmp_path / ".codex" / "sessions" / "rollout-multi-model.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)

    records_data = [
        {"timestamp": "2026-08-23T14:00:00.000Z", "ordinal": 0, "type": "session_meta", "payload": {"cwd": "/workdir/sme-1"}},
        {"timestamp": "2026-08-23T14:00:01.000Z", "ordinal": 1, "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
        {
            "timestamp": "2026-08-23T14:00:02.000Z",
            "ordinal": 2,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 1000, "output_tokens": 100}},
            },
        },
        # Mid-session model switch to gpt-5-codex
        {"timestamp": "2026-08-23T14:05:00.000Z", "ordinal": 10, "type": "turn_context", "payload": {"model": "gpt-5-codex"}},
        {
            "timestamp": "2026-08-23T14:05:05.000Z",
            "ordinal": 15,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 2000, "output_tokens": 200}},
            },
        },
    ]
    _write_lines(session_file, records_data)

    r = FakeRedis(agents=("sme-1",))
    r.values[prefix("acme", "hq", "sme-1", "launch")] = "codex"

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 2
    assert records[0]["model"] == "gpt-5.6-sol"
    assert records[0]["input"] == 1000
    assert records[1]["model"] == "gpt-5-codex"
    assert records[1]["input"] == 2000


def test_codex_session_meta_fallback_model(tmp_path):
    """Build 88 §1: session_meta base_instructions provenance model serves as fallback."""
    session_file = tmp_path / ".codex" / "sessions" / "rollout-meta.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)

    records_data = [
        {
            "timestamp": "2026-08-23T14:00:00.000Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {
                "cwd": "/workdir/sme-1",
                "base_instructions": {"provenance": {"type": "model", "model": "gpt-5-codex"}},
            },
        },
        {
            "timestamp": "2026-08-23T14:00:02.000Z",
            "ordinal": 2,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 500, "output_tokens": 50}},
            },
        },
    ]
    _write_lines(session_file, records_data)

    r = FakeRedis(agents=("sme-1",))
    r.values[prefix("acme", "hq", "sme-1", "launch")] = "codex"

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    assert records[0]["model"] == "gpt-5-codex"
    assert records[0]["input"] == 500


def test_office_usage_surfaces_codex_rate_limits(monkeypatch, capsys):
    """Build 88 §4: office usage surfaces rate limits (used_percent and plan_type)."""
    r = FakeRespRedis(agents=("sme-2",))
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "codex"

    usage_key = prefix("acme", "hq", resource="usage")
    usage_entry = json.dumps({
        "agent": "sme-2",
        "cli": "codex",
        "model": "gpt-5.6-sol",
        "input": 111751,
        "cache_read": 109312,
        "cache_write": 0,
        "output": 71,
        "ts": "2026-08-23T14:20:00.000Z",
        "rate_limits": {
            "limit_id": "codex",
            "primary": {"used_percent": 18.0, "window_minutes": 10080, "resets_at": 1787813260},
            "plan_type": "prolite",
        },
    })
    r.xadd(usage_key, {"usage": usage_entry})

    monkeypatch.setattr(cli, "_context", lambda: (r, "acme", "hq", "sme-2"))

    cli.main(["usage"])
    out = capsys.readouterr().out
    assert "sme-2" in out
    assert "codex" in out
    assert "gpt-5.6-sol" in out
    assert "18% (prolite)" in out

    cli.main(["usage", "--json"])
    json_out = json.loads(capsys.readouterr().out)
    assert len(json_out["rows"]) == 1
    assert json_out["rows"][0]["rate_limits"]["primary"]["used_percent"] == 18.0
    assert json_out["rows"][0]["rate_limits"]["plan_type"] == "prolite"


def test_office_usage_names_agy_agent_not_collected(monkeypatch, capsys):
    """Build 105 §2: office usage names agy agents as not collected rather than omitting or zeroing."""
    r = FakeRespRedis(agents=("architect", "backend"))
    r.values[prefix("acme", "hq", "architect", "launch")] = "agy"
    r.values[prefix("acme", "hq", "backend", "launch")] = "claude"

    usage_key = prefix("acme", "hq", resource="usage")
    backend_usage = json.dumps({
        "agent": "backend",
        "cli": "claude",
        "model": "claude-opus-4",
        "input": 10000,
        "cache_read": 0,
        "cache_write": 0,
        "output": 1000,
        "ts": "2026-08-23T14:00:00.000Z",
    })
    r.xadd(usage_key, {"usage": backend_usage})

    monkeypatch.setattr(cli, "_context", lambda: (r, "acme", "hq", "backend"))

    cli.main(["usage"])
    out = capsys.readouterr().out
    assert "architect" in out
    assert "agy" in out
    assert "not collected" in out
    assert "backend" in out

    cli.main(["usage", "--json"])
    json_out = json.loads(capsys.readouterr().out)
    architect_rows = [r for r in json_out["rows"] if r["agent"] == "architect"]
    assert len(architect_rows) == 1
    assert architect_rows[0]["cli"] == "agy"
    assert architect_rows[0]["model"] == "not collected"
    assert architect_rows[0]["collected"] is False
    assert architect_rows[0]["unpriced"] is True
    assert architect_rows[0]["usd"] is None


def test_agy_uncollected_documentation_bounded_claims():
    """CONTRACTS.md states exact bounded claims for agy transcripts.

    agy writes no token counts h-flock can read, and the claim about its
    transcripts is deliberately bounded — we know where they live, we do not
    collect them, and we have not verified whether they carry counts. Each
    assertion below pins one clause of that, so a later edit cannot quietly
    widen it into a claim we never tested.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent

    contracts_norm = " ".join((root / "docs" / "CONTRACTS.md").read_text(encoding="utf-8").split())
    assert "not collected (agy)" in contracts_norm
    assert 'model: "not collected"' in contracts_norm
    assert '"collected": false' in contracts_norm
    assert "brain/<id>/.system_generated/logs/" in contracts_norm
    assert "h-flock does not collect it" in contracts_norm
    assert "whether those transcripts carry token counts is unverified" in contracts_norm



def test_codex_session_rotation_resets_model(tmp_path):
    """Rotation control: rotating to a new rollout with session_meta resets model rather than retaining previous rollout's model."""
    import time
    sessions_dir = tmp_path / ".codex" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Rollout 1 with turn_context model-old
    rollout_old = sessions_dir / "rollout-old.jsonl"
    _write_lines(
        rollout_old,
        [
            {"timestamp": "2026-08-23T14:00:00.000Z", "ordinal": 0, "type": "session_meta", "payload": {"cwd": "/workdir/sme-1"}},
            {"timestamp": "2026-08-23T14:00:01.000Z", "ordinal": 1, "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {
                "timestamp": "2026-08-23T14:00:02.000Z",
                "ordinal": 2,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 100, "output_tokens": 10}},
                },
            },
        ],
    )

    r = FakeRedis(agents=("sme-1",))
    r.values[prefix("acme", "hq", "sme-1", "launch")] = "codex"

    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    assert records[0]["model"] == "gpt-5.6-sol"

    # Rollout 2 with session_meta fallback model-new (newer mtime)
    time.sleep(0.01)
    rollout_new = sessions_dir / "rollout-new.jsonl"
    _write_lines(
        rollout_new,
        [
            {
                "timestamp": "2026-08-23T14:10:00.000Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "cwd": "/workdir/sme-1",
                    "base_instructions": {"provenance": {"type": "model", "model": "gpt-5-codex"}},
                },
            },
            {
                "timestamp": "2026-08-23T14:10:02.000Z",
                "ordinal": 1,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 200, "output_tokens": 20}},
                },
            },
        ],
    )

    tailer.poll()
    records = _usage_records(r)
    assert len(records) == 2
    # Second record MUST be gpt-5-codex from the new session, NOT gpt-5.6-sol from the old session
    assert records[1]["model"] == "gpt-5-codex"


def test_codex_restart_at_mid_session_offset_recovers_model(tmp_path):
    """Restart control: watchdog restart at persisted offset recovers model from pre-offset turn_context."""
    sessions_dir = tmp_path / ".codex" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / "rollout-resume.jsonl"

    # Initial turn_context + first token_count
    _write_lines(
        rollout,
        [
            {"timestamp": "2026-08-23T14:00:00.000Z", "ordinal": 0, "type": "session_meta", "payload": {"cwd": "/workdir/sme-1"}},
            {"timestamp": "2026-08-23T14:00:01.000Z", "ordinal": 1, "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {
                "timestamp": "2026-08-23T14:00:02.000Z",
                "ordinal": 2,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 100, "output_tokens": 10}},
                },
            },
        ],
    )

    r = FakeRedis(agents=("sme-1",))
    r.values[prefix("acme", "hq", "sme-1", "launch")] = "codex"

    # First tailer pass processes records and commits offset
    tailer1 = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer1.poll()
    assert len(_usage_records(r)) == 1

    # Append new turn after offset without re-emitting turn_context
    with rollout.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps({
                "timestamp": "2026-08-23T14:05:00.000Z",
                "ordinal": 3,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 300, "output_tokens": 30}},
                },
            }) + "\n"
        )

    # Fresh tailer instance simulating watchdog restart with empty in-memory state
    tailer2 = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer2.poll()

    records = _usage_records(r)
    assert len(records) == 2
    # Second usage record MUST recover gpt-5.6-sol from before offset, NOT 'unknown'
    assert records[1]["model"] == "gpt-5.6-sol"
    assert records[1]["input"] == 300


def test_codex_session_ownership_rejects_arbitrary_cwd(tmp_path):
    """Ownership control: _codex_session_belongs_to strictly accepts /workdir/{agent} and rejects arbitrary cwd."""
    p_valid = tmp_path / "valid.jsonl"
    _write_lines(p_valid, [
        {"type": "session_meta", "payload": {"cwd": "/workdir/sme-2"}},
    ])
    assert ActivityTailer._codex_session_belongs_to(p_valid, "sme-2") is True
    assert ActivityTailer._codex_session_belongs_to(p_valid, "other") is False

    p_arbitrary = tmp_path / "arbitrary.jsonl"
    _write_lines(p_arbitrary, [
        {"type": "session_meta", "payload": {"cwd": "/tmp/sme-2"}},
    ])
    assert ActivityTailer._codex_session_belongs_to(p_arbitrary, "sme-2") is False


