import json
import uuid
from datetime import datetime, timezone


class EnvelopeError(Exception):
    """Raised when parsing or validating an envelope fails."""
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build(
    kind: str,
    producer: str,
    recipient: str,
    payload: dict,
    correlation_id: str | None = None,
) -> dict:
    stream_id = uuid.uuid4().hex
    if not correlation_id:
        correlation_id = uuid.uuid4().hex
    return {
        "v": 1,
        "kind": kind,
        "stream_id": stream_id,
        "correlation_id": correlation_id,
        "ts": _now_iso(),
        "producer": producer,
        "recipient": recipient,
        "payload": payload if payload is not None else {},
    }


def parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except Exception as e:
        raise EnvelopeError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise EnvelopeError("Envelope must be a JSON object")

    required_fields = ["v", "kind", "stream_id", "producer", "recipient", "payload"]
    for field in required_fields:
        if field not in data:
            raise EnvelopeError(f"Missing required envelope field: {field}")

    return data
