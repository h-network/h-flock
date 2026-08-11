"""Tail CLI session logs into privacy-reduced per-agent activity streams."""

import json
from datetime import datetime, timezone
from pathlib import Path

from flock.bus import members, prefix


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _claude_events(record: dict) -> list[tuple[str, str | None]]:
    record_type = record.get("type")
    if record_type == "user":
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and content and all(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        ):
            return []
        return [("input", None)]
    if record_type != "assistant":
        return []

    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return [("output", None)]

    events = []
    if any(isinstance(block, dict) and block.get("type") == "text" for block in content):
        events.append(("output", None))
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name")
        if isinstance(name, str) and name:
            events.append(("tool", name))
    return events


def _codex_events(record: dict) -> list[tuple[str, str | None]]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    payload_type = payload.get("type")
    if record.get("type") == "event_msg":
        if payload_type == "user_message":
            return [("input", None)]
        if payload_type == "agent_message":
            return [("output", None)]
    if record.get("type") == "response_item" and payload_type in ("function_call", "custom_tool_call"):
        name = payload.get("name")
        if isinstance(name, str) and name:
            return [("tool", name)]
    return []


class ActivityTailer:
    """Make one non-blocking pass over every participant's newest session file."""

    def __init__(self, r, *, pod: str, tenant: str, home_root: str | Path = "/home/ubuntu"):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.home_root = Path(home_root)

    def _profile(self, agent: str) -> str | None:
        return _text(self.r.get(prefix(self.pod, self.tenant, agent, "profile")))

    def _cli(self, agent: str) -> str | None:
        return _text(self.r.get(prefix(self.pod, self.tenant, agent, "launch")))

    def _newest(self, agent: str) -> tuple[Path, str] | None:
        profile = self._profile(agent)
        suffix = f"-{profile}" if profile else ""
        claude = self.home_root / f".claude{suffix}" / "projects" / f"-workdir-{agent}"
        codex = self.home_root / f".codex{suffix}" / "sessions"
        cli = self._cli(agent)
        if cli == "agy":
            return None
        candidates = []
        if cli in (None, "claude"):
            candidates.extend((path, "claude") for path in claude.glob("*.jsonl"))
        if cli in (None, "codex"):
            candidates.extend((path, "codex") for path in codex.glob("**/rollout-*.jsonl"))
        regular = [(path, flavor) for path, flavor in candidates if path.is_file()]
        if not regular:
            return None
        return max(regular, key=lambda candidate: candidate[0].stat().st_mtime_ns)

    def _state(self, agent: str) -> dict[str, int]:
        raw = self.r.get(prefix(self.pod, self.tenant, agent, "activity.offset"))
        if not raw:
            return {}
        try:
            state = json.loads(_text(raw))
            offsets = state.get("offsets")
            if isinstance(offsets, dict):
                return {
                    path: offset
                    for path, offset in offsets.items()
                    if isinstance(path, str) and isinstance(offset, int) and offset >= 0
                }
            # Read the original one-path shape so an upgrade does not replay the
            # currently selected session once before writing the new map shape.
            path, offset = state["path"], state["offset"]
            if isinstance(path, str) and isinstance(offset, int) and offset >= 0:
                return {path: offset}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return {}

    def _append(self, agent: str, timestamp: str, kind: str, tool: str | None) -> None:
        event = {"v": 1, "agent": agent, "ts": timestamp, "kind": kind}
        if kind == "tool":
            event["tool"] = tool
        self.r.xadd(
            prefix(self.pod, self.tenant, agent, "activity"),
            {"event": json.dumps(event, separators=(",", ":"))},
            maxlen=1000,
            approximate=True,
        )

    def _tail(self, agent: str, path: Path, flavor: str) -> None:
        offsets = self._state(agent)
        path_text = str(path)
        offset = offsets.get(path_text, 0)
        size = path.stat().st_size
        if offset > size:
            offset = 0
        parser = _claude_events if flavor == "claude" else _codex_events

        with path.open("rb") as session:
            session.seek(offset)
            committed_offset = offset
            while raw := session.readline():
                if not raw.endswith(b"\n"):
                    break
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    committed_offset = session.tell()
                    continue
                if not isinstance(record, dict):
                    committed_offset = session.tell()
                    continue
                timestamp = record.get("timestamp")
                if not isinstance(timestamp, str) or not timestamp:
                    timestamp = _now()
                for kind, tool in parser(record):
                    self._append(agent, timestamp, kind, tool)
                committed_offset = session.tell()
            offset = committed_offset

        offsets[path_text] = offset
        state = json.dumps({"offsets": offsets}, separators=(",", ":"))
        self.r.set(prefix(self.pod, self.tenant, agent, "activity.offset"), state)

    def poll(self, agents=None) -> None:
        agents = members(self.r, pod=self.pod, tenant=self.tenant) if agents is None else agents
        for agent in sorted(agents):
            try:
                newest = self._newest(agent)
                if newest is not None:
                    self._tail(agent, *newest)
            except OSError:
                # Session rotation can remove a candidate between discovery and
                # open. The next tenant pass will discover its replacement.
                continue
