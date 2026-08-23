"""Tail CLI session logs into privacy-reduced per-agent activity streams."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flock.bus import members, mirror, prefix


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _fields(raw: dict) -> dict[str, str]:
    return {_text(key): _text(value) for key, value in raw.items()}


def _timestamp(value) -> datetime | None:
    value = _text(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _claude_usage(record: dict) -> dict | None:
    record_type = record.get("type")
    if record_type != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    model = str(message.get("model") or record.get("model") or "unknown")
    request_id = str(message.get("id") or record.get("requestId") or record.get("id") or "")
    return {
        "cli": "claude",
        "model": model,
        "request_id": request_id,
        "input": int(usage.get("input_tokens", 0) or 0),
        "cache_read": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_write": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "output": int(usage.get("output_tokens", 0) or 0),
    }


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


def _codex_usage(record: dict, current_model: str = "") -> dict | None:
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else record
    record_type = str(record.get("type", ""))
    payload_type = str(payload.get("type", ""))

    usage = None
    if record_type == "token_count" or payload_type == "token_count":
        # ⚠ `last_token_usage`, NEVER `total_token_usage`. Measured on a live
        # codex session 2026-08-23: total is CUMULATIVE for the session and last
        # is that turn alone. Two records read total 14,373 then 28,908 while
        # last read 14,373 then 14,535 — so summing total across records gives
        # 43,281 for a session that used 28,908. One usage record is emitted per
        # parsed record and they are summed, so the per-turn figure is the only
        # correct one.
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        for key in ("last_token_usage", "usage"):
            if isinstance(info.get(key), dict):
                usage = info[key]
                break
        # ⚠ It used to take `payload` itself here, which carries no counts at
        # all — they are two levels down. Every codex record therefore emitted
        # zeros under model `unknown`, which reads in a cost table exactly like
        # an agent that ran and cost nothing.
    elif isinstance(payload.get("usage"), dict):
        usage = payload.get("usage")
    elif isinstance(payload.get("info", {}).get("usage"), dict):
        usage = payload["info"]["usage"]
    elif "input_tokens" in payload or "prompt_tokens" in payload:
        usage = payload

    if usage is None:
        return None

    # ⚠ A record carrying no tokens is not a usage record. codex writes
    # token_count events during startup and teardown whose counts are all zero;
    # emitting them makes an agent that did nothing appear in a cost table under
    # a model nobody can identify.
    if not any(
        int(usage.get(k) or 0)
        for k in ("input_tokens", "prompt_tokens", "input",
                  "cached_input_tokens", "cache_read_input_tokens",
                  "output_tokens", "completion_tokens", "output")
    ):
        return None

    model = current_model or str(payload.get("model") or record.get("model") or "unknown")
    request_id = str(payload.get("request_id") or payload.get("id") or record.get("id") or "")

    input_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input", 0)
        or 0
    )
    cache_read = int(
        usage.get("cached_tokens")
        or usage.get("cached_input_tokens")   # codex's spelling
        or usage.get("cache_read_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cache_read", 0)
        or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        or 0
    )
    cache_write = int(
        usage.get("cache_write_tokens")
        or usage.get("cache_write_input_tokens")   # codex's spelling
        or usage.get("cache_creation_input_tokens")
        or usage.get("cache_write", 0)
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("output", 0)
        or 0
    )

    rate_limits = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else (
        record.get("rate_limits") if isinstance(record.get("rate_limits"), dict) else None
    )

    usage_dict = {
        "cli": "codex",
        "model": model,
        "request_id": request_id,
        "input": input_tokens,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": output_tokens,
    }
    if rate_limits:
        usage_dict["rate_limits"] = rate_limits
    return usage_dict


_EMIT_USAGE_LUA = """
local stream_key = KEYS[1]
local seen_key = KEYS[2]
local attributed_key = KEYS[3]

local request_id = ARGV[1]
local raw_usage = ARGV[2]
local stream_id = ARGV[3]
local maxlen = tonumber(ARGV[4]) or 10000

if request_id ~= "" and seen_key ~= "" then
    local is_seen = redis.call("SISMEMBER", seen_key, request_id)
    if is_seen == 1 then
        return 0
    end
end

redis.call("XADD", stream_key, "MAXLEN", "~", maxlen, "*", "usage", raw_usage)

