"""Version-one wire envelopes."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from .keys import prefix


class EnvelopeError(ValueError):
    """Raised when a wire value is not a valid envelope."""


def _timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _agent_name(value: object) -> str:
    try:
        prefix("check", "check", agent=value)  # type: ignore[arg-type]
    except KeyError as exc:
        raise EnvelopeError(f"invalid agent name: {value!r}") from exc
    return value  # type: ignore[return-value]


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or any(c not in "0123456789abcdef" for c in value):
        raise EnvelopeError(f"{field} must be non-empty lowercase hex")
    return value


def build(
    kind: str,
    producer: str,
    recipient: str,
    payload: dict,
    correlation_id: str | None = None,
) -> dict:
    """Construct a valid v1 envelope, propagating or minting its correlation id."""
    if not isinstance(kind, str) or not kind:
        raise EnvelopeError("kind must be a non-empty string")
    producer = _agent_name(producer)
    recipient = "all" if recipient == "all" else _agent_name(recipient)
    if not isinstance(payload, dict):
        raise EnvelopeError("payload must be an object")
    correlation_id = uuid4().hex if correlation_id is None else _identifier(correlation_id, "correlation_id")
    return {
        "v": 1,
        "kind": kind,
        "stream_id": uuid4().hex,
        "correlation_id": correlation_id,
        "ts": _timestamp(),
        "producer": producer,
        "recipient": recipient,
        "payload": payload,
    }


def parse(raw: str) -> dict:
    """Parse and validate a v1 JSON envelope; ignore unknown outer fields."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EnvelopeError("envelope is not UTF-8") from exc
    if not isinstance(raw, str):
        raise EnvelopeError("envelope must be text")
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EnvelopeError("envelope is not valid JSON") from exc
    if not isinstance(envelope, dict):
        raise EnvelopeError("envelope must be an object")
    if envelope.get("v") != 1:
        raise EnvelopeError("unsupported envelope version")
    if not isinstance(envelope.get("kind"), str) or not envelope["kind"]:
        raise EnvelopeError("kind must be a non-empty string")
    _identifier(envelope.get("stream_id"), "stream_id")
    _identifier(envelope.get("correlation_id"), "correlation_id")
    if not isinstance(envelope.get("ts"), str) or not envelope["ts"]:
        raise EnvelopeError("ts must be a non-empty string")
    _agent_name(envelope.get("producer"))
    if envelope.get("recipient") != "all":
        _agent_name(envelope.get("recipient"))
    if not isinstance(envelope.get("payload"), dict):
        raise EnvelopeError("payload must be an object")
    return envelope
