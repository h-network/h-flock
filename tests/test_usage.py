"""Tests for token usage extraction, pricing, correlation, and office usage CLI."""

import json
from datetime import datetime, timezone
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

    def xrange(self, key, min="-", max="+"):
        return list(self.streams.get(key, []))

    def sadd(self, key, member):
        s = self.sets.setdefault(key, set())
        if member in s:
            return 0
        s.add(member)
        return 1

    def sismember(self, key, member):
        return member in self.sets.get(key, set())


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
