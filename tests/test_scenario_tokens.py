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
