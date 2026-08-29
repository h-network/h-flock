"""Real-Redis controls for atomic ingress admission."""

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import redis

from flock.bus import prefix
from flock.bus.doors import _increment_unreplied, _update_ack_streak
from flock.bus.queues import admit_ingress


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
        results.append(
            admit_ingress(
                real_redis,
                pod="acme",
                tenant="hq",
                destinations=["bob"],
                raw=raw,
                limit=1,
            )
        )

    threads = [threading.Thread(target=admit, args=(raw,)) for raw in ("one", "two")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(result[0] for result in results) == [False, True]
    assert (True, None, None) in results
    assert (False, "bob", 1) in results
    key = prefix("acme", "hq", "bob", "ingress")
    assert real_redis.llen(key) == 1
    assert real_redis.lindex(key, 0) in {"one", "two"}


def test_broadcast_rejection_appends_no_partial_copy(real_redis):
    bob = prefix("acme", "hq", "bob", "ingress")
    carol = prefix("acme", "hq", "carol", "ingress")
    real_redis.rpush(bob, "already full")
    result = admit_ingress(
        real_redis,
        pod="acme",
        tenant="hq",
        destinations=["bob", "carol"],
        raw="broadcast",
        limit=1,
    )

    assert result == (False, "bob", 1)
    assert real_redis.lrange(bob, 0, -1) == ["already full"]
    assert real_redis.llen(carol) == 0


def test_rejection_identifies_later_full_destination(real_redis):
    carol = prefix("acme", "hq", "carol", "ingress")
    real_redis.rpush(carol, "already full")

    result = admit_ingress(
        real_redis,
        pod="acme",
        tenant="hq",
        destinations=["bob", "carol"],
        raw="broadcast",
        limit=1,
    )

    assert result == (False, "carol", 1)


@pytest.mark.parametrize(
    ("destinations", "limit", "message"),
    [([], 1, "destinations must not be empty"), (["bob"], 0, "limit must be positive")],
)
def test_admission_rejects_invalid_operation_before_redis(
    real_redis, destinations, limit, message
):
    with pytest.raises(ValueError, match=message):
        admit_ingress(
            real_redis,
            pod="acme",
            tenant="hq",
            destinations=destinations,
            raw="message",
            limit=limit,
        )


def test_concurrent_unreplied_increments_preserve_count_and_first_since(real_redis):
    key = prefix("acme", "hq", "alice", "unreplied")
    first_since = "2026-08-29T12:00:00.000Z"
    _increment_unreplied(real_redis, key=key, client="telegram", since=first_since)
    barrier = threading.Barrier(11)

    def increment(index):
        barrier.wait()
        _increment_unreplied(
            real_redis, key=key, client="telegram",
            since=f"2026-08-29T12:00:{index:02d}.000Z",
        )

    threads = [threading.Thread(target=increment, args=(index,)) for index in range(1, 11)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert json.loads(real_redis.hget(key, "telegram")) == {
        "count": 11,
        "since": first_since,
    }


def test_concurrent_ack_streak_updates_are_atomic(real_redis):
    key = prefix("acme", "hq", "alice", "acks")
    barrier = threading.Barrier(11)

    def update():
        barrier.wait()
        _update_ack_streak(
            real_redis, key=key, destination="bob",
            now_ts="2026-08-29T16:00:30.000Z",
            cutoff_ts="2026-08-29T15:58:30.000Z",
        )

    threads = [threading.Thread(target=update) for _ in range(10)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert json.loads(real_redis.hget(key, "bob")) == {
        "streak": 10,
        "last_ts": "2026-08-29T16:00:30.000Z",
    }
