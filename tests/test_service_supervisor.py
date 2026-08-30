import os
import signal
import subprocess
import time
from pathlib import Path


SUPERVISOR = Path(__file__).parents[1] / "container/supervise-service.sh"
ENTRYPOINT = Path(__file__).parents[1] / "container/entrypoint.sh"


def _wait_for_lines(path: Path, count: int, timeout: float = 3) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = path.read_text().splitlines() if path.exists() else []
        if len(lines) >= count:
            return lines
        time.sleep(0.02)
    raise AssertionError(f"expected {count} launches, got {lines}")


def test_service_restarts_without_disturbing_peer_and_term_reaches_child(tmp_path):
    launches = tmp_path / "launches"
    worker = tmp_path / "worker.sh"
    worker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$$\" >> \"$1\"\n"
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 1; done\n"
    )
    worker.chmod(0o755)
    env = {**os.environ, "SERVICE_RESTART_SECONDS": "0.05"}
    first = subprocess.Popen([str(SUPERVISOR), "first", str(worker), str(launches)], env=env)
    peer = subprocess.Popen([str(SUPERVISOR), "peer", str(worker), str(tmp_path / "peer")], env=env)
    try:
        first_pid = int(_wait_for_lines(launches, 1)[0])
        peer_pid = int(_wait_for_lines(tmp_path / "peer", 1)[0])
        os.kill(first_pid, signal.SIGTERM)
        restarted_pid = int(_wait_for_lines(launches, 2)[1])
        assert restarted_pid != first_pid
        os.kill(peer_pid, 0)

        first.send_signal(signal.SIGTERM)
        first.wait(timeout=3)
        with subprocess.Popen(["bash", "-c", f"kill -0 {restarted_pid} 2>/dev/null"]) as probe:
            assert probe.wait() != 0
    finally:
        for process in (first, peer):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=3)


def test_peer_services_use_supervisor_while_redis_remains_critical():
    script = ENTRYPOINT.read_text()
    for service in ("tmux_reconciler", "switch", "watchdog", "api", "session"):
        assert f"start {service}" in script
    assert 'start_critical redis "${redis_cmd[@]}"' in script
    assert '/usr/local/bin/supervise-service.sh "$name" "$@" &' in script
    assert 'wait -n "${pids[@]}"' not in script
    assert 'wait "$critical_pid"' in script
