"""The bus's two queue doors."""

import json
from collections.abc import Callable

from .envelope import EnvelopeError, build, parse
from .keys import prefix
from .logging import emit, log_record


class DeadLetter(Exception):
    """Signal that an opener rejected an envelope after receive took custody."""


def send(
    r,
    *,
    pod: str,
    tenant: str,
    source: str,
    destination: str,
    payload: dict,
    kind: str = "Message",
    correlation_id: str | None = None,
    module: str = "bus",
) -> str:
    try:
        envelope = build(
            kind, source, destination, payload, correlation_id, pod=pod, tenant=tenant
        )
    except EnvelopeError as exc:
        log_record(
            module,
            "send_refused",
            source=source,
            destination=destination,
            reason=str(exc),
        )
        raise
    r.rpush(prefix(pod, tenant, source, "egress"), json.dumps(envelope, separators=(",", ":")))
    emit(module, "sent", envelope)
    return envelope["stream_id"]


def receive(
    r,
    *,
    pod: str,
    tenant: str,
    agent: str,
    openers: dict[str, Callable[[dict], None]],
    timeout: int,
    blocking: bool = True,
    module: str = "port",
) -> None:
    ingress_key = prefix(pod, tenant, agent, "ingress")
    if blocking:
        item = r.blpop(ingress_key, timeout=timeout)
        raw = None if item is None else item[1]
    else:
        raw = r.lpop(ingress_key)
    if raw is None:
        return
    try:
        envelope = parse(raw)
    except EnvelopeError as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        emit(module, "dead_lettered", {}, str(exc))
        return
    emit(module, "received", envelope)
    opener = openers.get(envelope["kind"])
    if opener is None:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        emit(module, "dead_lettered", envelope, f"unknown kind: {envelope['kind']}")
        return
    try:
        opener(envelope)
    except DeadLetter as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        emit(module, "dead_lettered", envelope, str(exc))
        return
    except Exception as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        emit(module, "dead_lettered", envelope, f"opener failed: {exc}")
        return
    emit(module, "opened", envelope)
