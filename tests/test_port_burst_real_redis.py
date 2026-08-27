"""Real-Redis tests for atomic ingress drain, concurrency, and Message batching."""

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import redis

from flock.bus import build as build_envelope, encode, prefix
from flock.bus import resp as resp_redis
from flock.port.deliver import _DRAIN_INGRESS, drain_ingress, deliver_one, run_port


@pytest.fixture
def real_redis_server(tmp_path):
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
                    yield port, client
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


def test_atomic_drain_with_concurrent_producers(real_redis_server):
    port, client = real_redis_server
    ingress_key = "test:concurrent:ingress"

    barrier = threading.Barrier(11)  # 10 producers + 1 drainer
    drained_batches = []

    def produce(idx):
        barrier.wait()
        for j in range(10):
            client.rpush(ingress_key, f"msg-{idx}-{j}")

    def drain():
        barrier.wait()
        for _ in range(20):
            batch = drain_ingress(client, ingress_key)
            if batch:
                drained_batches.append(batch)
            time.sleep(0.005)

    producer_threads = [threading.Thread(target=produce, args=(i,)) for i in range(10)]
    drain_thread = threading.Thread(target=drain)

    for t in producer_threads:
        t.start()
    drain_thread.start()

    for t in producer_threads:
        t.join()
    drain_thread.join()

    # Final drain for any items left
    final_batch = drain_ingress(client, ingress_key)
    if final_batch:
        drained_batches.append(final_batch)

    # Ingress must be empty
    assert client.llen(ingress_key) == 0

    # Total items drained must be exactly 100
    all_drained = [item for batch in drained_batches for item in batch]
    assert len(all_drained) == 100
    assert len(set(all_drained)) == 100  # no duplicates


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_real_redis_port_delivery_batching_and_markers(mock_run_tmux, mock_list_windows, real_redis_server, capsys):
    port, client = real_redis_server
    redis_url = f"redis://127.0.0.1:{port}/0"

    mock_list_windows.return_value = {"architect", "bob"}
    mock_run_tmux.return_value = (0, "", "")

    # Set launch CLI and roster
    client.set(prefix("acme", "hq", agent="bob", resource="launch"), "claude")
    client.hset(prefix("acme", "hq", resource="roster"), "bob", "tmux")

    ingress_key = prefix("acme", "hq", agent="bob", resource="ingress")

    # Send 5 messages in a burst
    envelopes = [
        build_envelope(
            kind="Message",
            source="architect",
            destination="bob",
            payload={"text": f"burst-part-{i}"},
        )
        for i in range(1, 6)
    ]
    for i, env in enumerate(envelopes, 1):
        env["stream_id"] = f"{i:032x}"

    client.rpush(ingress_key, *[encode(e) for e in envelopes])

    run_port(agent="bob", pod="acme", tenant="hq", redis_url=redis_url, session_name="hq")

    # Ingress drained
    assert client.llen(ingress_key) == 0

    # Exactly 1 paste call
    load_buffer_calls = [call for call in mock_run_tmux.call_args_list if "load-buffer" in call[0]]
    assert len(load_buffer_calls) == 1
    input_data = load_buffer_calls[0][1].get("input_data", "")
    for i in range(1, 6):
        assert f"[message from architect] burst-part-{i}\n" in input_data

    # 5 markers in pending.verify and delivery.markers in real Redis
    verify_key = prefix("acme", "hq", agent="bob", resource="pending.verify")
    markers_key = prefix("acme", "hq", agent="bob", resource="delivery.markers")

    verify_entries = client.xrange(verify_key)
    markers_entries = client.xrange(markers_key)

    assert len(verify_entries) == 5
    assert len(markers_entries) == 5

    verify_ids = [fields["stream_id"] for _, fields in verify_entries]
    assert verify_ids == [e["stream_id"] for e in envelopes]
