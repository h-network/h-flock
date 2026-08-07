"""Contract-shaped JSON line logging."""

import json
from datetime import datetime, timezone

_ENVELOPE_EVENTS = {"sent", "popped", "forwarded", "dead_lettered", "received", "opened"}


def emit(
    module: str,
    event: str,
    envelope: dict,
    reason: str | None = None,
    count: int | None = None,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "module": module,
        "event": event,
    }
    if event in _ENVELOPE_EVENTS:
        record["stream_id"] = envelope.get("stream_id", "unknown")
    for field in ("correlation_id", "producer", "recipient"):
        if field in envelope:
            record[field] = envelope[field]
    if reason is not None:
        record["reason"] = reason
    if count is not None:
        record["count"] = count
    print(json.dumps(record, separators=(",", ":")), flush=True)
