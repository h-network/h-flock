"""Delivery actions shared by more than one port type."""

import json
import math
import os
import re
from datetime import datetime, timezone

from flock.bus import DeadLetter, log_record, prefix, record_task_event


# Attachment wire/schema limits shared by tmux and OpenShell delivery.
ATTACHMENT_MAX_BYTES = 10_485_760  # 10 MiB
ATTACHMENT_MAX_BASE64_CHARS = 4 * math.ceil(ATTACHMENT_MAX_BYTES / 3)  # 13_981_016
MIME_TYPE_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$")
BASE64_CHARS_REGEX = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


def add_ticket_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
) -> None:
    """Write an AddTicket envelope to the recipient's board."""
    corr_id = envelope.get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})

    def _related(source_dict) -> list[str]:
        # Stored, never validated: a related id may live on another agent's
        # board entirely, and this opener has no cross-board lookup.
        raw = source_dict.get("related") if isinstance(source_dict, dict) else None
        return [value for value in raw if isinstance(value, str)] if isinstance(raw, list) else []

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
        related = _related(payload)
        if related:
            ticket_obj["related"] = related
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
        related = _related(payload)
        if related:
            ticket_obj["related"] = related

    todo_key = prefix(pod, tenant, agent=agent, resource="tasks.todo")
    try:
        depth = r.rpush(todo_key, json.dumps(ticket_obj))
    except Exception as exc:
        log_record(
            "port",
            "board_write_unknown",
            correlation_id=corr_id,
            destination=agent,
            reason=f"board write outcome UNKNOWN after {exc}",
            task_id=ticket_obj.get("id", ""),
        )
        raise DeadLetter("board_write_unknown") from exc
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
