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
        _line(stream_id, "kick_started", offset + 0.025, source=source),
        _line(stream_id, "received", offset + 0.030, source=source),
        _line(stream_id, "opened", offset + 0.040, source=source),
    ]


def _has(stdout: str, phrase: str) -> bool:
    """Compare ignoring column width.

    These assertions used to pin exact spacing, so widening a column to fit
    `kick_started` broke three tests that were checking alignment rather than
    behaviour. Normalise whitespace and assert on content.
    """
    squash = lambda t: " ".join(t.split())
    return squash(phrase) in squash(stdout)


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
    assert _has(result.stdout, "envelopes 21   expected 21")
    assert _has(result.stdout, "sent            21 / 21")
    assert _has(result.stdout, "sent -> popped")
    assert _has(result.stdout, "n=     21")
    assert _has(result.stdout, "steady-state (middle 80%)")


def test_missing_stage_refuses_instead_of_averaging_fixture():
    fixture = ROOT / "tests" / "fixtures" / "fabric-log-missing-stage.jsonl"

    result = _run(fixture, 2)

    assert result.returncode == 1
    assert _has(result.stdout, "received           1 / 2")
    assert _has(result.stdout, "kick_started -> received   REFUSED (n=1, needs 2)")
    assert _has(result.stdout, "received -> opened     REFUSED")


def test_source_filter_excludes_control_paths(tmp_path):
    lines = _complete("bench-1", 1) + _complete("bench-2", 2)
    lines.extend(_complete("control", 3, source="api"))
    log = tmp_path / "control.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 2)

    assert result.returncode == 0
    assert _has(result.stdout, "envelopes 2   expected 2")
