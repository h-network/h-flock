"""The bus's two queue doors."""

import json
from collections.abc import Callable
from datetime import datetime, timezone

from .envelope import (
    EnvelopeError,
    build,
    encode,
    parse,
    parse_for_switch,
    resolve_destination,
    resolve_source,
)
from .keys import prefix
from .logging import emit, log_record
from .policy import require_allowed
from .roster import port_type

# Kinds a client can plausibly be owed a reply for. `Command`, `AddTicket` and
# similar structured kinds are never sent by a client and would only ever
# reset a count that could not have been opened.
_UNREPLIED_KINDS = {"Message", "Attachment"}


def _unreplied_key(pod: str, tenant: str, agent: str) -> str:
    return prefix(pod, tenant, agent=agent, resource="unreplied")


def _track_unreplied(r, *, pod: str, tenant: str, source: str, destination: str, kind: str) -> None:
    """Open or clear a tmux agent's per-client unanswered-message count.

    ⚠ Reads both port types itself, via two fresh roster HGETs — it does NOT
    reuse work `require_allowed` above already did. That call checks policy
    export/import *tags*, a separate hash, and never touches port_type. This
    docstring previously claimed otherwise; corrected after `bus`'s
    module-boundary sweep caught the discrepancy. A client (`api` port_type,
    e.g. `telegram`) sending to a tmux agent opens or extends a count; that
    same agent sending anything back to the same client closes it outright.
    Peer traffic between two tmux agents never touches this key: ticket age
    already covers that responsiveness question via the watchdog's
    doing/todo/hold family (LLD-watchdog §2a-c). See LLD-watchdog §2d.
    """
    if kind not in _UNREPLIED_KINDS or destination == "all":
        return
    source_type = port_type(r, pod=pod, tenant=tenant, agent=source)
    destination_type = port_type(r, pod=pod, tenant=tenant, agent=destination)
    if source_type == "api" and destination_type == "tmux":
        key = _unreplied_key(pod, tenant, destination)
        count = 1
        since = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        existing = r.hget(key, source)
        if existing:
            try:
                data = json.loads(existing)
                count = int(data["count"]) + 1
                since = data["since"] or since
            except (TypeError, ValueError, KeyError):
                pass
        r.hset(key, source, json.dumps({"count": count, "since": since}, separators=(",", ":")))
    elif source_type == "tmux" and destination_type == "api":
        r.hdel(_unreplied_key(pod, tenant, source), destination)


class DeadLetter(Exception):
    """Signal that an opener rejected an envelope after receive took custody."""


def _emit_observation(
    module: str, event: str, envelope: dict, reason: str | None = None
) -> None:
    """Keep a logging fault from replacing the observed operation's result."""
    try:
        emit(module, event, envelope, reason)
    except Exception:
        # Logging is secondary observation: it must neither turn a committed
        # handover into failure nor replace an outcome-unknown Redis exception.
        pass


def _emit_for_recipient(
    module: str,
    event: str,
    envelope: dict,
    recipient: str,
    reason: str | None = None,
) -> None:
    """Best-effort receive custody about the participant, not L2 fan-out."""
    try:
        log_record(
            module,
            event,
            stream_id=envelope.get("stream_id"),
            correlation_id=envelope.get("correlation_id"),
            source=envelope.get("l2", {}).get("source"),
            destination=recipient,
            reason=reason,
        )
    except Exception:
        # receive() and burst delivery have already destructively popped or
        # drained ingress. Observation cannot strand that accepted custody.
        pass


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
    # Finish every operation that can provably fail before Redis is called.
    # Only RPUSH belongs inside the outcome-unknown window: prefix/encoding
    # errors prove that no queue write was attempted.
    egress_key = prefix(pod, tenant, source, "egress")
    raw = encode(envelope)
    try:
        r.rpush(egress_key, raw)
    except Exception as exc:
        _emit_observation(
            module,
            "send_unknown",
            envelope,
            f"egress write outcome UNKNOWN after {exc}",
        )
        raise
    _emit_observation(module, "sent", envelope)
    # The message is already durably enqueued above; this bookkeeping is a
    # secondary effect and must never make a successful send look failed to
    # the caller, so a fault here is logged and swallowed, not raised.
    try:
        _track_unreplied(
            r, pod=pod, tenant=tenant, source=local_source, destination=local_destination, kind=kind
        )
    except Exception as exc:
        _emit_observation(
            module,
            "unreplied_tracking_failed",
            envelope,
            f"unreplied bookkeeping failed: {exc}",
        )
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
        # A valid v4 header remains joinable when its corrupt body is rejected
        # here. A malformed header has no trustworthy custody identifiers.
        try:
            header = parse_for_switch(raw)
        except EnvelopeError:
            header = {}
        _emit_for_recipient(module, "dead_lettered", header, agent, str(exc))
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
