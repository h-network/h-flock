import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "container" / "scenarios" / "analyse-run.py"


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


def _complete(stream_id, offset, *, source="bench-1"):
    return [
        _line(stream_id, "sent", offset, source=source),
        _line(stream_id, "popped", offset + 0.010, source=source),
        _line(stream_id, "forwarded", offset + 0.020, source=source),
        _line(stream_id, "received", offset + 0.030, source=source),
        _line(stream_id, "opened", offset + 0.040, source=source),
    ]


def _run(path, expected):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(path),
            "--expect",
            str(expected),
            "--source-prefix",
            "bench-",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_complete_log_reports_every_stage_and_timing(tmp_path):
    lines = []
    for index in range(21):
        lines.extend(_complete(f"s-{index}", index))
    log = tmp_path / "complete.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 21)

    assert result.returncode == 0
    assert "envelopes 21   expected 21" in result.stdout
    assert "sent            21 / 21" in result.stdout
    assert "sent -> popped" in result.stdout
    assert "n=     21" in result.stdout
    assert "steady-state (middle 80%)" in result.stdout


def test_missing_stage_refuses_instead_of_averaging_fixture():
    fixture = ROOT / "tests" / "fixtures" / "fabric-log-missing-stage.jsonl"

    result = _run(fixture, 2)

    assert result.returncode == 1
    assert "received         1 / 2" in result.stdout
    assert "forwarded -> received   REFUSED (n=1, needs 2)" in result.stdout
    assert "received -> opened     REFUSED" in result.stdout


def test_source_filter_excludes_control_paths(tmp_path):
    lines = _complete("bench-1", 1) + _complete("bench-2", 2)
    lines.extend(_complete("control", 3, source="api"))
    log = tmp_path / "control.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 2)

    assert result.returncode == 0
    assert "envelopes 2   expected 2" in result.stdout
