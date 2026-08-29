"""The bus's two queue doors."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

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
_ACK_WINDOW_SECONDS = 120
_ACK_PHRASES = frozenset(
    {
        "ack", "acknowledged", "appreciate it", "got it", "much appreciated",
        "no problem", "noted", "np", "ok", "okay", "roger", "roger that",
        "sounds good", "thank you", "thanks", "thanks a lot", "understood",
        "will do",
    }
)

_INCREMENT_UNREPLIED = """
-- flock unreplied increment v1
local count = 1
local since = ARGV[2]
local existing = redis.call('HGET', KEYS[1], ARGV[1])
if existing then
    local ok, data = pcall(cjson.decode, existing)
    if ok and type(data) == 'table' and tonumber(data['count'])
       and type(data['since']) == 'string' and data['since'] ~= '' then
        count = tonumber(data['count']) + 1
        since = data['since']
        if ARGV[2] < since then
            since = ARGV[2]
        end
    end
end
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode({count=count, since=since}))
return count
"""

_UPDATE_ACK_STREAK = """
-- flock ack streak v1
local streak = 1
local existing = redis.call('HGET', KEYS[1], ARGV[1])
if existing then
    local ok, data = pcall(cjson.decode, existing)
    if ok and type(data) == 'table' and tonumber(data['streak'])
       and type(data['last_ts']) == 'string'
       and data['last_ts'] >= ARGV[3] and data['last_ts'] <= ARGV[2] then
        streak = tonumber(data['streak']) + 1
    end
end
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode({streak=streak, last_ts=ARGV[2]}))
return streak
"""


def _unreplied_key(pod: str, tenant: str, agent: str) -> str:
    return prefix(pod, tenant, agent=agent, resource="unreplied")


def _increment_unreplied(r, *, key: str, client: str, since: str) -> None:
    """Atomically increment one client backlog while preserving first since."""
    r.eval(_INCREMENT_UNREPLIED, 1, key, client, since)


def _is_ack_shaped(text) -> bool:
    """Apply the frozen v1 closing-acknowledgment classifier."""
    if not isinstance(text, str):
        return False
    trimmed = text.strip()
    if len(trimmed) > 80 or "?" in trimmed:
        return False
    normalized = " ".join(trimmed.split()).casefold().rstrip(".!").rstrip()
    if len(normalized.split()) > 12:
        return False
    return normalized in _ACK_PHRASES


def _acks_key(pod: str, tenant: str, source: str) -> str:
    return prefix(pod, tenant, agent=source, resource="acks")


def _update_ack_streak(
    r, *, key: str, destination: str, now_ts: str, cutoff_ts: str
) -> None:
    r.eval(_UPDATE_ACK_STREAK, 1, key, destination, now_ts, cutoff_ts)


def _track_ack_loop(
    r, *, pod: str, tenant: str, source: str, destination: str,
    kind: str, payload: dict, now: datetime | None = None,
) -> None:
    """Track ack-shaped Message streaks on one directed tmux peer edge."""
    if kind != "Message" or destination == "all":
        return
    if port_type(r, pod=pod, tenant=tenant, agent=source) != "tmux":
        return
    if port_type(r, pod=pod, tenant=tenant, agent=destination) != "tmux":
        return
    key = _acks_key(pod, tenant, source)
    if not _is_ack_shaped(payload.get("text")):
        r.hdel(key, destination)
        return
    current = now or datetime.now(timezone.utc)
    now_ts = current.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cutoff_ts = (current - timedelta(seconds=_ACK_WINDOW_SECONDS)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    _update_ack_streak(
        r, key=key, destination=destination, now_ts=now_ts, cutoff_ts=cutoff_ts
    )


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
    if destination == "all":
        return
    source_type = port_type(r, pod=pod, tenant=tenant, agent=source)
    destination_type = port_type(r, pod=pod, tenant=tenant, agent=destination)
    if (
        source_type == "api"
        and destination_type == "tmux"
        and kind in _UNREPLIED_KINDS
    ):
        key = _unreplied_key(pod, tenant, destination)
        since = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        _increment_unreplied(r, key=key, client=source, since=since)
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
    try:
        _track_ack_loop(
            r, pod=pod, tenant=tenant, source=local_source,
            destination=local_destination, kind=kind, payload=payload,
        )
    except Exception as exc:
        _emit_observation(
            module,
            "ack_tracking_failed",
            envelope,
            f"ack-loop bookkeeping failed: {exc}",
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
