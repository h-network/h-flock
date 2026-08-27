import json
import os
import time
from datetime import datetime, timezone
from flock.bus import DeadLetter, EnvelopeError, log_record, parse, prefix, receive
from flock.bus.doors import _emit_for_recipient
from flock.bus.envelope import parse_for_switch
# Minimal hand-rolled RESP client (flock.bus.resp.Redis), not redis-py, for fast transient process startup
from flock.bus import resp as redis
from .openers import add_ticket_opener, command_opener, message_opener, messages_opener


_DRAIN_INGRESS = """
-- flock ingress drain all v1
local key = KEYS[1]
local items = redis.call('LRANGE', key, 0, -1)
if #items > 0 then
    redis.call('DEL', key)
end
return items
"""


def drain_ingress(r, ingress_key: str) -> list[str]:
    """Atomically drain all raw envelopes currently queued in ingress."""
    if hasattr(r, "eval"):
        try:
            res = r.eval(_DRAIN_INGRESS, 1, ingress_key)
            if res is not None:
                return [item.decode() if isinstance(item, bytes) else str(item) for item in res]
        except Exception:
            pass
    # Fallback for test doubles without eval support
    items = []
    while True:
        raw = r.lpop(ingress_key)
        if raw is None:
            break
        items.append(raw.decode() if isinstance(raw, bytes) else str(raw))
    return items


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
    ingress_key = prefix(pod, tenant, agent, "ingress")
    dead_key = prefix(pod, tenant, agent, "dead")
    inbox_key = prefix(pod, tenant, agent=agent, resource="inbox")

    raw_items = drain_ingress(r, ingress_key)
    for raw in raw_items:
        try:
            envelope = parse(raw)
        except EnvelopeError as exc:
            r.rpush(dead_key, raw)
            try:
                header = parse_for_switch(raw)
            except EnvelopeError:
                header = {}
            _emit_for_recipient("port", "dead_lettered", header, agent, str(exc))
            continue

        _emit_for_recipient("port", "received", envelope, agent)
        raw_env = json.dumps(envelope)
        r.xadd(inbox_key, {"envelope": raw_env}, maxlen=1000, approximate=True)
        _emit_for_recipient("port", "opened", envelope, agent)


def deliver_unroutable(
    r,
    pod: str,
    tenant: str,
    agent: str,
    port_type_name: str | None,
    timeout: int = 1,
) -> None:
    ingress_key = prefix(pod, tenant, agent, "ingress")
    dead_key = prefix(pod, tenant, agent, "dead")
    raw_items = drain_ingress(r, ingress_key)
    for raw in raw_items:
        try:
            envelope = parse(raw)
        except EnvelopeError as exc:
            r.rpush(dead_key, raw)
            _emit_for_recipient("port", "dead_lettered", {}, agent, str(exc))
            continue
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

    ingress_key = prefix(pod, tenant, agent, "ingress")
    dead_key = prefix(pod, tenant, agent, "dead")

    raw_items = drain_ingress(r, ingress_key)
    if not raw_items:
        return

    parsed_items: list[tuple[str, dict]] = []
    for raw in raw_items:
        try:
            envelope = parse(raw)
        except EnvelopeError as exc:
            r.rpush(dead_key, raw)
            try:
                header = parse_for_switch(raw)
            except EnvelopeError:
                header = {}
            _emit_for_recipient("port", "dead_lettered", header, agent, str(exc))
            continue

        _emit_for_recipient("port", "received", envelope, agent)
        parsed_items.append((raw, envelope))

    if not parsed_items:
        return

    current_message_batch: list[tuple[str, dict]] = []

    def flush_messages() -> None:
        nonlocal current_message_batch
        if not current_message_batch:
            return
        batch = current_message_batch
        current_message_batch = []
        envelopes = [env for _, env in batch]
        try:
            messages_opener(
                r=r,
                pod=pod,
                tenant=tenant,
                agent=agent,
                envelopes=envelopes,
                session_name=session_name,
                socket=socket,
            )
        except DeadLetter as exc:
            for raw_item, env in batch:
                r.rpush(dead_key, raw_item)
                _emit_for_recipient("port", "dead_lettered", env, agent, str(exc))
            return
        except Exception as exc:
            for raw_item, env in batch:
                r.rpush(dead_key, raw_item)
                _emit_for_recipient("port", "dead_lettered", env, agent, f"opener failed: {exc}")
            return

        for _, env in batch:
            _emit_for_recipient("port", "opened", env, agent)

    for raw, envelope in parsed_items:
        kind = envelope.get("kind")
        if kind == "Message":
            current_message_batch.append((raw, envelope))
        else:
            flush_messages()
            if kind == "Command":
                try:
                    command_opener(
                        r=r,
                        pod=pod,
                        tenant=tenant,
                        agent=agent,
                        envelope=envelope,
                        session_name=session_name,
                        socket=socket,
                    )
                except DeadLetter as exc:
                    r.rpush(dead_key, raw)
                    _emit_for_recipient("port", "dead_lettered", envelope, agent, str(exc))
                    continue
                except Exception as exc:
                    r.rpush(dead_key, raw)
                    _emit_for_recipient("port", "dead_lettered", envelope, agent, f"opener failed: {exc}")
                    continue
                _emit_for_recipient("port", "opened", envelope, agent)

            elif kind == "AddTicket":
                try:
                    add_ticket_opener(
                        r=r,
                        pod=pod,
                        tenant=tenant,
                        agent=agent,
                        envelope=envelope,
                        session_name=session_name,
                        socket=socket,
                    )
                except DeadLetter as exc:
                    r.rpush(dead_key, raw)
                    _emit_for_recipient("port", "dead_lettered", envelope, agent, str(exc))
                    continue
                except Exception as exc:
                    r.rpush(dead_key, raw)
                    _emit_for_recipient("port", "dead_lettered", envelope, agent, f"opener failed: {exc}")
                    continue
                _emit_for_recipient("port", "opened", envelope, agent)

            else:
                r.rpush(dead_key, raw)
                _emit_for_recipient("port", "dead_lettered", envelope, agent, f"unknown kind: {kind}")

    flush_messages()


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
