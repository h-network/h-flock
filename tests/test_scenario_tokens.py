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


def test_api_scenarios_fail_loudly_when_token_empty():
    """Build 116: scenarios refuse to run with empty token when container is not running."""
    clean_env = {k: v for k, v in os.environ.items() if k != "API_TOKEN"}
    for script in API_SCENARIOS:
        result = subprocess.run(
            ['bash', str(script)],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert result.returncode == 1, f"Expected {script.name} to exit 1, got {result.returncode}"
        assert "Error: API_TOKEN is empty" in result.stderr


def test_no_hardcoded_token_in_scenarios():
    """Build 116: no hardcoded API token constant remains in container/scenarios."""
    target_token = "7af3ad5eb2cac57e9ca97a953908ef09"
    for script in SCENARIOS_DIR.glob('*.sh'):
        content = script.read_text(encoding='utf-8')
        assert target_token not in content, f"Hardcoded token found in {script}"


def test_api_scenario_executes_with_docker_discovered_token(tmp_path):
    """Build 116: scenario successfully discovers API_TOKEN via docker exec on container h-flock-api-lab-tenant-1."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_bin = bin_dir / "docker"
    docker_bin.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"exec\" ] && [ \"$2\" = \"h-flock-api-lab-tenant-1\" ] && [ \"$3\" = \"printenv\" ] && [ \"$4\" = \"API_TOKEN\" ]; then\n"
        "    echo \"discovered-test-token-7788\"\n"
        "else\n"
        "    exit 1\n"
        "fi\n"
    )
    docker_bin.chmod(0o755)

    clean_env = {k: v for k, v in os.environ.items() if k != "API_TOKEN"}
    clean_env["PATH"] = f"{bin_dir}:{clean_env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(SCENARIOS_DIR / "api-auth-and-limits.sh")],
        capture_output=True,
        text=True,
        env=clean_env,
    )
    assert result.returncode == 0
    assert "=== Scenario Complete ===" in result.stdout
    assert "Error: API_TOKEN is empty" not in result.stderr
