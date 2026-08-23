"""Tests for token usage extraction, pricing, correlation, and office usage CLI."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from flock.bus import prefix
from flock.office import cli
from flock.office.pricing import calculate_cost, find_model_rates, load_pricing
from flock.port.openers import mark_delivery_pending
from flock.watchdog.activity import ActivityTailer


class UsageRedis:
    def __init__(self, agents=("bus",)):
        self.values = {}
        self.streams = {}
        self.sets = {}
        self.agents = agents

    def hkeys(self, key):
        return self.agents

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def xadd(self, key, fields, *, maxlen=None, approximate=False):
        self.streams.setdefault(key, []).append((f"{len(self.streams.setdefault(key, [])) + 1}-0", fields))

    def xrange(self, key, min="-", max="+", count=None):
        entries = list(self.streams.get(key, []))
        if count is not None:
            entries = entries[:count]
        return entries

    def xrevrange(self, key, max="+", min="-", count=None):
        entries = list(reversed(self.streams.get(key, [])))
        if count is not None:
            entries = entries[:count]
        return entries

    def xdel(self, key, *ids):
        id_set = set(ids)
        if key in self.streams:
            self.streams[key] = [e for e in self.streams[key] if e[0] not in id_set]
        return len(id_set)

    def sadd(self, key, member):
        s = self.sets.setdefault(key, set())
        if member in s:
            return 0
        s.add(member)
        return 1

    def sismember(self, key, member):
        return member in self.sets.get(key, set())

    def incr(self, key):
        val = int(self.values.get(key, 0) or 0) + 1
        self.values[key] = val
        return val

    def eval(self, script, numkeys, *args):
        stream_key = args[0] if numkeys >= 1 else ""
        seen_key = args[1] if numkeys >= 2 else ""
        attributed_key = args[2] if numkeys >= 3 else ""

        request_id = args[numkeys] if len(args) > numkeys else ""
        raw_usage = args[numkeys + 1] if len(args) > numkeys + 1 else ""
        stream_id = args[numkeys + 2] if len(args) > numkeys + 2 else ""

        if "SISMEMBER" in script and request_id and seen_key:
            if self.sismember(seen_key, request_id):
                return 0

        if "XADD" in script and stream_key and raw_usage:
            self.xadd(stream_key, {"usage": raw_usage})

        if "SADD" in script:
            if request_id and seen_key:
                self.sadd(seen_key, request_id)
            if stream_id and attributed_key:
                self.sadd(attributed_key, stream_id)

        return 1


def _usage_records(r):
    key = prefix("acme", "hq", resource="usage")
    return [json.loads(entry[1]["usage"]) for entry in r.streams.get(key, [])]


def _write_lines(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_claude_fixture_extracts_four_buckets_and_exact_usd(tmp_path):
    """Verification case 1: claude fixture with known usage -> exact 4 buckets, exact USD."""
    r = UsageRedis(agents=("bus",))
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
    r = UsageRedis(agents=("bus",))
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
    r = UsageRedis(agents=("architect",))
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
    r = UsageRedis(agents=("bus",))
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
    """Codex rollout token_count event correctly parsed into 4 buckets."""
    r = UsageRedis(agents=("tmux",))
    r.values[prefix("acme", "hq", "tmux", "launch")] = "codex"
    session = tmp_path / ".codex" / "sessions" / "2026" / "08" / "rollout-tmux.jsonl"
    _write_lines(
        session,
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/tmux"}},
            {
                "type": "token_count",
                "timestamp": "2026-08-22T11:00:00.000Z",
                "payload": {
                    "request_id": "codex_req_001",
                    "model": "gpt-5-codex",
                    "input_tokens": 8100,
                    "cached_tokens": 412000,
                    "cache_write_tokens": 0,
                    "output_tokens": 12000,
                },
            },
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    records = _usage_records(r)
    assert len(records) == 1
    rec = records[0]
    assert rec["cli"] == "codex"
    assert rec["model"] == "gpt-5-codex"
    assert rec["input"] == 8100
    assert rec["cache_read"] == 412000
    assert rec["cache_write"] == 0
    assert rec["output"] == 12000

    cost, is_priced = calculate_cost(
        rec["model"],
        input_tokens=rec["input"],
        cache_read=rec["cache_read"],
        cache_write=rec["cache_write"],
        output_tokens=rec["output"],
    )
    assert is_priced is True
    # gpt-5-codex: input $2.5, cache_read $1.25, output $10 per 1M tokens
    expected_cost = (8100 * 2.5 + 412000 * 1.25 + 12000 * 10.0) / 1_000_000.0
    assert cost == pytest.approx(expected_cost)


def test_office_usage_cli_table_and_json(monkeypatch, capsys):
    """office usage CLI formats table with totals, unpriced flags, and JSON."""
    r = UsageRedis()
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
    r = UsageRedis(agents=("bus", "tmux"))
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
    r = UsageRedis(agents=("bus",))
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
    class FailingUsageRedis(UsageRedis):
        def __init__(self):
            super().__init__(agents=("bus",))
            self.fail_xadd = True

        def xadd(self, key, fields, *, maxlen=None, approximate=False):
            if self.fail_xadd and key == prefix("acme", "hq", resource="usage"):
                raise RuntimeError("Simulated Redis write failure")
            super().xadd(key, fields, maxlen=maxlen, approximate=approximate)

    r = FailingUsageRedis()
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
    r = UsageRedis(agents=("bus",))
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
