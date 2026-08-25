"""Contract-shaped JSON line logging."""

import json
import os
import sys
from datetime import datetime, timezone

_WRITER = os.environ.get("FLOCK_WRITER")

_ENVELOPE_EVENTS = {
    "sent",
    "send_unknown",
    "popped",
    "forwarded",
    "forward_unknown",
    "source_stamped",
    "kick_started",
    "kick_unknown",
    "dead_lettered",
    "received",
    "opened",
    "delivery_unjudged",
    "delivery_unverified",
}


def mirror(line: str) -> None:
    """Append one already-formatted record to the durable evidence file.

    ⚠ **Container stdout is deleted with the container.** Docker's `json-file`
    driver goes with `docker compose down`, so this file is the only thing that
    says a run happened once the tenant is gone — the failure `TEST-SIGNOFF`
    records as *"evidence /tmp/b77-build.log — torn down, no sha256"*.

    ⚠ **Call this ONLY where the same line is printed to stdout**, so the file
    stays a byte copy of what `docker logs` shows for that container's lifetime.
    A record written here *instead* of stdout is invisible to `docker logs`; a
    record written here *as well as* by another path is a duplicate, and a
    duplicated custody record is indistinguishable from a duplicated delivery to
    every conservation check we have.

    Never raises. A full or read-only evidence volume must not fail a command.
    """
    path = os.environ.get("FLOCK_CUSTODY_FILE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as evidence:
            evidence.write(line + "\n")
    except Exception:
        pass


def log_record(
    module: str,
    event: str,
    *,
    stream_id: str | None = None,
    correlation_id: str | None = None,
    source: str | None = None,
    destination: str | None = None,
    reason: str | None = None,
    count: int | None = None,
    task_id: str | None = None,
    waited: int | float | None = None,
    byte_count: int | None = None,
) -> None:
    """One JSON object per line on stdout. Fields absent when not known.

    `stream_id` belongs to envelope events only — it is the join key for one
    envelope's life, and a synthetic value on a lifecycle event makes the six
    records of a real envelope harder to find. See CONTRACTS §3.

    ⚠ This said "four" until 2026-08-22. A delivered unicast leaves SIX —
    `sent, popped, forwarded, kick_started, received, opened` — and the count in
    this file has now been stale at four, five and six in turn.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "module": module,
        "event": event,
        "writer": _WRITER or module,
    }
    if event in _ENVELOPE_EVENTS:
        # An envelope event ALWAYS carries the field, so a missing id reads as
        # `unknown` rather than as an absent key that analysis silently skips.
        record["stream_id"] = stream_id or "unknown"
    elif stream_id is not None:
        # ⚠ Any other event keeps an id the caller actually passed. This used to
        # be dropped: the allowlist gated the FIELD rather than only its default,
        # so a new event name lost its identity with no error. Ten records from a
        # test adapter collapsed into one `None` and cost a day to find. Every
        # other optional field below is "include if not None"; this now matches.
        record["stream_id"] = stream_id
    for field, value in (
        ("correlation_id", correlation_id),
        ("source", source),
        ("destination", destination),
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
    # no use for. Measured: an agent read `{"module":"port",...}` out of its
    # own terminal, reasoned that envelope ids imply a broker, went looking, and
    # found Redis. HLD §5 already says these records reach the log through the
    # window file the switch tails — the print was redundant as well as a
    # signpost. A daemon has no FLOCK_LOG_FILE and still prints to its stdout.
    # ⚠ `office` sets FLOCK_LOG_QUIET because it runs in an agent's PANE: its
    # stdout is the agent's screen. Printing an envelope record there hands the
    # agent module names, stream ids and correlation ids it has no use for.
    # Measured: an agent read {"module":"port",...} out of its own terminal,
    # reasoned that envelope ids imply a broker, went looking and found Redis.
    # The record still reaches the log through the window file the switch tails
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
        # ⚠ A DURABLE MIRROR OF STDOUT, and deliberately nothing more. Container
        # stdout is Docker's `json-file`, which is deleted with the container —
        # so before this existed, `docker compose down` destroyed the only
        # evidence a run ever happened. TEST-SIGNOFF's own REFUSED example fails
        # on exactly that: "evidence /tmp/b77-build.log — torn down, no sha256".
        # ⚠ Gated on the SAME condition as the stdout write, so the file is a
        # byte-for-byte copy of what `docker logs` shows. A pane record is
        # QUIET here and reaches the log once, when the switch re-emits the
        # window file it tails (HLD §5). Mirroring it directly as well would
        # write it TWICE, and a duplicate custody record is indistinguishable
        # from a duplicate delivery to every conservation check we have.
        mirror(line)
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
        source=envelope.get("l2", {}).get("source"),
        destination=envelope.get("l2", {}).get("destination"),
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
