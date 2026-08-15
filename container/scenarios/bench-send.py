#!/usr/bin/env python3
"""bench-send — generate the benchmark ring, and nothing else.

This is the common sender for the scenario harnesses.  It uses the real
``flock.bus.doors.send`` path and emits the real ``sent`` custody records.  It
does not enrol participants, wait for delivery, read logs, or judge a run.

Stdout is intentionally custody-only.  Harnesses redirect it to PID 1 so the
records enter ``docker logs`` through the same evidence path as the rest of the
run.  The human submission summary goes to stderr.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, "/app/src")

import redis  # noqa: E402

from flock.bus.doors import send  # noqa: E402


def payload_for(round_number: int, payload_bytes: int | None) -> dict[str, str]:
    """Return today's payload, padded (never replaced or truncated) if asked."""
    text = f"r{round_number}"
    if payload_bytes is not None:
        text += "x" * max(0, payload_bytes - len(text.encode("utf-8")))
    return {"text": text}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pod", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--prefix", default="bench-")
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--rounds", type=int, required=True)
    ap.add_argument("--payload-bytes", type=int, default=None)
    ap.add_argument("--names", default=None,
                    help="space-separated participant names; overrides prefix/count names")
    args = ap.parse_args()

    if args.count < 1 or args.rounds < 1:
        ap.error("--count and --rounds must be positive")
    if args.payload_bytes is not None and args.payload_bytes < 0:
        ap.error("--payload-bytes must be non-negative")

    agents = args.names.split() if args.names is not None else [
        f"{args.prefix}{i}" for i in range(1, args.count + 1)
    ]
    if len(agents) != args.count:
        ap.error(f"--names contains {len(agents)} names, expected --count {args.count}")

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    started = time.time()
    for rnd in range(args.rounds):
        for i, source in enumerate(agents):
            send(
                r,
                pod=args.pod,
                tenant=args.tenant,
                source=source,
                destination=agents[(i + 1) % len(agents)],
                kind="Message",
                payload=payload_for(rnd, args.payload_bytes),
            )

    count = len(agents) * args.rounds
    print(f"  submitted {count} in {time.time() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
