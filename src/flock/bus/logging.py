"""Contract-shaped JSON line logging."""

import json
from datetime import datetime, timezone

_ENVELOPE_EVENTS = {"sent", "popped", "forwarded", "dead_lettered", "received", "opened"}


def log_record(
    module: str,
    event: str,
    *,
    stream_id: str | None = None,
    correlation_id: str | None = None,
    producer: str | None = None,
    recipient: str | None = None,
    reason: str | None = None,
    count: int | None = None,
) -> None:
    """One JSON object per line on stdout. Fields absent when not known.

    `stream_id` belongs to the six envelope events only — it is the join key for
    one envelope's life, and a synthetic value on a lifecycle event makes the
    four records of a real envelope harder to find. See CONTRACTS §3.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "module": module,
        "event": event,
    }
    if event in _ENVELOPE_EVENTS:
        record["stream_id"] = stream_id or "unknown"
    for field, value in (
        ("correlation_id", correlation_id),
        ("producer", producer),
        ("recipient", recipient),
        ("reason", reason),
        ("count", count),
    ):
        if value is not None:
            record[field] = value
    print(json.dumps(record, separators=(",", ":")), flush=True)


def emit(
    module: str,
    event: str,
    envelope: dict,
    reason: str | None = None,
    count: int | None = None,
) -> None:
    """`log_record` for the case where the fields come off an envelope."""
    log_record(
        module,
        event,
        stream_id=envelope.get("stream_id"),
        correlation_id=envelope.get("correlation_id"),
        producer=envelope.get("producer"),
        recipient=envelope.get("recipient"),
        reason=reason,
        count=count,
    )
