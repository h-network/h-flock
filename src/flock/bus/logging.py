"""Contract-shaped JSON line logging."""

import json
import os
import sys
from datetime import datetime, timezone

_ENVELOPE_EVENTS = {
    "sent",
    "popped",
    "forwarded",
    "producer_stamped",
    "dead_lettered",
    "received",
    "opened",
    "delivery_unjudged",
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
    byte_count: int | None = None,
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
        ("bytes", byte_count),
    ):
        if value is not None:
            record[field] = value
    line = json.dumps(record, separators=(",", ":"))
    # ⚠ Not to stdout when we are inside an agent's window. `office` runs in a
    # pane, so its stdout IS the agent's screen, and printing an envelope record
    # there hands the agent module names, stream ids and correlation ids it has
    # no use for. Measured: an agent read `{"module":"adapter",...}` out of its
    # own terminal, reasoned that envelope ids imply a broker, went looking, and
    # found Redis. HLD §5 already says these records reach the log through the
    # window file the router tails — the print was redundant as well as a
    # signpost. A daemon has no FLOCK_LOG_FILE and still prints to its stdout.
    # ⚠ `office` sets FLOCK_LOG_QUIET because it runs in an agent's PANE: its
    # stdout is the agent's screen. Printing an envelope record there hands the
    # agent module names, stream ids and correlation ids it has no use for.
    # Measured: an agent read {"module":"adapter",...} out of its own terminal,
    # reasoned that envelope ids imply a broker, went looking and found Redis.
    # The record still reaches the log through the window file the router tails
    # (HLD §5), so nothing is lost. Daemons do not set this and keep printing.
    path = os.environ.get("FLOCK_LOG_FILE")
    if os.environ.get("FLOCK_LOG_QUIET") != "1":
        # One syscall-sized write, newline included. Container daemons share
        # stdout, and print() writes the text and newline separately under
        # PYTHONUNBUFFERED; another process can land its record between them and
        # turn two valid JSON objects into one unparsable line. Records stay
        # below PIPE_BUF, so this single write is atomic against peer writers.
        # Flush separately after the complete-record write: it emits no second
        # record bytes, and keeps timely observation when PYTHONUNBUFFERED is
        # absent instead of making Dockerfile configuration part of this API.
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    try:
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
        producer=envelope.get("l2", {}).get("source"),
        recipient=envelope.get("l2", {}).get("destination"),
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
