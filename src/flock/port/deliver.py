import json
import os
import time
from datetime import datetime, timezone
from flock.bus import EnvelopeError, log_record, parse, prefix, receive
from flock.bus.doors import _emit_for_recipient
# Minimal hand-rolled RESP client (flock.bus.resp.Redis), not redis-py, for fast transient process startup
from flock.bus import resp as redis
from .openers import add_ticket_opener, command_opener, message_opener


class _CatchAllDict(dict):
    def __init__(self, default_factory):
        super().__init__()
        self.default_factory = default_factory

    def get(self, key, default=None):
        return self.default_factory(key)

    def __getitem__(self, key):
        return self.default_factory(key)

    def __contains__(self, key):
        return True


def deliver_api(
    r,
    pod: str,
    tenant: str,
    agent: str,
    timeout: int = 1,
) -> None:
    inbox_key = prefix(pod, tenant, agent=agent, resource="inbox")

    def handle_api_inbox(envelope: dict) -> None:
        raw_env = json.dumps(envelope)
        r.xadd(inbox_key, {"envelope": raw_env}, maxlen=1000, approximate=True)

    openers = _CatchAllDict(lambda _kind: handle_api_inbox)
    receive(
        r,
        pod=pod,
        tenant=tenant,
        agent=agent,
        openers=openers,
        timeout=timeout,
        blocking=False,
        module="port",
    )


def deliver_unroutable(
    r,
    pod: str,
    tenant: str,
    agent: str,
    port_type_name: str | None,
    timeout: int = 1,
) -> None:
    ingress_key = prefix(pod, tenant, agent, "ingress")
    raw = r.lpop(ingress_key)
    if raw is None:
        return
    dead_key = prefix(pod, tenant, agent, "dead")
    try:
        envelope = parse(raw)
    except EnvelopeError as exc:
        r.rpush(dead_key, raw)
        _emit_for_recipient("port", "dead_lettered", {}, agent, str(exc))
        return
    _emit_for_recipient("port", "received", envelope, agent)
    r.rpush(dead_key, raw)
    reason = f"unroutable port_type: {port_type_name!r}"
    _emit_for_recipient("port", "dead_lettered", envelope, agent, reason)


def deliver_one(
    r,
    pod: str,
    tenant: str,
    agent: str,
    session_name: str,
    socket: str | None = None,
) -> None:
    paused_key = prefix(pod, tenant, agent=agent, resource="paused")
    if r.get(paused_key):
        return

    roster_key = prefix(pod, tenant, resource="roster")
    raw_port_type = r.hget(roster_key, agent)
    agent_port_type = raw_port_type.decode() if isinstance(raw_port_type, bytes) else raw_port_type

    if agent_port_type == "control":
        try:
            from flock.control import deliver_one as control_deliver_one
            control_deliver_one(
                r,
                pod=pod,
                tenant=tenant,
                agent=agent,
                session_name=session_name,
                socket=socket,
            )
        except ImportError:
            log_record("port", "error", destination=agent, reason="flock.control module not available")
        return

    if agent_port_type == "api":
        deliver_api(r, pod=pod, tenant=tenant, agent=agent)
        return

    if agent_port_type is not None and agent_port_type != "tmux":
        deliver_unroutable(r, pod=pod, tenant=tenant, agent=agent, port_type_name=agent_port_type)
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

    def handle_command(envelope: dict) -> None:
        command_opener(
            r=r,
            pod=pod,
            tenant=tenant,
            agent=agent,
            envelope=envelope,
            session_name=session_name,
            socket=socket,
        )

    def handle_add_ticket(envelope: dict) -> None:
        add_ticket_opener(
            r=r,
            pod=pod,
            tenant=tenant,
            agent=agent,
            envelope=envelope,
            session_name=session_name,
            socket=socket,
        )

    openers = {
        "Message": handle_message,
        "Command": handle_command,
        "AddTicket": handle_add_ticket,
    }
    receive(
        r,
        pod=pod,
        tenant=tenant,
        agent=agent,
        openers=openers,
        timeout=1,
        blocking=False,
        module="port",
    )


def run_port(
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

    # Atomic busy tag acquisition using hsetnx
    while True:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if r.hsetnx(delivering_key, agent, now_iso):
            break
        time.sleep(0.05)

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
