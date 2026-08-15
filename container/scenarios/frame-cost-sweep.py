#!/usr/bin/env python3
"""Decompose fixed-header parsing, source stamping and Redis-write cost."""

import json
import math
import os
import statistics
import time

import redis

from flock.bus.envelope import build, encode, parse_for_switch, stamp_source


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


def rotate(values, offset):
    offset %= len(values)
    return values[offset:] + values[:offset]


def main() -> None:
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    key = "frame-cost-sweep"
    r.delete(key)
    cases = []
    for shape in ("string", "nested"):
        for size in SIZES:
            frame = build(
                "Message",
                "architect",
                "sme-2",
                payload(shape, size),
                pod="acme",
                # Keep the qualified L3 addresses the same length as the bus72
                # baseline so frame-size deltas describe the header, not names.
                tenant="bench",
            )
            cases.append((shape, size, encode(frame)))

    print("shape,payload_target,frame_bytes,operation,n,p50_us,p95_us")
    for name in ("parse_for_switch", "stamp_source", "redis.rpush"):
        observed = {(shape, size): [] for shape, size, _raw in cases}
        for repetition in range(WARMUP + SAMPLES):
            # Rotate all six cases through every position. Measuring one shape
            # in a block produced a 3.3 versus 4.3 us split on identical header
            # work solely because CPU state drifted between the blocks.
            for shape, size, raw in rotate(cases, repetition):
                started = time.perf_counter()
                if name == "parse_for_switch":
                    parse_for_switch(raw)
                elif name == "stamp_source":
                    stamp_source(raw, "architect")
                else:
                    r.rpush(key, raw)
                elapsed = (time.perf_counter() - started) * 1_000_000
                if name == "redis.rpush":
                    r.lpop(key)
                if repetition >= WARMUP:
                    observed[(shape, size)].append(elapsed)
        for shape, size, raw in cases:
            values = sorted(observed[(shape, size)])
            p50 = statistics.median(values)
            p95 = values[math.ceil(SAMPLES * 0.95) - 1]
            print(f"{shape},{size},{len(raw.encode())},{name},{SAMPLES},{p50:.3f},{p95:.3f}")
    r.delete(key)


if __name__ == "__main__":
    main()
