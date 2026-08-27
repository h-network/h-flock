"""Real-Redis controls for atomic ingress admission."""

import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import redis

from flock.switch.service import _ADMIT_INGRESS


@pytest.fixture
def real_redis(tmp_path):
    redis_bin = shutil.which("redis-server") or "/usr/bin/redis-server"
    if not Path(redis_bin).exists():
        pytest.fail(f"redis-server binary not found at {redis_bin}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [redis_bin, "--port", str(port), "--dir", str(tmp_path), "--save", "", "--appendonly", "no"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(50):
            try:
                client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True)
                if client.ping():
                    yield client
                    return
            except redis.RedisError:
                time.sleep(0.05)
        pytest.fail("real redis-server did not become ready")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_concurrent_admission_never_exceeds_limit(real_redis):
    barrier = threading.Barrier(3)
    results = []

    def admit(raw):
        barrier.wait()
        results.append(real_redis.eval(_ADMIT_INGRESS, 1, "ingress", 1, raw))

    threads = [threading.Thread(target=admit, args=(raw,)) for raw in ("one", "two")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(int(result[0]) for result in results) == [0, 1]
    assert real_redis.llen("ingress") == 1
    assert real_redis.lindex("ingress", 0) in {"one", "two"}


def test_broadcast_rejection_appends_no_partial_copy(real_redis):
    real_redis.rpush("bob-ingress", "already full")
    result = real_redis.eval(
        _ADMIT_INGRESS, 2, "bob-ingress", "carol-ingress", 1, "broadcast"
    )

    assert list(map(int, result)) == [0, 1, 1]
    assert real_redis.lrange("bob-ingress", 0, -1) == ["already full"]
    assert real_redis.llen("carol-ingress") == 0
