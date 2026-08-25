#!/usr/bin/env python3
"""Inject one unknown control-plane write in the real host port process."""

import argparse
import os
import subprocess
import time

import redis

from flock.bus import log_record, prefix, send
from flock.control.openers import start_agent
from flock.port import deliver as port


class RefusePurgeReplyOnce:
    """Allow roster hdel, then make the following resource delete UNKNOWN."""

    def __init__(self, client, purge_keys):
        self._client = client
        self._purge_keys = set(purge_keys)
        self.roster_removed = False
        self.fired = False

    def __getattr__(self, name):
        return getattr(self._client, name)

    def hdel(self, key, *fields):
        result = self._client.hdel(key, *fields)
        text = key.decode() if isinstance(key, bytes) else key
        if text.endswith(":roster"):
            self.roster_removed = True
        return result

    def delete(self, *keys):
        normalized = {
            key.decode() if isinstance(key, bytes) else key for key in keys
        }
        if self.roster_removed and not self.fired and normalized & self._purge_keys:
            self.fired = True
            raise redis.ConnectionError(
                "BUILD102 deliberate resource purge reply loss"
            )
        return self._client.delete(*keys)


def _office(command, *, pod, tenant, agent):
    env = os.environ | {"POD": pod, "TENANT": tenant, "AGENT_NAME": agent}
    return subprocess.run(
        ["office", command], env=env, text=True, capture_output=True, check=False
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pod", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()

    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    marker = prefix(args.pod, args.tenant, resource="fault.injection")
    armed = client.get(marker)
    armed = armed.decode() if isinstance(armed, bytes) else armed
    if armed != args.token:
        raise SystemExit("REFUSED: fault token does not match this tenant marker")

    roster_key = prefix(args.pod, args.tenant, resource="roster")
    state_keys = {
        prefix(args.pod, args.tenant, agent=args.agent, resource=resource)
        for resource in (
            "launch", "profile", "provider", "paused", "tasks.todo",
            "tasks.doing", "tasks.hold", "tasks.done", "delivery.markers",
            "pending.verify", "inbox",
        )
    }
    client.hset(roster_key, args.agent, "tmux")
    for key in state_keys:
        client.set(key, "BUILD102 residue")
    client.hset(prefix(args.pod, args.tenant, resource="delivering"), args.agent, "held")

    ingress_key = prefix(args.pod, args.tenant, agent="host", resource="ingress")
    # Make the one-shot pop deterministic: wait for any prior host mail to
    # clear, then wait for this envelope to reach ingress before popping.
    for _ in range(120):
        if client.llen(ingress_key) == 0:
            break
        time.sleep(0.1)
    else:
        raise SystemExit("REFUSED: host ingress already contains queued mail")
    stream_id = send(
        client,
        pod=args.pod,
        tenant=args.tenant,
        source="architect",
        destination="host",
        payload={"agent": args.agent},
        kind="StopAgent",
        module="fault_injection",
    )
    log_record(
        "fault_injection", "active", destination=args.agent,
        reason="BUILD102 deliberate purge reply loss",
    )
    for _ in range(120):
        if client.llen(ingress_key) > 0:
            break
        time.sleep(0.1)
    else:
        raise SystemExit("REFUSED: StopAgent envelope did not reach host ingress")

    fault = RefusePurgeReplyOnce(client, state_keys)
    original = port.redis.Redis.from_url
    port.redis.Redis.from_url = lambda _url: fault
    try:
        port.run_port(
            agent="host", pod=args.pod, tenant=args.tenant,
            redis_url=os.environ["REDIS_URL"], session_name=args.tenant,
        )
    except redis.ConnectionError as exc:
        if not fault.fired or not fault.roster_removed:
            raise
        log_record(
            "fault_injection", "observed", destination=args.agent,
            reason=str(exc),
        )
    finally:
        port.redis.Redis.from_url = original

    if not fault.fired:
        raise SystemExit("REFUSED: deliberate purge fault did not fire")

    status = _office("status", pod=args.pod, tenant=args.tenant, agent="architect")
    peers = _office("peers", pod=args.pod, tenant=args.tenant, agent="architect")
    with open(args.snapshot, "w", encoding="utf-8") as out:
        out.write(f"stop_stream={stream_id}\n")
        out.write("STATE roster=" + ("present" if client.hexists(roster_key, args.agent) else "absent") + "\n")
        out.write("STATE resources=" + ("present" if any(client.exists(k) for k in state_keys) else "absent") + "\n")
        out.write("STATE delivery_lock=" + ("present" if client.hexists(prefix(args.pod, args.tenant, resource="delivering"), args.agent) else "absent") + "\n")
        out.write("STATUS_BEGIN\n" + status.stdout + status.stderr + "STATUS_END\n")
        out.write("PEERS_BEGIN\n" + peers.stdout + peers.stderr + "PEERS_END\n")

    # A subsequent StartAgent uses the real control opener after the faulted
    # host-port delivery. This is the same operation an unfaulted host port
    # would invoke, while keeping the observation in this immutable snapshot.
    start = send(
        client,
        pod=args.pod,
        tenant=args.tenant,
        source="architect",
        destination="host",
        payload={"agent": args.agent, "cli": "claude"},
        kind="StartAgent",
        module="fault_injection",
    )
    start_agent(
        client, pod=args.pod, tenant=args.tenant,
        envelope={"payload": {"agent": args.agent, "cli": "claude"}},
        replace_window=lambda _agent: None,
    )
    with open(args.snapshot, "a", encoding="utf-8") as out:
        out.write(f"start_stream={start}\n")
        out.write("START_RESULT roster=" + ("present" if client.hexists(roster_key, args.agent) else "absent") + "\n")
        out.write("START_RESULT resources=" + ("present" if any(client.exists(k) for k in state_keys) else "absent") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
