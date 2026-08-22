import json
import os
from datetime import datetime, timezone
from typing import Set

from flock.bus import DeadLetter, log_record, prefix, record_task_event
from flock.tmux import list_windows, paste_text, run_tmux

# Backwards compatibility helper for existing tests
get_tmux_windows = list_windows

# The CLIs that write a session file the switch can tail. An agent running
# anything else — agy, a bare shell — produces no activity, so a delivery to it
# can never be confirmed and must not be marked.
VERIFIABLE_CLIS = frozenset({"claude", "codex"})


def mark_delivery_pending(
    r,
    pod: str,
    tenant: str,
    agent: str,
    stream_id: str,
    correlation_id: str | None = None,
) -> None:
    """Record a pending delivery verification marker for a tmux paste (claude/codex only)."""
    try:
        if not stream_id:
            return
        # ⚠ An allowlist, not "everything except agy". A marker is only useful
        # for a CLI whose activity we can tail, and anything else can never be
        # confirmed — so it would report unverified forever.
        #
        # Measured: a denylist marked bash windows too (an agent with no launch
        # key at all), and three of the first four unverified records in a live
        # run were those. A CLI we cannot tail must be skipped by default, not
        # by having been remembered.
        launch_key = prefix(pod, tenant, agent=agent, resource="launch")
        raw_cli = r.get(launch_key)
        cli = (raw_cli.decode() if isinstance(raw_cli, bytes) else str(raw_cli)) if raw_cli else ""
        if cli not in VERIFIABLE_CLIS:
            return

        verify_key = prefix(pod, tenant, agent=agent, resource="pending.verify")
        markers_key = prefix(pod, tenant, agent=agent, resource="delivery.markers")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        entry = {"stream_id": stream_id, "ts": ts}
        if correlation_id:
            entry["correlation_id"] = correlation_id
        r.xadd(
            verify_key,
            entry,
        )
        r.xadd(
            markers_key,
            entry,
        )
    except Exception:
        pass


def message_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    stream_id = envelope.get("stream_id", "")
    corr_id = envelope.get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    text = payload.get("text", "")
    formatted_msg = f"[message from {source}] {text}\n"
    # ⚠ Mark BEFORE pasting. The CLI records its input the instant the text is
    # submitted, so a marker written afterwards can carry a later timestamp than
    # the very event meant to confirm it — a sub-second race the comparison then
    # loses. Measured: six deliveries all landed and five read unverified.
    #
    # Marking first costs nothing if the paste fails: the delivery genuinely did
    # not happen, and unverified is the right answer.
    mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)
    paste_text(session_name, agent, formatted_msg, stream_id=stream_id, socket=socket)


def command_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    stream_id = envelope.get("stream_id", "")
    corr_id = envelope.get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    text = payload.get("text", "")
    formatted_msg = f"{text}\n"
    # ⚠ Mark BEFORE pasting. The CLI records its input the instant the text is
    # submitted, so a marker written afterwards can carry a later timestamp than
    # the very event meant to confirm it — a sub-second race the comparison then
    # loses. Measured: six deliveries all landed and five read unverified.
    #
    # Marking first costs nothing if the paste fails: the delivery genuinely did
    # not happen, and unverified is the right answer.
    mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)
    paste_text(session_name, agent, formatted_msg, stream_id=stream_id, socket=socket)


def add_ticket_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    corr_id = envelope.get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})

    if isinstance(payload, dict) and "v" in payload and "id" in payload:
        ticket_obj = payload
    elif isinstance(payload, dict) and "id" in payload:
        ticket_obj = {
            "v": 1,
            "id": payload.get("id", corr_id or os.urandom(4).hex()),
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "created_by": payload.get("created_by", payload.get("from", source)),
            "status": payload.get("status", "todo"),
            "created_ts": payload.get("created_ts", payload.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")),
            "started_ts": payload.get("started_ts", ""),
            "done_ts": payload.get("done_ts", ""),
            "priority": payload.get("priority", "normal"),
        }
    else:
        title = payload.get("title", "") if isinstance(payload, dict) else str(payload)
        description = payload.get("description", "") if isinstance(payload, dict) else ""
        priority = payload.get("priority", "normal") if isinstance(payload, dict) else "normal"
        task_id = corr_id or os.urandom(4).hex()
        created_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ticket_obj = {
            "v": 1,
            "id": task_id,
            "title": title,
            "description": description,
            "created_by": source,
            "status": "todo",
            "created_ts": created_ts,
            "started_ts": "",
            "done_ts": "",
            "priority": priority,
        }

    todo_key = prefix(pod, tenant, agent=agent, resource="tasks.todo")
    try:
        depth = r.rpush(todo_key, json.dumps(ticket_obj))
    except Exception as exc:
        log_record(
            "port",
            "board_write_failed",
            correlation_id=corr_id,
            destination=agent,
            reason=str(exc),
            task_id=ticket_obj.get("id", ""),
        )
        raise DeadLetter("board_write_failed") from exc
    if not isinstance(depth, int) or depth < 1:
        log_record(
            "port",
            "board_write_failed",
            correlation_id=corr_id,
            destination=agent,
            reason="RPUSH did not return a positive list length",
            task_id=ticket_obj.get("id", ""),
        )
        raise DeadLetter("board_write_failed")

    log_record(
        "port",
        "board_write_confirmed",
        correlation_id=corr_id,
        destination=agent,
        count=depth,
        task_id=ticket_obj.get("id", ""),
    )

    record_task_event(
        "add",
        id=ticket_obj.get("id", ""),
        title=ticket_obj.get("title", ""),
        agent=agent,
        actor=source,
        timestamp=ticket_obj.get("created_ts"),
    )
