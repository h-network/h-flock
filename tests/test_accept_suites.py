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
import re
import shutil

import pytest

ROOT = Path(__file__).parents[1]
ACCEPT = ROOT / "container/accept.sh"

AUXILIARY_FLAGS = {
    "--tenant": ["--tenant", "matrix-tenant"],
    "--api-port": ["--api-port", "19456"],
    "--session-port": ["--session-port", "19457"],
    "--console-port": ["--console-port", "19458"],
    "--keep": ["--keep"],
    "--no-console": ["--no-console"],
    "--log": ["--log", "/dev/null"],
    "--aof-dir": ["--aof-dir", "/tmp/matrix-aof"],
    "--expect-writer": ["--expect-writer", "bench-send=1"],
}

# This is the parser/dispatch contract, not a live-behaviour matrix. Invalid
# pairs must stop at rc2; valid standalone pairs are proved below with child
# shims that expose the argv or environment they actually received.
MODES = {
    "bare": ([], {"--tenant", "--api-port", "--session-port", "--console-port", "--keep", "--no-console"}),
    "core": (["--core"], {"--tenant", "--api-port", "--session-port", "--console-port", "--keep", "--no-console"}),
    "fault": (["--fault"], {"--tenant", "--api-port", "--session-port", "--keep"}),
    "api": (["--api"], {"--tenant", "--api-port", "--session-port", "--keep"}),
    "all": (["--all"], {"--tenant", "--api-port", "--session-port", "--console-port", "--keep", "--no-console"}),
    "analyse-run": (["--scenario", "analyse-run"], {"--log", "--expect-writer"}),
    "analyse-verification": (["--scenario", "analyse-verification"], {"--log"}),
    "analyse-v4-aof": (["--scenario", "analyse-v4-aof"], {"--aof-dir"}),
    "tmux-boundary": (["--scenario", "tmux-boundary"], {"--tenant"}),
    "tmux-concurrent-hire": (["--scenario", "tmux-concurrent-hire"], {"--tenant", "--api-port"}),
    "tmux-window-loss": (["--scenario", "tmux-window-loss"], {"--tenant", "--api-port"}),
}


def _clean_env(**extra):
    env = {key: value for key, value in os.environ.items() if key not in {"TENANT", "API_PORT"}}
    env.update(extra)
    return env