if request_id ~= "" and seen_key ~= "" then
    redis.call("SADD", seen_key, request_id)
end

if stream_id ~= "" and attributed_key ~= "" then
    redis.call("SADD", attributed_key, stream_id)
end

return 1
"""


class ActivityTailer:
    """Make one non-blocking pass over every participant's newest session file."""

    def __init__(self, r, *, pod: str, tenant: str, home_root: str | Path = "/home/ubuntu"):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.home_root = Path(home_root)
        import collections
        self._seen_requests: dict[str, set[str]] = collections.defaultdict(set)
        self._attributed_markers: dict[str, set[str]] = collections.defaultdict(set)
        self._codex_model: dict[str, str] = collections.defaultdict(str)

    def _profile(self, agent: str) -> str | None:
        return _text(self.r.get(prefix(self.pod, self.tenant, agent, "profile")))

    def _cli(self, agent: str) -> str | None:
        return _text(self.r.get(prefix(self.pod, self.tenant, agent, "launch")))

    @staticmethod
    def _codex_session_belongs_to(path: Path, agent: str) -> bool:
        """Use Codex's own session metadata or turn context to assign a shared rollout.

        CODEX_HOME is an account directory, so agents on the default account or
        the same named profile legitimately share its sessions directory.  A
        rollout without a matching workspace is therefore unknown, not safe to
        attribute to whichever agent happens to inspect it first.
        """
        try:
            with path.open("rb") as session:
                for _ in range(10):
                    raw = session.readline()
                    if not raw:
                        break
                    try:
                        record = json.loads(raw)
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(record, dict):
                        continue
                    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                    cwd = payload.get("cwd")
                    if isinstance(cwd, str) and (cwd == f"/workdir/{agent}" or cwd == f"-workdir-{agent}" or cwd.endswith(f"/{agent}")):
                        return True
        except OSError:
            return False
        return False

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
        regular = [
            (path, flavor)
            for path, flavor in candidates
            if path.is_file() and (flavor != "codex" or self._codex_session_belongs_to(path, agent))
        ]
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

    def _correlate_delivery(self, agent: str, usage_ts: str) -> tuple[str | None, str | None]:
        """Correlate usage timestamp with preceding delivery marker (Build 82 §3).

        Heuristic: the first usage record for agent A after the marker for
        stream_id S, and before the next marker for A, is S's turn.
        An agent receiving two messages during one turn produces one usage
        record; only the latest marker gets attributed, and subsequent usage
        records without new markers receive no attribution.
        """
        usage_time = _timestamp(usage_ts)
        if usage_time is None:
            return None, None

        markers_key = prefix(self.pod, self.tenant, agent, "delivery.markers")
        verify_key = prefix(self.pod, self.tenant, agent, "pending.verify")
        attributed_key = prefix(self.pod, self.tenant, agent, "usage.attributed")

        raw_entries = []
        if hasattr(self.r, "xrange"):
            try:
                raw_entries.extend(self.r.xrange(markers_key, min="-", max="+"))
            except Exception:
                pass
            try:
                raw_entries.extend(self.r.xrange(verify_key, min="-", max="+"))
            except Exception:
                pass
        elif hasattr(self.r, "streams"):
            raw_entries.extend(self.r.streams.get(markers_key, []))
            raw_entries.extend(self.r.streams.get(verify_key, []))

        candidates = []
        seen_sids = set()
        for item in raw_entries:
            entry_id = item[0] if isinstance(item, tuple) and len(item) == 2 else None
            raw_fields = item[1] if isinstance(item, tuple) and len(item) == 2 else item
            fields = _fields(raw_fields) if hasattr(raw_fields, "items") else {}
            sid = fields.get("stream_id")
            if not sid or sid in seen_sids:
                continue
            seen_sids.add(sid)
            m_time = _timestamp(fields.get("ts"))
            if m_time is not None and m_time <= usage_time:
                candidates.append((m_time, sid, fields.get("correlation_id"), entry_id))

        if not candidates:
            return None, None

        def _parse_eid(eid):
            if eid is None:
                return (0, 0)
            if isinstance(eid, bytes):
                eid = eid.decode("utf-8", "replace")
            parts = str(eid).split("-")
            try:
                return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except ValueError:
                return (0, 0)

        candidates.sort(key=lambda item: (item[0], _parse_eid(item[3])))
        _, stream_id, correlation_id, _ = candidates[-1]

        if stream_id in self._attributed_markers[agent]:
            return None, None

        if hasattr(self.r, "sismember"):
            try:
                if self.r.sismember(attributed_key, stream_id):
                    self._attributed_markers[agent].add(stream_id)
                    return None, None
            except Exception:
                pass

        return stream_id, correlation_id

    def _emit_usage(self, agent: str, timestamp: str, usage: dict) -> None:
        request_id = usage.get("request_id") or ""
        seen_key = prefix(self.pod, self.tenant, agent, "usage.requests") if request_id else ""
        if request_id and request_id in self._seen_requests[agent]:
            return

        stream_id, correlation_id = self._correlate_delivery(agent, timestamp)
        stream_id_str = stream_id or ""
        attributed_key = prefix(self.pod, self.tenant, agent, "usage.attributed") if stream_id else ""

        record = {
            "module": "watchdog",
            "event": "usage",
            "writer": "usage",
            "agent": agent,
            "cli": usage["cli"],
            "model": usage["model"],
            "input": usage["input"],
            "cache_read": usage["cache_read"],
            "cache_write": usage["cache_write"],
            "output": usage["output"],
            "ts": timestamp,
        }
        if stream_id:
            record["stream_id"] = stream_id
        if correlation_id:
            record["correlation_id"] = correlation_id
        if "rate_limits" in usage:
            record["rate_limits"] = usage["rate_limits"]

        raw = json.dumps(record, separators=(",", ":"))
        usage_stream = prefix(self.pod, self.tenant, resource="usage")

        emitted = False
        if hasattr(self.r, "eval"):
            try:
                res = self.r.eval(
                    _EMIT_USAGE_LUA,
                    3,
                    usage_stream,
                    seen_key or "",
                    attributed_key or "",
                    request_id,
                    raw,
                    stream_id_str,
                    10000,
                )
                if res == 0:
                    if request_id:
                        self._seen_requests[agent].add(request_id)
                    return
                emitted = bool(res)
            except Exception:
                return
        elif hasattr(self.r, "xadd"):
            if request_id and hasattr(self.r, "sismember"):
                try:
                    if self.r.sismember(seen_key, request_id):
                        self._seen_requests[agent].add(request_id)
                        return
                except Exception:
                    pass
            try:
                self.r.xadd(usage_stream, {"usage": raw}, maxlen=10000, approximate=True)
                if request_id and hasattr(self.r, "sadd"):
                    self.r.sadd(seen_key, request_id)
                if stream_id and hasattr(self.r, "sadd"):
                    self.r.sadd(attributed_key, stream_id)
                emitted = True
            except Exception:
                return
        else:
            return

        if not emitted:
            return

        if request_id:
            self._seen_requests[agent].add(request_id)
        if stream_id:
            self._attributed_markers[agent].add(stream_id)

        if os.environ.get("FLOCK_LOG_QUIET") != "1":
            sys.stdout.write(raw + "\n")
            sys.stdout.flush()
            mirror(raw)

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

                if flavor == "codex":
                    rtype = record.get("type")
                    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                    if rtype == "turn_context":
                        m = payload.get("model")
                        if isinstance(m, str) and m:
                            self._codex_model[agent] = m
                    elif rtype == "session_meta" and not self._codex_model[agent]:
                        base_inst = payload.get("base_instructions") if isinstance(payload.get("base_instructions"), dict) else {}
                        prov = base_inst.get("provenance") if isinstance(base_inst.get("provenance"), dict) else {}
                        m = prov.get("model") or payload.get("model")
                        if isinstance(m, str) and m:
                            self._codex_model[agent] = m

                timestamp = record.get("timestamp")
                if not isinstance(timestamp, str) or not timestamp:
                    timestamp = _now()
                for kind, tool in parser(record):
                    self._append(agent, timestamp, kind, tool)

                if flavor == "codex":
                    usage = _codex_usage(record, current_model=self._codex_model.get(agent, ""))
                else:
                    usage = _claude_usage(record)

                if usage is not None:
                    self._emit_usage(agent, timestamp, usage)
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
