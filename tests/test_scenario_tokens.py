import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCENARIOS_DIR = ROOT / 'container' / 'scenarios'
API_SCENARIOS = [
    SCENARIOS_DIR / 'api-auth-and-limits.sh',
    SCENARIOS_DIR / 'api-concurrency-and-time.sh',
    SCENARIOS_DIR / 'api-session-and-log-privacy.sh',
]


def test_api_scenarios_syntax_valid():
    """Build 116: bash -n passes on all three API scenario scripts."""
    for script in API_SCENARIOS:
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error in {script}: {result.stderr}"


def test_api_scenarios_refuse_to_run_without_a_token():
    """No token means the run COULD NOT HAPPEN, which is not the same as failing.

    ⚠ These scripts exit 100 rather than 1, and the distinction is load-bearing:
    `accept.sh` counts a 1 as a broken framework and a 100 as a step that never
    reached a verdict. A missing token is the second, and reporting it as the
    first would make an unrunnable suite look like a defect in the product.
    """
    clean_env = {k: v for k, v in os.environ.items() if k != "API_TOKEN"}
    clean_env["CONTAINER"] = "no-such-container"
    for script in API_SCENARIOS:
        result = subprocess.run(
            ['bash', str(script)], capture_output=True, text=True, env=clean_env,
        )
        assert result.returncode == 100, f"{script.name} exited {result.returncode}, expected 100"
        assert "incomplete reason=no_api_token" in result.stderr, result.stderr


def test_no_hardcoded_token_in_scenarios():
    """Build 116: no hardcoded API token constant remains in container/scenarios."""
    target_token = "7af3ad5eb2cac57e9ca97a953908ef09"
    for script in SCENARIOS_DIR.glob('*.sh'):
        content = script.read_text(encoding='utf-8')
        assert target_token not in content, f"Hardcoded token found in {script}"


def test_api_scenario_discovers_its_token_through_docker(tmp_path):
    """The token comes from the running container, not a constant in the file.

    ⚠ These scripts used to fall back to a hardcoded 32-hex token committed to a
    PUBLIC repo. They now ask the container. This proves the discovery path runs:
    with a docker that answers only `printenv API_TOKEN`, the script gets past
    the token stage and starts checking. It then fails every HTTP check, because
    there is no door behind the shim — and failing is the correct outcome for a
    script that can no longer pass by not looking.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_bin = bin_dir / "docker"
    docker_bin.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"exec\" ] && [ \"$3\" = \"printenv\" ] && [ \"$4\" = \"API_TOKEN\" ]; then\n"
        "    echo \"discovered-test-token-7788\"\n"
        "else\n"
        "    exit 1\n"
        "fi\n"
    )
    docker_bin.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k != "API_TOKEN"}
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CONTAINER"] = "h-flock-api-lab-tenant-1"
    env["API_HOST_URL"] = "http://127.0.0.1:9"          # nothing listens here

    script = ROOT / "container/scenarios/api-auth-and-limits.sh"
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)

    assert result.returncode != 100, "a token WAS discovered, so this is not could-not-run"
    assert "incomplete" not in result.stderr
    assert result.returncode > 0, "with no door behind the shim every check must fail"
    assert "RESULT api-auth fail" in result.stderr


def test_the_shared_scenario_lib_can_actually_fail():
    """Control for `_lib.sh`: the three api-* scripts it backs used to print what
    they observed and compare nothing, so they always exited 0. Each verdict path
    is exercised here, because a helper that cannot report failure would make
    every script built on it a recorder again."""
    import subprocess
    from pathlib import Path

    lib = Path(__file__).parents[1] / "container/scenarios/_lib.sh"

    def run(body):
        return subprocess.run(["bash", "-c", f'. "{lib}"\n{body}'], capture_output=True, text=True)

    passing = run('expect "same" a a\nfinish demo')
    assert passing.returncode == 0 and "RESULT demo pass" in passing.stdout

    failing = run('expect "differs" a b\nexpect "also differs" 1 2\nfinish demo')
    assert failing.returncode == 2, "the exit code is the count of failed checks"
    assert "RESULT demo fail failed=2" in failing.stderr

    unrunnable = run('incomplete demo no_token\nfinish demo')
    assert unrunnable.returncode == 100, "could-not-run is neither pass nor fail"
    assert "RESULT demo incomplete reason=no_token" in unrunnable.stderr


def test_bus_v4_scenario_heredocs_reach_the_container():
    """A `python3 -` producer needs docker exec -i or it reads EOF and sends zero frames."""
    for name, expected_calls in (
        ("bus-retained-egress.sh", 2),
        ("bus-broadcast-storm.sh", 1),
    ):
        content = (SCENARIOS_DIR / name).read_text(encoding="utf-8")
        assert 'dxi() { docker exec -i "$C" "$@"; }' in content
        assert content.count("dxi python3 -") == expected_calls
