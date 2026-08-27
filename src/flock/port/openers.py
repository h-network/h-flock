import json
import os
from datetime import datetime, timezone
from typing import Set

from flock.bus import DeadLetter, log_record, prefix, record_task_event
from flock.tmux import list_windows, paste_text, run_tmux

# Backwards compatibility helper for existing tests
get_tmux_windows = list_windows

# The CLIs that write a session file the switch can tail. An agent running
# anything else — a bare shell — produces no activity, so a delivery to it can
# never be confirmed and must not be marked.
#
# ⚠ `agy` joined this set once `~/.gemini/antigravity-cli/history.jsonl` was
# confirmed live and wired into `ActivityTailer` (`watchdog/activity.py`'s
# `_agy_events`) — it records every submitted input, including a paste, so the
# same "input after the marker" aliveness check that verifies claude/codex now
# applies to agy too.
VERIFIABLE_CLIS = frozenset({"claude", "codex", "agy"})


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
            maxlen=100,
            approximate=True,
        )
        # ⚠ 500 IS A SAFETY NET, NOT A POLICY, AND IT CAN LOSE ATTRIBUTION.
        # A marker trimmed here yields a usage record with no stream_id, which is
        # the degradation BUILD-82 §3 specifies — omit rather than guess — so the
        # loss is acceptable and bounded. It is NOT observable: a counter that
        # fired on every uncorrelated record was removed in review because 9 of
        # 27 uncorrelated in the live run were the normal case, and a signal
        # dominated by the normal case is the delivery_unverified defect again.
        # ⚠ Do not "fix" this with an XDEL on attribution. That was built once
        # and deleted the marker BEFORE the claim, turning a retryable XADD miss
        # into permanent loss and letting a duplicate delete a newer marker.
        r.xadd(
            markers_key,
            entry,
            maxlen=500,
            approximate=True,
        )
    except Exception:
        pass


def messages_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelopes: list[dict],
    session_name: str,
    socket: str | None = None,
) -> None:
    if not envelopes:
        return

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    blocks = []
    for envelope in envelopes:
        source = envelope.get("l2", {}).get("source", "unknown")
        payload = envelope.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
        blocks.append(f"[message from {source}] {text}\n")

    combined_msg = "".join(blocks)

    # ⚠ Mark BEFORE pasting. The CLI records its input the instant the text is
    # submitted, so a marker written afterwards can carry a later timestamp than
    # the very event meant to confirm it — a sub-second race the comparison then
    # loses. Measured: six deliveries all landed and five read unverified.
    #
    # Marking first costs nothing if the paste fails: the delivery genuinely did
    # not happen, and unverified is the right answer.
    for envelope in envelopes:
        stream_id = envelope.get("stream_id", "")
        corr_id = envelope.get("correlation_id")
        mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)

    primary_stream_id = envelopes[0].get("stream_id", "")
    paste_text(session_name, agent, combined_msg, stream_id=primary_stream_id, socket=socket)


def message_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    messages_opener(
        r=r,
        pod=pod,
        tenant=tenant,
        agent=agent,
        envelopes=[envelope],
        session_name=session_name,
        socket=socket,
    )


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
