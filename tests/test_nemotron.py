import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "container/scenarios/tmux-nemotron.sh"


def _drain_function():
    text = TOOL.read_text()
    return re.search(r"drain_transport\(\) \{\n.*?\n\}", text, re.DOTALL).group(0)


def _run_drain(depths, tmp_path, *, timeout=10):
    sequence = " ".join(depths)
    state = tmp_path / "calls"
    probe = f'''set -uo pipefail
{_drain_function()}
depths=($DEPTHS)
sleeps=0
printf 0 >"$STATE"
read_transport_depth() {{
  index="$(cat "$STATE")"
  value="${{depths[$index]:-${{depths[-1]}}}}"
  printf '%s' "$((index + 1))" >"$STATE"
  [ "$value" = FAIL ] && return 1
  [ "$value" = EMPTY ] || printf '%s\n' "$value"
}}
sleep() {{ sleeps=$((sleeps + 1)); SECONDS=$((SECONDS + $1)); }}
SECONDS=0
drain_transport "$TIMEOUT" 1
rc=$?
printf 'rc=%s calls=%s sleeps=%s\n' "$rc" "$(cat "$STATE")" "$sleeps"
exit "$rc"
'''
    return subprocess.run(
        ["bash", "-c", probe],
        env={**os.environ, "DEPTHS": sequence, "TIMEOUT": str(timeout), "STATE": str(state)},
        capture_output=True,
        text=True,
        timeout=2,
    )


def test_nemotron_dx_forwards_heredoc_stdin_into_container():
    text = TOOL.read_text()
    assert 'dx() { docker exec -i "$CONTAINER" "$@"; }' in text
    assert "read_transport_depth()" in text
    assert 'dx python3 - "$POD" "$TENANT"' in text


def test_drain_exits_immediately_only_when_depth_is_zero(tmp_path):
    empty = _run_drain(["0"], tmp_path)
    assert empty.returncode == 0
    assert "rc=0 calls=1 sleeps=0" in empty.stdout

    draining = _run_drain(["3", "0"], tmp_path)
    assert draining.returncode == 0
    assert "rc=0 calls=2 sleeps=1" in draining.stdout


@pytest.mark.parametrize("depth", ["EMPTY", "warning", "1x"])
def test_drain_refuses_empty_or_non_integer_depth(tmp_path, depth):
    result = _run_drain([depth], tmp_path)
    assert result.returncode == 100
    assert "incomplete reason=unreadable_queue_depth" in result.stderr


def test_drain_refuses_a_failed_depth_probe(tmp_path):
    result = _run_drain(["FAIL"], tmp_path)
    assert result.returncode == 100
    assert "incomplete reason=queue_depth_probe_failed" in result.stderr
