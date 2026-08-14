import importlib.util
import json
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / "container" / "scenarios" / "analyse-run.py"
SPEC = importlib.util.spec_from_file_location("fabric_log_metrics", PATH)
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def _line(stream_id, event, seconds, *, source="bench-1"):
    return json.dumps(
        {
            "ts": f"2026-08-15T00:00:{seconds:06.3f}Z",
            "module": "test",
            "event": event,
            "stream_id": stream_id,
            "source": source,
            "destination": "bench-2",
        }
    )


def _complete(stream_id, offset):
    return [
        _line(stream_id, "sent", offset),
        _line(stream_id, "popped", offset + 0.010),
        _line(stream_id, "forwarded", offset + 0.020),
        _line(stream_id, "received", offset + 0.030),
        _line(stream_id, "opened", offset + 0.040),
    ]


def test_analyse_joins_stages_and_reports_middle_window():
    lines = []
    for index in range(11):
        lines.extend(_complete(f"s-{index}", index))
    result = metrics.analyse(lines, expected=11, source_prefix="bench-")
    assert result["delivered"] == 11
    assert result["dead_lettered"] == 0
    assert result["steady_count"] == 9
    assert result["steady_seconds"] == pytest.approx(8.0)
    assert result["steady_rate"] == pytest.approx(1.125)
    for values in result["stage_ms"].values():
        assert values["n"] == 11
        assert values["p50"] == pytest.approx(10.0)
        assert values["p95"] == pytest.approx(10.0)
    assert result["end_to_end_ms"]["n"] == 11
    assert result["end_to_end_ms"]["p50"] == pytest.approx(40)
    assert result["end_to_end_ms"]["p95"] == pytest.approx(40)
    assert result["end_to_end_ms"]["p99"] == pytest.approx(40)


def test_missing_stage_refuses_metrics_instead_of_averaging():
    lines = _complete("complete", 1)
    lines.extend(_complete("missing", 2))
    lines = [line for line in lines if not ('"stream_id": "missing"' in line and '"event": "received"' in line)]
    with pytest.raises(ValueError, match=r"refusing stage metrics: 1 stream\(s\) incomplete.*received"):
        metrics.analyse(lines, expected=2, source_prefix="bench-")


def test_source_filter_excludes_control_paths():
    lines = _complete("bench-1", 1) + _complete("bench-2", 2)
    lines.extend(_complete("control", 3))
    lines = [line.replace('"source": "bench-1"', '"source": "api"') if '"stream_id": "control"' in line else line for line in lines]
    result = metrics.analyse(lines, expected=2, source_prefix="bench-")
    assert result["joined_paths"] == 2
