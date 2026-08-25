import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "container" / "scenarios" / "analyse-run.py"


def _line(stream_id, event, seconds, *, source="bench-1", writer="port"):
    return json.dumps(
        {
            "ts": f"2026-08-15T00:00:{seconds:06.3f}Z",
            "module": "test",
            "event": event,
            "stream_id": stream_id,
            "source": source,
            "destination": "bench-2",
            "writer": writer,
        }
    )


def _complete(stream_id, offset, *, source="bench-1", writer="port"):
    return [
        _line(stream_id, "sent", offset, source=source, writer=writer),
        _line(stream_id, "popped", offset + 0.010, source=source, writer=writer),
        _line(stream_id, "forwarded", offset + 0.020, source=source, writer=writer),
        _line(stream_id, "kick_started", offset + 0.025, source=source, writer=writer),
        _line(stream_id, "received", offset + 0.030, source=source, writer=writer),
        _line(stream_id, "opened", offset + 0.040, source=source, writer=writer),
    ]


def _has(stdout: str, phrase: str) -> bool:
    """Compare ignoring column width.

    These assertions used to pin exact spacing, so widening a column to fit
    `kick_started` broke three tests that were checking alignment rather than
    behaviour. Normalise whitespace and assert on content.
    """
    squash = lambda t: " ".join(t.split())
    return squash(phrase) in squash(stdout)


def _run(path, expected, *extra):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(path),
            "--expect",
            str(expected),
            "--source-prefix",
            "bench-",
            *extra,
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

    assert result.returncode == 100
    assert _has(result.stdout, "received           1 / 2")
    assert _has(result.stdout, "kick_started -> received   REFUSED (n=1, needs 2)")
    assert _has(result.stdout, "received -> opened     REFUSED")


def test_indeterminate_forward_is_its_own_refused_bucket(tmp_path):
    lines = _complete("unknown-forward", 1)
    lines[2] = _line("unknown-forward", "forward_unknown", 1.020)
    log = tmp_path / "forward-unknown.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 1)

    assert result.returncode == 100
    assert _has(result.stdout, "indeterminate forwards 1")
    assert _has(
        result.stdout,
        "forward_unknown 1 ⚠ REFUSED — write outcome is neither forwarded nor lost",
    )
    assert _has(result.stdout, "forwarded 0 / 1")


def test_legacy_attempt_record_refuses_cross_version_analysis(tmp_path):
    log = tmp_path / "legacy.jsonl"
    log.write_text(_line("legacy", "forward_failed", 1) + "\n")

    result = _run(log, 1)

    assert result.returncode == 4
    assert "REFUSED: 1 legacy *_failed attempt records" in result.stdout


def test_source_filter_excludes_control_paths(tmp_path):
    lines = _complete("bench-1", 1) + _complete("bench-2", 2)
    lines.extend(_complete("control", 3, source="api"))
    log = tmp_path / "control.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 2)

    assert result.returncode == 0
    assert _has(result.stdout, "envelopes 2   expected 2")


def test_writer_census_refuses_synthetic_and_exact_exclusion_restores_run(tmp_path):
    lines = _complete("real", 1, writer="port")
    lines.extend(_complete("synthetic", 2, writer="bench-send"))
    log = tmp_path / "writers.jsonl"
    log.write_text("\n".join(lines) + "\n")

    refused = _run(log, 2)
    assert refused.returncode == 100
    assert _has(refused.stdout, "writers: bench-send=6 port=6")
    assert "bench-send was not explicitly expected" in refused.stdout

    excluded = _run(log, 1, "--exclude-writer", "bench-send")
    assert excluded.returncode == 0
    assert _has(excluded.stdout, "writers: port=6")
    assert "bench-send=" not in excluded.stdout


def test_expected_synthetic_writer_requires_exact_count(tmp_path):
    lines = _complete("synthetic", 1, writer="bench-send")
    log = tmp_path / "synthetic.jsonl"
    log.write_text("\n".join(lines) + "\n")

    accepted = _run(log, 1, "--expect-writer", "bench-send=6")
    wrong = _run(log, 1, "--expect-writer", "bench-send=5")

    assert accepted.returncode == 0
    assert wrong.returncode == 1
    assert "bench-send count 6 != expected 5" in wrong.stdout


def test_default_writer_census_matches_legacy_module_fallback(tmp_path):
    current_lines = _complete("current", 1, writer="test")
    legacy_lines = []
    for line in current_lines:
        record = json.loads(line)
        record.pop("writer")
        legacy_lines.append(json.dumps(record))
    current = tmp_path / "current.jsonl"
    legacy = tmp_path / "legacy.jsonl"
    current.write_text("\n".join(current_lines) + "\n")
    legacy.write_text("\n".join(legacy_lines) + "\n")

    current_result = _run(current, 1)
    legacy_result = _run(legacy, 1)

    assert current_result.returncode == legacy_result.returncode == 0
    assert current_result.stdout == legacy_result.stdout
    assert _has(current_result.stdout, "writers: test=6")


def test_writer_include_is_repeatable_and_exact(tmp_path):
    lines = _complete("port", 1, writer="port")
    lines.extend(_complete("switch", 2, writer="switch"))
    lines.extend(_complete("watchdog", 3, writer="watchdog"))
    log = tmp_path / "writers.jsonl"
    log.write_text("\n".join(lines) + "\n")

    result = _run(log, 2, "--writer", "port", "--writer", "switch")

    assert result.returncode == 0
    assert _has(result.stdout, "writers: port=6 switch=6")
    assert "watchdog=" not in result.stdout


def test_bench_writer_is_set_before_flock_logging_is_imported():
    for name, writer in (("bench-send.py", "bench-send"), ("bench-port.py", "bench-port")):
        text = (ROOT / "container" / "scenarios" / name).read_text()
        assignment = f'os.environ["FLOCK_WRITER"] = "{writer}"'
        assert text.index(assignment) < text.index("from flock.bus")
