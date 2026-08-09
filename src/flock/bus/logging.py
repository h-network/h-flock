"""Contract-shaped JSON line logging."""

import json
import os
from datetime import datetime, timezone

_ENVELOPE_EVENTS = {
    "sent",
    "popped",
    "forwarded",
    "dead_lettered",
    "received",
    "opened",
    "delivery_unverified",
}


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
    task_id: str | None = None,
    waited: int | float | None = None,
) -> None:
    """One JSON object per line on stdout. Fields absent when not known.

    `stream_id` belongs to envelope events only — it is the join key for one
    envelope's life, and a synthetic value on a lifecycle event makes the four
    records of a real envelope harder to find. See CONTRACTS §3.
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
        ("task_id", task_id),
        ("waited", waited),
    ):
        if value is not None:
            record[field] = value
    line = json.dumps(record, separators=(",", ":"))
    print(line, flush=True)
    try:
        path = os.environ.get("FLOCK_LOG_FILE")
        agent_only = os.environ.get("FLOCK_LOG_FILE_AGENT_ONLY")
        if path and (not agent_only or os.environ.get("AGENT_NAME")):
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        # A central observation failing must never turn into a failed command.
        pass


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


def record_task_event(
    event: str,
    *,
    id: str,
    title: str,
    agent: str,
    actor: str,
    timestamp: str | None = None,
) -> None:
    """Append one board-history event without ever breaking its command."""
    try:
        path = os.environ.get("TASK_RECORD", "/home/ubuntu/.flock/tasks.jsonl")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        record = {
            "event": event,
            "id": id,
            "title": title,
            "agent": agent,
            "actor": actor,
            "timestamp": timestamp
            or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:
        pass
