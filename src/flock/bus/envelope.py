"""Version-two layered wire frames."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from .keys import prefix


class EnvelopeError(ValueError):
    """Raised when a wire value is not a valid frame."""


def _timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _segment(value: object, field: str = "agent") -> str:
    try:
        prefix("check", "check", agent=value)  # type: ignore[arg-type]
    except KeyError as exc:
        raise EnvelopeError(f"invalid {field} name: {value!r}") from exc
    return value  # type: ignore[return-value]


def _address(value: object, field: str, *, broadcast: bool = False) -> tuple[str, str, str]:
    if broadcast and value == "all":
        return "", "", "all"
    if not isinstance(value, str):
        raise EnvelopeError(f"invalid {field} address: {value!r}")
    parts = value.split(":")
    if len(parts) != 3:
        raise EnvelopeError(f"{field} must be a qualified pod:tenant:agent address")
    pod, tenant, agent = parts
    _segment(pod, "pod")
    _segment(tenant, "tenant")
    if not (broadcast and agent == "all"):
        _segment(agent)
    return pod, tenant, agent


def resolve_destination(*, pod: str, tenant: str, destination: str) -> tuple[str, str]:
    """Return qualified L3 and local L2 destinations, or reject non-local L3."""
    _segment(pod, "pod")
    _segment(tenant, "tenant")
    if destination == "all":
        return f"{pod}:{tenant}:all", "all"
    if ":" not in destination:
        agent = _segment(destination)
        return f"{pod}:{tenant}:{agent}", agent
    dst_pod, dst_tenant, agent = _address(destination, "destination")
    if (dst_pod, dst_tenant) != (pod, tenant):
        raise EnvelopeError(f"no route to non-local destination {destination!r}")
    return destination, agent


def resolve_source(*, pod: str, tenant: str, source: str) -> tuple[str, str]:
    """Return qualified L3 and local L2 source names."""
    _segment(pod, "pod")
    _segment(tenant, "tenant")
    local_source = _segment(source, "source")
    return f"{pod}:{tenant}:{local_source}", local_source


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or any(c not in "0123456789abcdef" for c in value):
        raise EnvelopeError(f"{field} must be non-empty lowercase hex")
    return value


def build(
    kind: str,
    source: str,
    destination: str,
    payload: dict,
    correlation_id: str | None = None,
    *,
    pod: str = "default",
    tenant: str = "default",
) -> dict:
    """Construct a valid v2 frame after resolving its destination locally."""
    if not isinstance(kind, str) or not kind:
        raise EnvelopeError("kind must be a non-empty string")
    l3_source, source = resolve_source(pod=pod, tenant=tenant, source=source)
    l3_destination, l2_destination = resolve_destination(
        pod=pod, tenant=tenant, destination=destination
    )
    if not isinstance(payload, dict):
        raise EnvelopeError("payload must be an object")
    correlation_id = uuid4().hex if correlation_id is None else _identifier(correlation_id, "correlation_id")
    return {
        "v": 2,
        "kind": kind,
        "stream_id": uuid4().hex,
        "correlation_id": correlation_id,
        "ts": _timestamp(),
        "l2": {"source": source, "destination": l2_destination},
        "l3": {
            "source": l3_source,
            "destination": l3_destination,
        },
        "payload": payload,
    }


def _decode(raw: str) -> dict:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EnvelopeError("frame is not UTF-8") from exc
    if not isinstance(raw, str):
        raise EnvelopeError("frame must be text")
    try:
        frame = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EnvelopeError("frame is not valid JSON") from exc
    if not isinstance(frame, dict):
        raise EnvelopeError("frame must be an object")
    if frame.get("v") != 2:
        raise EnvelopeError("unsupported frame version")
    if not isinstance(frame.get("kind"), str) or not frame["kind"]:
        raise EnvelopeError("kind must be a non-empty string")
    _identifier(frame.get("stream_id"), "stream_id")
    _identifier(frame.get("correlation_id"), "correlation_id")
    if not isinstance(frame.get("ts"), str) or not frame["ts"]:
        raise EnvelopeError("ts must be a non-empty string")
    return frame


def parse_for_switch(raw: str) -> dict:
    """Validate only the common and L2 fields used for local forwarding."""
    frame = _decode(raw)
    l2 = frame.get("l2")
    if not isinstance(l2, dict):
        raise EnvelopeError("l2 must be an object")
    _segment(l2.get("source"), "L2 source")
    if l2.get("destination") != "all":
        _segment(l2.get("destination"), "L2 destination")
    return frame


def parse(raw: str) -> dict:
    """Parse and validate every field consumed at the adapter boundary."""
    frame = parse_for_switch(raw)
    l3 = frame.get("l3")
    if not isinstance(l3, dict):
        raise EnvelopeError("l3 must be an object")
    _address(l3.get("source"), "L3 source")
    _address(l3.get("destination"), "L3 destination", broadcast=True)
    if not isinstance(frame.get("payload"), dict):
        raise EnvelopeError("payload must be an object")
    return frame
