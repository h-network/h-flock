import json
import os
from datetime import datetime, timezone
from typing import Set

from flock.bus import prefix, log_record, record_task_event
from flock.tmux import list_windows, paste_text, run_tmux

# Backwards compatibility helper for existing tests
get_tmux_windows = list_windows


def mark_delivery_pending(
    r,
    pod: str,
    tenant: str,
    agent: str,
    stream_id: str,
) -> None:
    """Record a pending delivery verification marker for a tmux paste (claude/codex only)."""
    try:
        if not stream_id:
            return
        launch_key = prefix(pod, tenant, agent=agent, resource="launch")
        raw_cli = r.get(launch_key)
        if raw_cli:
            cli = raw_cli.decode() if isinstance(raw_cli, bytes) else str(raw_cli)
            if cli == "agy":
                return

        verify_key = prefix(pod, tenant, agent=agent, resource="pending_verify")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        r.xadd(
            verify_key,
            {"stream_id": stream_id, "ts": ts},
            maxlen=100,
            approximate=True,
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
    producer = envelope.get("producer", "unknown")
    payload = envelope.get("payload", {})

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        dead_key = prefix(pod, tenant, agent=agent, resource="dead")
        r.rpush(dead_key, json.dumps(envelope))
        log_record(
            module="adapter",
            event="dead_lettered",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=agent,
            reason="window_missing",
        )
        return

    text = payload.get("text", "")
    formatted_msg = f"[message from {producer}] {text}\n"
    paste_text(session_name, agent, formatted_msg, stream_id=stream_id, socket=socket)
    mark_delivery_pending(r, pod, tenant, agent, stream_id)


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
    producer = envelope.get("producer", "unknown")
    payload = envelope.get("payload", {})

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        dead_key = prefix(pod, tenant, agent=agent, resource="dead")
        r.rpush(dead_key, json.dumps(envelope))
        log_record(
            module="adapter",
            event="dead_lettered",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=agent,
            reason="window_missing",
        )
        return

    text = payload.get("text", "")
    formatted_msg = f"{text}\n"
    paste_text(session_name, agent, formatted_msg, stream_id=stream_id, socket=socket)
    mark_delivery_pending(r, pod, tenant, agent, stream_id)


def add_ticket_opener(
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
    producer = envelope.get("producer", "unknown")
    payload = envelope.get("payload", {})
    kind = envelope.get("kind", "AddTicket")

    if kind == "AssignTask":
        log_record(
            module="adapter",
            event="deprecated_kind",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=agent,
            reason="AssignTask is deprecated, use AddTicket",
        )

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        dead_key = prefix(pod, tenant, agent=agent, resource="dead")
        r.rpush(dead_key, json.dumps(envelope))
        log_record(
            module="adapter",
            event="dead_lettered",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=agent,
            reason="window_missing",
        )
        return

    if isinstance(payload, dict) and "v" in payload and "id" in payload:
        ticket_obj = payload
    elif isinstance(payload, dict) and "id" in payload:
        ticket_obj = {
            "v": 1,
            "id": payload.get("id", corr_id or os.urandom(4).hex()),
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "created_by": payload.get("created_by", payload.get("from", producer)),
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
            "created_by": producer,
            "status": "todo",
            "created_ts": created_ts,
            "started_ts": "",
            "done_ts": "",
            "priority": priority,
        }

    todo_key = prefix(pod, tenant, agent=agent, resource="tasks.todo")
    r.rpush(todo_key, json.dumps(ticket_obj))

    record_task_event(
        "add",
        id=ticket_obj.get("id", ""),
        title=ticket_obj.get("title", ""),
        agent=agent,
        actor=producer,
        timestamp=ticket_obj.get("created_ts"),
    )


# Alias for backward compatibility
assign_task_opener = add_ticket_opener
