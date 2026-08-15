"""Version-four frames with a reserved fixed-width header and opaque JSON body."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from .keys import prefix

VERSION = "4"
IDENTIFIER_WIDTH = 32
NAME_WIDTH = 63
SOURCE_START = 65
DESTINATION_START = 128
TTL_START = 191
HOPS_START = 194
RESERVED_START = 197
HEADER_WIDTH = 256
DEFAULT_TTL = 16


class EnvelopeError(ValueError):
    """Raised when a wire value is not a valid frame."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
    _segment(pod, "pod")
    _segment(tenant, "tenant")
    local_source = _segment(source, "source")
    return f"{pod}:{tenant}:{local_source}", local_source


def _identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != IDENTIFIER_WIDTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EnvelopeError(f"{field} must be {IDENTIFIER_WIDTH} lowercase hex characters")
    return value


def _counter(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise EnvelopeError(f"{field} must be an integer from 0 through 999")
    return value


def _parse_counter(text: str, field: str, default: int) -> int:
    # All spaces means absent, allowing an older sender with the same frozen
    # header width to leave a field unallocated.
    if text == "   ":
        return default
    if len(text) != 3 or not text.isascii() or not text.isdigit():
        raise EnvelopeError(f"{field} must be three ASCII digits or spaces")
    return int(text)


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
    """Construct a valid v4 frame after resolving its destination locally."""
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
        "v": 4,
        "kind": kind,
        "stream_id": uuid4().hex,
        "correlation_id": correlation_id,
        "ts": _timestamp(),
        "l2": {"source": source, "destination": l2_destination},
        "ttl": DEFAULT_TTL,
        "hops": 0,
        "l3": {"source": l3_source, "destination": l3_destination},
        "payload": payload,
    }


def _validate_body(frame: dict) -> None:
    if not isinstance(frame.get("kind"), str) or not frame["kind"]:
        raise EnvelopeError("kind must be a non-empty string")
    if not isinstance(frame.get("ts"), str) or not frame["ts"]:
        raise EnvelopeError("ts must be a non-empty string")
    l3 = frame.get("l3")
    if not isinstance(l3, dict):
        raise EnvelopeError("l3 must be an object")
    _address(l3.get("source"), "L3 source")
    _address(l3.get("destination"), "L3 destination", broadcast=True)
    if not isinstance(frame.get("payload"), dict):
        raise EnvelopeError("payload must be an object")


def encode(frame: dict) -> str:
    """Serialize a validated frame into the fixed header plus compact JSON body."""
    if not isinstance(frame, dict) or frame.get("v") != 4:
        raise EnvelopeError("unsupported frame version")
    stream_id = _identifier(frame.get("stream_id"), "stream_id")
    correlation_id = _identifier(frame.get("correlation_id"), "correlation_id")
    l2 = frame.get("l2")
    if not isinstance(l2, dict):
        raise EnvelopeError("l2 must be an object")
    source = _segment(l2.get("source"), "L2 source")
    destination = l2.get("destination")
    if destination != "all":
        destination = _segment(destination, "L2 destination")
    ttl = _counter(frame.get("ttl", DEFAULT_TTL), "ttl")
    hops = _counter(frame.get("hops", 0), "hops")
    _validate_body(frame)
    body = {field: frame[field] for field in ("kind", "ts", "l3", "payload")}
    return (
        VERSION
        + stream_id
        + correlation_id
        + source.ljust(NAME_WIDTH)
        + destination.ljust(NAME_WIDTH)
        + f"{ttl:03d}"
        + f"{hops:03d}"
        + " " * (HEADER_WIDTH - RESERVED_START)
        + json.dumps(body, separators=(",", ":"))
    )


def _wire_text(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EnvelopeError("frame is not UTF-8") from exc
    if not isinstance(raw, str):
        raise EnvelopeError("frame must be text")
    return raw


def _header_text(raw: str | bytes) -> str:
    """Decode only the fixed ASCII header; the body is opaque to the switch."""
    if isinstance(raw, bytes):
        try:
            return raw[:HEADER_WIDTH].decode("ascii")
        except UnicodeDecodeError as exc:
            raise EnvelopeError("frame header is not ASCII") from exc
    if not isinstance(raw, str):
        raise EnvelopeError("frame must be text")
    return raw[:HEADER_WIDTH]


def header_record_fields(raw: str | bytes) -> dict:
    """Return best-effort fields for the immediate, pre-validation pop record."""
    try:
        text = _header_text(raw)
    except EnvelopeError:
        return {}
    if len(text) < HEADER_WIDTH:
        return {}
    return {
        "stream_id": text[1:33],
        "correlation_id": text[33:65],
        "source": text[SOURCE_START:DESTINATION_START].rstrip(),
        "destination": text[DESTINATION_START:TTL_START].rstrip(),
    }


def parse_for_switch(raw: str | bytes) -> dict:
    """Validate and return only the fixed header used for local forwarding."""
    text = _header_text(raw)
    if len(text) < HEADER_WIDTH:
        raise EnvelopeError("frame is shorter than the v4 header")
    if text[0] != VERSION:
        raise EnvelopeError("unsupported frame version")
    stream_id = _identifier(text[1:33], "stream_id")
    correlation_id = _identifier(text[33:65], "correlation_id")
    source = _segment(text[SOURCE_START:DESTINATION_START].rstrip(), "L2 source")
    destination = text[DESTINATION_START:TTL_START].rstrip()
    if destination != "all":
        destination = _segment(destination, "L2 destination")
    ttl = _parse_counter(text[TTL_START:HOPS_START], "ttl", DEFAULT_TTL)
    hops = _parse_counter(text[HOPS_START:RESERVED_START], "hops", 0)
    return {
        "v": 4,
        "stream_id": stream_id,
        "correlation_id": correlation_id,
        "l2": {"source": source, "destination": destination},
        "ttl": ttl,
        "hops": hops,
    }


def stamp_source(raw: str | bytes, source: str) -> str | bytes:
    """Replace only the fixed-width L2 source, preserving every body byte."""
    padded = _segment(source, "L2 source").ljust(NAME_WIDTH)
    if isinstance(raw, bytes):
        return raw[:SOURCE_START] + padded.encode("ascii") + raw[DESTINATION_START:]
    text = _wire_text(raw)
    return text[:SOURCE_START] + padded + text[DESTINATION_START:]


def advance_hop(raw: str | bytes, envelope: dict) -> str | bytes:
    """Decrement TTL and increment hops by fixed-offset splices only."""
    ttl = _counter(envelope.get("ttl"), "ttl")
    hops = _counter(envelope.get("hops"), "hops")
    if hops == 999:
        raise EnvelopeError("hops cannot exceed 999")
    ttl = max(0, ttl - 1)
    hops += 1
    envelope["ttl"] = ttl
    envelope["hops"] = hops
    counters = f"{ttl:03d}{hops:03d}"
    if isinstance(raw, bytes):
        return raw[:TTL_START] + counters.encode("ascii") + raw[RESERVED_START:]
    text = _wire_text(raw)
    return text[:TTL_START] + counters + text[RESERVED_START:]


def parse(raw: str | bytes) -> dict:
    """Parse and validate the header and body consumed at the port boundary."""
    text = _wire_text(raw)
    header = parse_for_switch(text)
    try:
        body = json.loads(text[HEADER_WIDTH:])
    except (json.JSONDecodeError, TypeError) as exc:
        raise EnvelopeError("frame body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise EnvelopeError("frame body must be an object")
    _validate_body(body)
    return {**header, **body}
