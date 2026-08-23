#!/usr/bin/env python3
"""Run one deliberately faulted switch step against a disposable live tenant."""

import argparse
import os
import time

import redis

from flock.bus import log_record, prefix, send
from flock.switch.service import Switch


class RefuseIngressReplyOnce:
    """Delegate every Redis operation except one deliberately unanswered write."""

    def __init__(self, client, target: str):
        self._client = client
        self._target = target
        self.fired = False

    def __getattr__(self, name):
        return getattr(self._client, name)

    def rpush(self, key, *values):
        text = key.decode() if isinstance(key, bytes) else key
        if text == self._target and not self.fired:
            self.fired = True
            # Deliberately do not call Redis. From the switch's observation an
            # exception supplies no evidence whether the server committed; the
            # live queue capture therefore has no later fact that can settle it.
            raise redis.ConnectionError("BUILD100 deliberate missing ingress reply")
        return self._client.rpush(key, *values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pod", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()

    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    marker = prefix(args.pod, args.tenant, resource="fault.injection")
    armed = client.get(marker)
    armed = armed.decode() if isinstance(armed, bytes) else armed
    if armed != args.token:
        raise SystemExit("REFUSED: fault token does not match this tenant's ownership marker")

    target = prefix(args.pod, args.tenant, args.destination, "ingress")
    log_record(
        "fault_injection",
        "active",
        source=args.source,
        destination=args.destination,
        reason="BUILD100 deliberate one-shot ingress reply loss",
    )
    client.hset(
        prefix(args.pod, args.tenant, resource="roster"),
        mapping={args.source: "api", args.destination: "api"},
    )
    sent_ts = time.time()
    stream_id = send(
        client,
        pod=args.pod,
        tenant=args.tenant,
        source=args.source,
        destination=args.destination,
        payload={"text": "BUILD100 deliberate forward_unknown"},
        module="fault_injection",
    )
    with open(args.ledger, "w", encoding="utf-8") as ledger:
        ledger.write(
            f"1\t{stream_id}\t{args.source}\t{args.destination}\t{sent_ts}\n"
        )

    faulted = RefuseIngressReplyOnce(client, target)
    try:
        Switch(faulted, pod=args.pod, tenant=args.tenant).step(timeout=1)
    except redis.ConnectionError as exc:
        if not faulted.fired:
            raise
        log_record(
            "fault_injection",
            "observed",
            source=args.source,
            destination=args.destination,
            reason=str(exc),
        )
        return 0
    raise SystemExit("REFUSED: deliberate forward fault did not fire")


if __name__ == "__main__":
    raise SystemExit(main())
