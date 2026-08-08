import os
import time
from datetime import datetime, timezone
import redis

from flock.bus import prefix, receive, vab
from .openers import message_opener


def deliver_one(
    r: redis.Redis,
    pod: str,
    tenant: str,
    agent: str,
    session_name: str,
    socket: str | None = None,
) -> None:
    agent_vab = vab(r, pod=pod, tenant=tenant, agent=agent)
    if agent_vab is not None and agent_vab != "tmux":
        return

    def handle_message(envelope: dict) -> None:
        message_opener(
            r=r,
            pod=pod,
            tenant=tenant,
            agent=agent,
            envelope=envelope,
            session_name=session_name,
            socket=socket,
        )

    openers = {"Message": handle_message}
    receive(r, pod=pod, tenant=tenant, agent=agent, openers=openers, timeout=0, module="adapter")


def run_adapter(
    agent: str,
    pod: str = "default",
    tenant: str = "default",
    redis_url: str = "redis://127.0.0.1:6379/0",
    session_name: str | None = None,
    socket: str | None = None,
) -> None:
    r = redis.Redis.from_url(redis_url)
    session_name = session_name or tenant
    socket = socket or os.environ.get("TMUX_SOCKET")

    delivering_key = prefix(pod, tenant, resource="delivering")

    # Wait for busy tag to clear
    while r.hexists(delivering_key, agent):
        time.sleep(0.05)

    # Set busy tag
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    r.hset(delivering_key, agent, now_iso)

    try:
        deliver_one(
            r,
            pod=pod,
            tenant=tenant,
            agent=agent,
            session_name=session_name,
            socket=socket,
        )
    finally:
        r.hdel(delivering_key, agent)
