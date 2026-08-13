#!/usr/bin/env python3
"""policy-bench — does tag policy belong at the port or at the switch?

The layer split in DESIGN-layers §2 rests on an argument that was asserted and
never measured: long policy belongs at the port because ports are per-send and
parallel, while the switch must stay tiny because it is shared and serialized.

This measures the same decision in both placements. It needs no h-flock; it
models the decision against a real Redis, so it can run before build 54 exists.

  REDIS_URL=redis://127.0.0.1:6399/0 python3 policy-bench.py

⚠ Reports MEDIANS. Means are meaningless against a Redis that spikes.
⚠ The port column shows higher TOTAL work by design — N ports each doing a
  lookup is more work than one switch doing it once. The question is not total
  work, it is which curve bends as N grows.
"""
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import redis

URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6399/0")
ROSTERS = [int(x) for x in os.environ.get("ROSTERS", "10,100,1000").split(",")]
TAGSIZES = [int(x) for x in os.environ.get("TAGSIZES", "1,5,20").split(",")]
ITER = int(os.environ.get("ITER", "600"))


def key(agent, side):
    return f"policy:{agent}:{side}"


def seed(r, n, tags):
    """export/import tag sets per participant, in companion keys (§3)."""
    pipe = r.pipeline()
    for i in range(n):
        pipe.delete(key(f"a{i}", "export"), key(f"a{i}", "import"))
        pipe.sadd(key(f"a{i}", "export"), *[f"t{j}" for j in range(tags)])
        pipe.sadd(key(f"a{i}", "import"), *[f"t{j}" for j in range(tags)])
    pipe.execute()


def decide(r, src, dst):
    """May src reach dst? Two reads and a set intersection — DESIGN-layers §3."""
    pipe = r.pipeline()
    pipe.smembers(key(src, "export"))
    pipe.smembers(key(dst, "import"))
    exp, imp = pipe.execute()
    return bool(exp & imp)


def median_us(fn, n=ITER):
    s = []
    fn()
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        s.append((time.perf_counter() - t0) * 1e6)
    return statistics.median(s)


def _worker(args):
    """One port: its own connection, its own decisions. Returns wall seconds."""
    count, tags = args
    r = redis.Redis.from_url(URL)
    t0 = time.perf_counter()
    for i in range(count):
        decide(r, f"a{i % 10}", f"a{(i + 1) % 10}")
    return time.perf_counter() - t0


def main():
    r = redis.Redis.from_url(URL)
    r.ping()
    print(f"redis {URL}   iterations {ITER}\n")

    print("== 1. cost of ONE decision (2 reads pipelined + intersection) ==")
    print(f"{'roster':>7} {'tags':>5} {'median us':>11}")
    for n in ROSTERS:
        for t in TAGSIZES:
            seed(r, min(n, 200), t)
            us = median_us(lambda: decide(r, "a0", "a1"))
            print(f"{n:>7} {t:>5} {us:>11.1f}")

    print("\n== 2. what it costs the SWITCH (serialized, one process) ==")
    seed(r, 200, 5)
    base = median_us(lambda: r.hexists("policy:roster", "a1"))
    withp = median_us(lambda: (r.hexists("policy:roster", "a1"), decide(r, "a0", "a1")))
    print(f"  forwarding lookup only          {base:8.1f} us  ->  ceiling {1e6/base:9,.0f}/s")
    print(f"  forwarding lookup + tag check   {withp:8.1f} us  ->  ceiling {1e6/withp:9,.0f}/s")
    print(f"  ⚠ the switch's ceiling drops by {100*(1-base/withp):.0f}%")

    print("\n== 3. what it costs the PORTS (parallel, N processes) ==")
    print(f"{'ports':>6} {'decisions each':>15} {'wall s':>9} {'total/s':>11} {'per-port us':>13}")
    per = 400
    for ports in (1, 2, 4, 8, 16):
        with ProcessPoolExecutor(max_workers=ports) as ex:
            t0 = time.perf_counter()
            list(ex.map(_worker, [(per, 5)] * ports))
            wall = time.perf_counter() - t0
        total = ports * per
        print(f"{ports:>6} {per:>15} {wall:>9.2f} {total/wall:>11,.0f} {wall*1e6/per:>13.1f}")
    print("  ⚠ if per-port us stays flat while total/s rises, the parallel claim holds")


if __name__ == "__main__":
    sys.exit(main())
