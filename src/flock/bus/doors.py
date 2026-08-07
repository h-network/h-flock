"""The bus's two queue doors."""

import json
from collections.abc import Callable

from .envelope import EnvelopeError, build, parse
from .keys import prefix
from .logging import emit


def send(
    r,
    *,
    pod: str,
    tenant: str,
    producer: str,
    recipient: str,
    payload: dict,
    kind: str = "Message",
    correlation_id: str | None = None,
    module: str = "bus",
) -> str:
    envelope = build(kind, producer, recipient, payload, correlation_id)
    r.rpush(prefix(pod, tenant, producer, "egress"), json.dumps(envelope, separators=(",", ":")))
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
    module: str = "adapter",
) -> None:
    item = r.blpop(prefix(pod, tenant, agent, "ingress"), timeout=timeout)
    if item is None:
        return
    raw = item[1]
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
    except Exception as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        emit(module, "dead_lettered", envelope, f"opener failed: {exc}")
        return
    emit(module, "opened", envelope)
