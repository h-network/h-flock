"""Judge terminal-delivery markers from privacy-reduced activity events."""

import json
from datetime import datetime, timezone

from flock.bus import log_record, prefix


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _timestamp(value) -> datetime | None:
    value = _text(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fields(raw: dict) -> dict[str, str]:
    return {_text(key): _text(value) for key, value in raw.items()}


def _elapsed(now: datetime, then: datetime) -> int | float:
    seconds = max(0.0, (now - then).total_seconds())
    return int(seconds) if seconds.is_integer() else seconds


class DeliveryVerifier:
    """Confirm aged paste markers against later CLI input activity."""

    def __init__(self, r, *, pod: str, tenant: str, verify_after_seconds: float = 10.0):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.verify_after_seconds = verify_after_seconds

    def _input_times(self, agent: str) -> list[datetime]:
        entries = self.r.xrange(prefix(self.pod, self.tenant, agent, "activity"), min="-", max="+")
        result = []
        for _, raw_fields in entries:
            raw_event = _fields(raw_fields).get("event")
            try:
                event = json.loads(raw_event)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict) or event.get("kind") != "input":
                continue
            timestamp = _timestamp(event.get("ts"))
            if timestamp is not None:
                result.append(timestamp)
        return result

    def _has_activity_history(self, agent: str) -> bool:
        offset_key = prefix(self.pod, self.tenant, agent, "activity.offset")
        activity_key = prefix(self.pod, self.tenant, agent, "activity")
        return bool(self.r.exists(offset_key) or self.r.xlen(activity_key))

    def poll(self, agents, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        for agent in sorted(agents):
            pending_key = prefix(self.pod, self.tenant, agent, "pending.verify")
            blocked_key = prefix(self.pod, self.tenant, agent, "blocked")
            pending = self.r.xrange(pending_key, min="-", max="+")
            eligible = []
            for entry_id, raw_fields in pending:
                marker = _fields(raw_fields)
                marker_time = _timestamp(marker.get("ts"))
                if marker_time is None or (now - marker_time).total_seconds() < self.verify_after_seconds:
                    continue
                eligible.append((entry_id, marker, marker_time))
            if not eligible:
                continue

            if not self._has_activity_history(agent):
                for entry_id, marker, marker_time in eligible:
                    log_record(
                        "switch",
                        "delivery_unjudged",
                        stream_id=marker.get("stream_id"),
                        recipient=agent,
                        reason="agent has no activity history; first delivery is not judged",
                        waited=_elapsed(now, marker_time),
                    )
                    self.r.xdel(pending_key, entry_id)
                continue

            input_times = self._input_times(agent)
            for entry_id, marker, marker_time in eligible:
                verified = any(input_time > marker_time for input_time in input_times)
                if verified:
                    self.r.delete(blocked_key)
                else:
                    if not self.r.hgetall(blocked_key):
                        self.r.hset(
                            blocked_key,
                            mapping={
                                "since": marker.get("ts", ""),
                                "stream_id": marker.get("stream_id", ""),
                            },
                        )
                    log_record(
                        "switch",
                        "delivery_unverified",
                        stream_id=marker.get("stream_id"),
                        recipient=agent,
                        reason=(
                            "not confirmed by a later input activity event; "
                            "not retried because verification cannot distinguish "
                            "loss from a landed paste"
                        ),
                        waited=_elapsed(now, marker_time),
                    )
                self.r.xdel(pending_key, entry_id)
