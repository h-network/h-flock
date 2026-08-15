#!/usr/bin/env python3
"""Decompose v2 parse, re-encode and Redis-write cost by payload size/shape."""

import json
import math
import os
import statistics
import time

import redis

from flock.bus.envelope import build


SIZES = (16, 65_536, 1_048_576)
SAMPLES = int(os.environ.get("SAMPLES", "200"))
WARMUP = 10


def payload(shape: str, size: int) -> dict:
    if shape == "string":
        return {"text": "x" * size}
    # Repeated small objects force json.loads to allocate thousands of dicts,
    # strings and list slots instead of scanning one long string. The encoded
    # payload is kept close to the requested byte class, not claimed exact.
    item_bytes = len(json.dumps({"value": "xxxxxxxx"}, separators=(",", ":"))) + 1
    count = max(1, math.ceil(size / item_bytes))
    return {"items": [{"value": "xxxxxxxx"} for _ in range(count)]}


def samples(operation, cleanup=lambda: None):
    for _ in range(WARMUP):
        operation()
        cleanup()
    observed = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        operation()
        observed.append((time.perf_counter() - started) * 1_000_000)
        cleanup()
    return statistics.median(observed), sorted(observed)[math.ceil(SAMPLES * 0.95) - 1]


def main() -> None:
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    key = "build72:frame-cost"
    r.delete(key)
    print("shape,payload_target,frame_bytes,operation,n,p50_us,p95_us")
    for shape in ("string", "nested"):
        for size in SIZES:
            frame = build(
                "Message",
                "architect",
                "sme-2",
                payload(shape, size),
                pod="acme",
                tenant="bus72",
            )
            raw = json.dumps(frame, separators=(",", ":"))
            operations = (
                ("json.loads", lambda: json.loads(raw), lambda: None),
                ("json.dumps", lambda: json.dumps(frame, separators=(",", ":")), lambda: None),
                ("redis.rpush", lambda: r.rpush(key, raw), lambda: r.lpop(key)),
            )
            for name, operation, cleanup in operations:
                p50, p95 = samples(operation, cleanup)
                print(f"{shape},{size},{len(raw.encode())},{name},{SAMPLES},{p50:.3f},{p95:.3f}")
    r.delete(key)


if __name__ == "__main__":
    main()
