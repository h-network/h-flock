"""Sample per-agent presence from the privacy-reduced activity stream."""

import json
from datetime import datetime, timedelta, timezone

from flock.bus import prefix


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


def _format(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class PresenceSampler:
    """Write one current state per agent without waiting on any agent."""

    def __init__(self, r, *, pod: str, tenant: str, working_seconds: float = 30.0):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.working_seconds = working_seconds

    def _tailable(self, agent: str) -> bool:
        """Whether this agent's CLI writes a session file we can read.

        ⚠ The difference between "nothing to see" and "nothing seen yet".
        Without it a freshly hired, authenticated agent reads `unknown` — the
        same answer as a bare shell — so a client cannot tell a ready agent from
        an unknowable one until it happens to do something.

        ⚠ `agy` joined `claude`/`codex` here once `~/.gemini/antigravity-cli/
        history.jsonl` was confirmed live (`ActivityTailer._agy_events`) — it
        only carries `input`, never `output`/`tool`, but that is enough for
        `working`/`idle` the same way it is enough for verification's aliveness
        check: recency of *any* activity, not which kind.
        """
        launch = _text(self.r.get(prefix(self.pod, self.tenant, agent, "launch")))
        return launch in ("claude", "codex", "agy")

    def _last_activity(self, agent: str) -> datetime | None:
        if not self._tailable(agent):
            return None
        key = prefix(self.pod, self.tenant, agent, "activity")
        # Activity is written by our own tailer, but scan a small newest-first
        # batch so one malformed observation does not erase otherwise known
        # presence. The Stream itself can hold roughly 1,000 entries; fetching
        # all of them every pass to obtain one timestamp is unnecessary.
        for _, fields in self.r.xrevrange(key, max="+", min="-", count=10):
            raw = fields.get(b"event", fields.get("event"))
            try:
                event = json.loads(_text(raw))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            timestamp = _timestamp(event.get("ts"))
            if timestamp is not None:
                return timestamp
        return None

    def poll(self, agents, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        for agent in sorted(agents):
            last = self._last_activity(agent)
            if last is None:
                # A tailable CLI with an empty feed has not spoken yet; that is
                # idle. Only an agent whose activity we could never see is
                # unknown.
                state = "idle" if self._tailable(agent) else "unknown"
                entered = now
                last_text = ""
            elif (now - last).total_seconds() <= self.working_seconds:
                state = "working"
                entered = last
                last_text = _format(last)
            else:
                state = "idle"
                entered = last + timedelta(seconds=self.working_seconds)
                last_text = _format(last)

            key = prefix(self.pod, self.tenant, agent, "presence")
            existing_raw = self.r.hgetall(key)
            existing = {_text(field): _text(value) for field, value in existing_raw.items()}
            if existing.get("state") == state and existing.get("since"):
                since = existing["since"]
            else:
                since = _format(entered)
            self.r.hset(
                key,
                mapping={"state": state, "since": since, "last_activity": last_text},
            )
