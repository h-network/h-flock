#!/usr/bin/env python3
"""bench-port — a synthetic port. Pops, records, discards.

    python3 bench-port.py --pod acme --tenant bench --prefix bench- --count 100

⚠ **This is a SWITCH benchmark, not a delivery test.** It deliberately removes
the two things that dominate a real delivery and vary the most:

  * **process spawn per envelope** — measured at 659–911 ms in situ, ~98% of the
    path. This process is long-lived and pops in a loop, so a delivery costs a
    Redis round trip instead of an interpreter start
  * **the opener's work** — a tmux paste sleeps `PASTE_ENTER_DELAY` (0.5 s); an
    api client writes a stream entry. Neither says anything about forwarding

What is left is exactly what a forwarding change moves: **egress → switch →
ingress → pop**, and the custody records that prove it.

⚠ **It emits the SAME records a real port does** — `received` then `opened`,
same fields, same join key — so `analyse-run.py` reads its logs unchanged and
the figures are comparable stage by stage.

⚠ **It does NOT replace real-path testing.** A green run here says the fabric
forwards correctly and fast. It says nothing about whether a message reaches an
agent, which is what `accept.sh` and the tmux path are for. **Do not quote these
numbers as delivery throughput.**
"""
import argparse
import os
import sys
import time

sys.path.insert(0, "/app/src")

import redis  # noqa: E402  (long-lived process: the import is paid once)

from flock.bus import parse, prefix  # noqa: E402
# ⚠ Reuse the real receive-side emitter rather than reimplementing it. Build 69
# made these records name the actual recipient rather than L2's fan-out target,
# and a synthetic port that got that wrong would silently break reconciliation.
from flock.bus.doors import _emit_for_recipient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pod", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--prefix", default="bench-")
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--idle-exit", type=float, default=30.0,
                    help="exit after this many seconds with no envelope")
    args = ap.parse_args()

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    keys = [
        prefix(args.pod, args.tenant, f"{args.prefix}{i}", "ingress")
        for i in range(1, args.count + 1)
    ]

    handled = 0
    last = time.time()
    while True:
        item = r.blpop(keys, timeout=2)
        if item is None:
            if time.time() - last > args.idle_exit:
                break
            continue
        last = time.time()
        key, raw = item
        if isinstance(key, bytes):
            key = key.decode()
        # `pod:<p>:tenant:<t>:agent:<name>:ingress` — the participant this pop is for.
        agent = key.split(":")[-2]
        try:
            envelope = parse(raw)
        except Exception as exc:
            # ⚠ Mirror the real port: a malformed frame dead-letters, it does not vanish.
            r.rpush(prefix(args.pod, args.tenant, agent, "dead"), raw)
            _emit_for_recipient("port", "dead_lettered", {}, agent, str(exc))
            continue
        # Same two records a real port writes, with the recipient this pop was for
        # (build 69) so broadcast reconciles on (stream_id, recipient).
        for event in ("received", "opened"):
            _emit_for_recipient("port", event, envelope, agent)
        handled += 1

    print(f"bench-port: handled {handled}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