def _accept(*args, env=None):
    return subprocess.run(
        ["/bin/bash", str(ACCEPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env or _clean_env(),
    )


def _executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def _shimmed_suite_root(tmp_path):
    """A no-Docker accept root whose children all return clean verdicts."""
    root = tmp_path / "repo"
    tools = root / "tools"
    (root / "container").mkdir(parents=True)
    (root / "clients/web").mkdir(parents=True)
    tools.mkdir()
    shutil.copy2(ACCEPT, root / "container/accept.sh")
    shutil.copytree(ROOT / "container/scenarios", root / "container/scenarios")
    (root / "container/plumbing-check.sh").write_text("")
    (root / "clients/web/server.py").write_text("")
    (root / "clients/web/flow-check.py").write_text("")
    _executable(
        root / "setup.sh",
        """#!/bin/sh
answers="$(cat)"
api_port="$(printf '%s\n' "$answers" | sed -n '13p')"
printf 'API_ENABLED=1\nAPI_PORT=%s\nAPI_TOKEN=matrix-token\n' "$api_port" >container/.env
touch "$MATRIX_STATE/created"
printf 'healthy\n'
""",
    )
    _executable(
        tools / "docker",
        """#!/bin/sh
case "$1 $2" in
  'ps -aq') [ -f "$MATRIX_STATE/created" ] && printf 'container-id\n' ;;
  'inspect --format') printf 'healthy\n' ;;
  'exec h-flock-'*) printf 'architect\n' ;;
esac
""",
    )
    _executable(
        tools / "bash",
        """#!/bin/sh
case "$1" in
  container/plumbing-check.sh) printf 'PASS=1 FAIL=0\n' ;;
  container/scenarios/*) printf 'RESULT shim pass\n' ;;
  *) exit 2 ;;
esac
""",
    )
    _executable(tools / "curl", "#!/bin/sh\nprintf '200'\n")
    _executable(tools / "openssl", "#!/bin/sh\nprintf 'matrix-secret\n'\n")
    _executable(tools / "python3", "#!/bin/sh\nexit 0\n")
    return root, _clean_env(
        PATH=f"{tools}:{os.environ['PATH']}",
        MATRIX_STATE=str(tmp_path),
    )


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


def test_matrix_inventory_covers_every_parsed_auxiliary_flag():
    parsed = set(re.findall(r"^    (--[a-z-]+)\)", ACCEPT.read_text(), re.MULTILINE))
    selectors = {"--core", "--fault", "--api", "--all", "--scenario"}
    assert parsed - selectors == set(AUXILIARY_FLAGS)


INVALID_MODE_FLAG_PAIRS = [
    (mode, flag)
    for mode, (_, allowed) in MODES.items()
    for flag in AUXILIARY_FLAGS
    if flag not in allowed
]


@pytest.mark.parametrize("mode,flag", INVALID_MODE_FLAG_PAIRS)
@pytest.mark.parametrize("flag_first", [False, True])
def test_incompatible_flag_mode_pairs_refuse_before_dispatch(mode, flag, flag_first):
    mode_args, _ = MODES[mode]
    flag_args = AUXILIARY_FLAGS[flag]
    args = [*flag_args, *mode_args] if flag_first else [*mode_args, *flag_args]
    result = _accept(*args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert f"accept: {flag} is incompatible" in result.stderr


@pytest.mark.parametrize("flag", ["--tenant", "--api-port", "--session-port", "--console-port",
                                  "--scenario", "--log", "--aof-dir", "--expect-writer"])
def test_value_flags_without_values_are_bad_arguments(flag):
    result = _accept(flag)
    assert result.returncode == 2
    assert f"accept: {flag} requires a value" in result.stderr


def test_value_flag_does_not_consume_the_next_flag_as_its_value():
    result = _accept("--tenant", "--api")
    assert result.returncode == 2
    assert "accept: --tenant requires a value" in result.stderr


def test_scenario_and_suite_selection_cannot_be_combined():
    result = _accept("--fault", "--scenario", "analyse-verification", "--log", "/dev/null")
    assert result.returncode == 2
    assert "suite selector is incompatible" in result.stderr


def test_console_port_is_not_silently_ignored_when_console_is_disabled():
    result = _accept("--core", "--no-console", "--console-port", "19458")
    assert result.returncode == 2
    assert "--console-port is incompatible" in result.stderr


SUITE_ALLOWED_PAIRS = [
    (mode, flag)
    for mode, (_, allowed) in MODES.items()
    if mode in {"bare", "core", "fault", "api", "all"}
    for flag in allowed
]


@pytest.mark.parametrize("mode,flag", SUITE_ALLOWED_PAIRS)
def test_compatible_suite_pairs_get_past_parser_validation(tmp_path, mode, flag):
    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/bin/sh\nprintf 'existing-project-resource\\n'\n")
    fake_docker.chmod(0o755)
    mode_args, _ = MODES[mode]
    result = _accept(
        *mode_args, *AUXILIARY_FLAGS[flag],
        env=_clean_env(PATH=f"{tmp_path}:{os.environ['PATH']}"),
    )
    assert result.returncode == 2
    assert "is incompatible" not in result.stderr
    assert "refusing existing compose project" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--core"],
        ["--all"],
        ["--core", "--no-console"],
        ["--all", "--keep"],
        ["--tenant", "documented-example", "--keep"],
    ],
    ids=["bare", "core", "all", "core-no-console", "all-keep", "documented-ssh"],
)
def test_repository_suite_invocations_still_pass_with_clean_children(tmp_path, args):
    root, env = _shimmed_suite_root(tmp_path)
    result = subprocess.run(
        ["/bin/bash", "container/accept.sh", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "scenario,args,expected",
    [
        ("analyse-run", ["--log", "/capture/log", "--expect-writer", "bench-send=2"],
         "container/scenarios/analyse-run.py|/capture/log|--expect-writer|bench-send=2"),
        ("analyse-verification", ["--log", "/capture/log"],
         "container/scenarios/analyse-verification.py|/capture/log"),
        ("analyse-v4-aof", ["--aof-dir", "/capture/aof"],
         "container/scenarios/analyse-v4-aof.py|/capture/aof"),
    ],
)
def test_analyser_flags_reach_the_selected_child(tmp_path, scenario, args, expected):
    fake_python = tmp_path / "python3"
    fake_python.write_text("#!/bin/sh\n(IFS='|'; printf '%s\\n' \"$*\")\n")
    fake_python.chmod(0o755)
    result = _accept(
        "--scenario", scenario, *args,
        env=_clean_env(PATH=f"{tmp_path}:{os.environ['PATH']}"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "scenario,args,expected",
    [
        ("tmux-boundary", ["--tenant", "chosen"], "TENANT=chosen API_PORT=8080"),
        ("tmux-concurrent-hire", ["--tenant", "chosen", "--api-port", "19456"],
         "TENANT=chosen API_PORT=19456"),
        ("tmux-window-loss", ["--tenant", "chosen", "--api-port", "19456"],
         "TENANT=chosen API_PORT=19456"),
    ],
)
def test_tmux_flags_reach_the_selected_child(tmp_path, scenario, args, expected):
    fake_bash = tmp_path / "bash"
    fake_bash.write_text("#!/bin/sh\nprintf 'TENANT=%s API_PORT=%s\\n' \"$TENANT\" \"$API_PORT\"\n")
    fake_bash.chmod(0o755)
    result = _accept(
        "--scenario", scenario, *args,
        env=_clean_env(PATH=f"{tmp_path}:{os.environ['PATH']}"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == expected


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


def test_paste_negative_control_reaches_scenario(tmp_path):
    fake_bash = tmp_path / "bash"
    fake_bash.write_text("#!/bin/sh\nprintf 'args=%s\\n' \"$*\"\n")
    fake_bash.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(ACCEPT), "--scenario", "tmux-paste-delivery", "--tenant", "chosen", "--break-delivery"],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0
    assert result.stdout == "args=container/scenarios/tmux-paste-delivery.sh --break-delivery\n"


def test_paste_negative_control_cannot_be_silently_mistargeted():
    for command in (
        ["/bin/bash", str(ACCEPT), "--break-delivery"],
        ["/bin/bash", str(ACCEPT), "--scenario", "analyse-verification", "--log", "/dev/null", "--break-delivery"],
    ):
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 2
        assert "--break-delivery requires --scenario tmux-paste-delivery" in result.stderr


def test_paste_delivery_observes_the_pane_before_trusting_opened():
    scenario = (ROOT / "container/scenarios/tmux-paste-delivery.sh").read_text()
    assert scenario.count("capture-pane -p -J") == 2
    assert "stale_message_marker" in scenario
    pane_check = scenario.index('expect "exact message text is present in destination pane"')
    opened_check = scenario.index('expect "custody reports opened after pane paste"')
    assert pane_check < opened_check
    assert "`opened` is secondary custody" in scenario


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
