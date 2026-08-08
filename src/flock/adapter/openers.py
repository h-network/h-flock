import json
import os
from datetime import datetime, timezone
from typing import Set

from flock.bus import prefix, log_record
from flock.tmux import list_windows, paste_text, run_tmux

# Backwards compatibility helper for existing tests
get_tmux_windows = list_windows


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


def assign_task_opener(
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

    if isinstance(payload, dict) and "id" in payload:
        task_obj = payload
        title = payload.get("title", "")
    else:
        title = payload.get("title", "") if isinstance(payload, dict) else str(payload)
        task_id = corr_id or os.urandom(4).hex()
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        task_obj = {
            "id": task_id,
            "title": title,
            "from": producer,
            "created_at": created_at,
        }

    todo_key = prefix(pod, tenant, agent=agent, resource="tasks.todo")
    r.rpush(todo_key, json.dumps(task_obj))
