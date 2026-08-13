#!/usr/bin/env bash
# frame-bench — interleaved component costs for the v1 flat envelope and v2 frame.
set -euo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
ITERATIONS="${ITERATIONS:-1000}"

docker exec -i "$CONTAINER" python3 - "$POD" "$TENANT" "$ITERATIONS" <<'PY'
import json
import os
import statistics
import sys
import time
import uuid

sys.path.insert(0, "/app/src")
import redis
from flock.bus.envelope import build
from flock.bus.keys import prefix

pod, tenant, iterations = sys.argv[1], sys.argv[2], int(sys.argv[3])
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))

def flat():
    return {
        "v": 1,
        "kind": "Message",
        "stream_id": uuid.uuid4().hex,
        "correlation_id": uuid.uuid4().hex,
        "ts": "2026-08-13T00:00:00.000Z",
        "producer": "alice",
        "recipient": "bob",
        "payload": {"text": "frame benchmark"},
    }

def layered():
    return build(
        "Message", "alice", "bob", {"text": "frame benchmark"},
        pod=pod, tenant=tenant,
    )

flat_ns, frame_ns = [], []
for i in range(iterations):
    pair = ((flat, flat_ns), (layered, frame_ns))
    if i % 2:
        pair = pair[::-1]
    for fn, samples in pair:
        started = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - started)

flat_json = json.dumps(flat(), separators=(",", ":"))
frame_json = json.dumps(layered(), separators=(",", ":"))
print(f"assemble_iterations={iterations}")
print(f"flat_assemble_median_us={statistics.median(flat_ns) / 1000:.2f}")
print(f"frame_assemble_median_us={statistics.median(frame_ns) / 1000:.2f}")
print(f"flat_json_bytes={len(flat_json.encode())}")
print(f"frame_json_bytes={len(frame_json.encode())}")

memory_key = prefix(pod, tenant, "framebench", "egress")
def used_memory():
    return int(r.info("memory")["used_memory"])

r.delete(memory_key)
base = used_memory()
pipe = r.pipeline(transaction=False)
for _ in range(2000):
    pipe.rpush(memory_key, flat_json)
pipe.execute()
flat_delta = used_memory() - base
r.delete(memory_key)
base = used_memory()
pipe = r.pipeline(transaction=False)
for _ in range(2000):
    pipe.rpush(memory_key, frame_json)
pipe.execute()
frame_delta = used_memory() - base
r.delete(memory_key)
print(f"flat_redis_delta_2000_bytes={flat_delta}")
print(f"frame_redis_delta_2000_bytes={frame_delta}")

roster_key = prefix(pod, tenant, resource="roster")
for size in (10, 100, 1000):
    fields = {f"frame-{i}": "api" for i in range(size)}
    r.hset(roster_key, mapping=fields)
    destination = f"frame-{size - 1}"
    old = {"recipient": destination}
    new = {"l2": {"source": "alice", "destination": destination}}
    old_ns, new_ns = [], []
    for i in range(iterations):
        pair = ((old, old_ns, "recipient"), (new, new_ns, "l2"))
        if i % 2:
            pair = pair[::-1]
        for value, samples, shape in pair:
            started = time.perf_counter_ns()
            candidate = value[shape] if shape == "recipient" else value[shape]["destination"]
            r.hexists(roster_key, candidate)
            samples.append(time.perf_counter_ns() - started)
    print(
        f"roster={size} flat_decision_median_us={statistics.median(old_ns) / 1000:.2f} "
        f"l2_decision_median_us={statistics.median(new_ns) / 1000:.2f}"
    )
    r.hdel(roster_key, *fields)
PY
