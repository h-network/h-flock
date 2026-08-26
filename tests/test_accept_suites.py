"""accept.sh's own contract: suite selection, and the verdict it records.

⚠ These exist because the first version of `run_scenario` piped a scenario into
`grep ... || true` and read `PIPESTATUS[0]`. When grep matched nothing the
`|| true` fired, PIPESTATUS became 0, and a scenario that exited 6 in silence was
recorded as a PASS. An always-green gate is the defect this whole suite exists to
catch, so the helper that decides pass from fail is itself under test.
"""
import subprocess
import os
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
    help_result = subprocess.run(["bash", str(ACCEPT), "--help"], capture_output=True, text=True)
    assert help_result.returncode == 0
    assert "--tmux" in help_result.stdout
    assert "real agents in real panes" in help_result.stdout
    assert "tmux-nemotron is manual integration only" in help_result.stdout
    assert "do NOT exercise a successful paste_text" in help_result.stdout
    assert "tmux-window-loss targets a missing window" in help_result.stdout
    assert "tmux-boundary sends nothing" in help_result.stdout
    assert "tmux-concurrent-hire uses the control-plane opener" in help_result.stdout
    assert "delivery_unverified" in help_result.stdout
    assert "not run analyse-verification" in help_result.stdout
    bad = subprocess.run(["bash", str(ACCEPT), "--nonsense"], capture_output=True)
    assert bad.returncode == 2, "an unknown argument must not be silently ignored"


def test_scenario_exports_selected_api_port(tmp_path):
    """The standalone exec must receive the door selected by --api-port."""
    fake_bash = tmp_path / "bash"
    fake_bash.write_text("#!/bin/sh\nprintf 'TENANT=%s API_PORT=%s\\n' \"$TENANT\" \"$API_PORT\"\n")
    fake_bash.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(ACCEPT), "--scenario", "tmux-window-loss", "--tenant", "chosen", "--api-port", "9456"],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0
    assert result.stdout == "TENANT=chosen API_PORT=9456\n"


def test_scenario_refuses_missing_api_port():
    result = subprocess.run(
        ["/bin/bash", str(ACCEPT), "--scenario", "tmux-window-loss", "--tenant", "chosen"],
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "API_PORT"},
    )
    assert result.returncode == 100
    assert "RESULT tmux-window-loss incomplete reason=api_port_required" in result.stderr


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


def test_the_image_tag_names_the_commit_it_was_built_from():
    """An image tagged `latest` cannot tell you whether it matches the source, so
    reusing it would silently test stale code. Tagging by commit makes the
    image's EXISTENCE the proof, which is what lets a run skip the build safely.

    ⚠ A dirty tree is never cached: an image tagged with a commit it does not
    contain would be exactly the lie this avoids.
    """
    lib = ROOT / "container/flock-image.sh"

    def tag(extra=""):
        out = subprocess.run(["bash", "-c", f'. "{lib}"\n{extra}\nflock_image_tag'],
                             capture_output=True, text=True, cwd=ROOT)
        return out.stdout.strip()

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, cwd=ROOT).stdout.strip()

    if dirty:
        assert tag() == "h-flock:dirty", "an unnameable tree must not be cached"
    else:
        assert tag() == f"h-flock:{sha}", "a clean tree is named by its commit"


def test_a_dirty_tree_always_rebuilds_and_force_overrides():
    """The two cases where a present image must not be trusted."""
    lib = ROOT / "container/flock-image.sh"

    def flag(env):
        out = subprocess.run(["bash", "-c", f'. "{lib}"\nflock_build_flag'],
                             capture_output=True, text=True, cwd=ROOT, env={**__import__("os").environ, **env})
        return out.stdout.strip()

    assert flag({"FLOCK_IMAGE": "h-flock:dirty"}) == "--build", "dirty is never reused"
    assert flag({"FLOCK_IMAGE": "h-flock:whatever", "FLOCK_FORCE_BUILD": "1"}) == "--build"
