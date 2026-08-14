"""The bus's two queue doors."""

import json
from collections.abc import Callable

from .envelope import EnvelopeError, build, parse, resolve_destination, resolve_source
from .keys import prefix
from .logging import emit, log_record
from .policy import require_allowed


class DeadLetter(Exception):
    """Signal that an opener rejected an envelope after receive took custody."""


def _emit_for_recipient(
    module: str,
    event: str,
    envelope: dict,
    recipient: str,
    reason: str | None = None,
) -> None:
    """Emit receive-side custody about the actual participant, not L2 fan-out."""
    log_record(
        module,
        event,
        stream_id=envelope.get("stream_id"),
        correlation_id=envelope.get("correlation_id"),
        source=envelope.get("l2", {}).get("source"),
        destination=recipient,
        reason=reason,
    )


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
        _, local_source = resolve_source(pod=pod, tenant=tenant, source=source)
        _, local_destination = resolve_destination(
            pod=pod, tenant=tenant, destination=destination
        )
        if local_destination != "all":
            require_allowed(
                r,
                pod=pod,
                tenant=tenant,
                source=local_source,
                destination=local_destination,
            )
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
    try:
        r.rpush(
            prefix(pod, tenant, source, "egress"),
            json.dumps(envelope, separators=(",", ":")),
        )
    except Exception as exc:
        emit(module, "send_failed", envelope, f"egress write failed: {exc}")
        raise
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
        _emit_for_recipient(module, "dead_lettered", {}, agent, str(exc))
        return
    _emit_for_recipient(module, "received", envelope, agent)
    opener = openers.get(envelope["kind"])
    if opener is None:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        _emit_for_recipient(
            module, "dead_lettered", envelope, agent, f"unknown kind: {envelope['kind']}"
        )
        return
    try:
        opener(envelope)
    except DeadLetter as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        _emit_for_recipient(module, "dead_lettered", envelope, agent, str(exc))
        return
    except Exception as exc:
        r.rpush(prefix(pod, tenant, agent, "dead"), raw)
        _emit_for_recipient(
            module, "dead_lettered", envelope, agent, f"opener failed: {exc}"
        )
        return
    _emit_for_recipient(module, "opened", envelope, agent)
