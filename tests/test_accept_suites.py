"""accept.sh's own contract: suite selection, and the verdict it records.

⚠ These exist because the first version of `run_scenario` piped a scenario into
`grep ... || true` and read `PIPESTATUS[0]`. When grep matched nothing the
`|| true` fired, PIPESTATUS became 0, and a scenario that exited 6 in silence was
recorded as a PASS. An always-green gate is the defect this whole suite exists to
catch, so the helper that decides pass from fail is itself under test.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
ACCEPT = ROOT / "container/accept.sh"


def _helpers():
    """The verdict helpers, lifted out of accept.sh so they can be exercised."""
    text = ACCEPT.read_text()
    start = text.index("INCOMPLETE=0")
    end = text.index('CONSOLE_GATE_DEADLINE_SECONDS=', start)
    return "FAILED=0\nTENANT=t\nCONTAINER=c\n" + text[start:end]


def _run(body):
    return subprocess.run(["bash", "-c", _helpers() + "\n" + body],
                          capture_output=True, text=True, cwd=ROOT)


def test_help_is_readable_and_arguments_are_checked():
    assert subprocess.run(["bash", str(ACCEPT), "--help"], capture_output=True).returncode == 0
    bad = subprocess.run(["bash", str(ACCEPT), "--nonsense"], capture_output=True)
    assert bad.returncode == 2, "an unknown argument must not be silently ignored"


def test_a_silent_failure_is_not_recorded_as_a_pass(tmp_path):
    """The regression that matters: a scenario that fails while printing nothing
    the filter matches must still be recorded as a failure."""
    script = tmp_path / "quiet.sh"
    script.write_text("#!/usr/bin/env bash\necho 'nothing the filter wants'\nexit 6\n")
    out = _run(f'run_scenario quiet "{script}"; echo "FAILED=$FAILED INCOMPLETE=$INCOMPLETE"')
    assert "RESULT quiet fail rc=6" in out.stderr, out.stderr
    assert "FAILED=1 INCOMPLETE=0" in out.stdout


def test_could_not_run_is_neither_pass_nor_fail(tmp_path):
    """100 has its own bucket. Collapsing it into pass hides a step that never
    happened; collapsing it into fail blames the product for a missing tenant."""
    script = tmp_path / "unrunnable.sh"
    script.write_text("#!/usr/bin/env bash\nexit 100\n")
    out = _run(f'run_scenario u "{script}"; echo "FAILED=$FAILED INCOMPLETE=$INCOMPLETE"')
    assert "RESULT u incomplete" in out.stderr
    assert "FAILED=0 INCOMPLETE=1" in out.stdout


def test_a_missing_scenario_is_incomplete_not_passing(tmp_path):
    out = _run(f'run_scenario gone "{tmp_path}/absent.sh"; echo "INCOMPLETE=$INCOMPLETE"')
    assert "incomplete" in out.stderr and "INCOMPLETE=1" in out.stdout


def test_a_passing_scenario_is_recorded_as_passing(tmp_path):
    script = tmp_path / "ok.sh"
    script.write_text("#!/usr/bin/env bash\necho 'RESULT inner pass'\nexit 0\n")
    out = _run(f'run_scenario ok "{script}"; echo "FAILED=$FAILED"')
    assert "RESULT ok pass" in out.stdout and "FAILED=0" in out.stdout
