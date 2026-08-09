"""Report tenant stalls and blocked deliveries without repairing either."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

from flock.bus import members, prefix, vab
from flock.tmux import run_tmux


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _timestamp(value) -> datetime | None:
    value = _text(value)
    if not value:
        return None
    try:
        if value.replace(".", "", 1).isdigit():
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fields(raw: dict) -> dict[str, str]:
    return {_text(key): _text(value) for key, value in raw.items()}


class Watchdog:
    def __init__(
        self,
        r,
        *,
        pod: str,
        tenant: str,
        session_name: str,
        socket: str | None = None,
        stall_seconds: float = 600,
        silence_seconds: float = 300,
        cooldown_seconds: int = 3600,
        credential_warn_days: int = 7,
        home_root: str | Path = "/home/ubuntu",
    ):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.session_name = session_name
        self.socket = socket
        self.stall_seconds = stall_seconds
        self.silence_seconds = silence_seconds
        self.cooldown_seconds = cooldown_seconds
        self.credential_warn_days = credential_warn_days
        self.home_root = Path(home_root)

    def _agents(self) -> list[str]:
        return sorted(
            agent
            for agent in members(self.r, pod=self.pod, tenant=self.tenant)
            if vab(self.r, pod=self.pod, tenant=self.tenant, agent=agent) == "tmux"
        )

    def _window_activity(self) -> dict[str, int]:
        rc, output, _ = run_tmux(
            "list-windows",
            "-t",
            self.session_name,
            "-F",
            "#{window_name}\t#{window_activity}",
            socket=self.socket,
        )
        if rc:
            return {}
        result = {}
        for line in output.splitlines():
            try:
                name, activity = line.rsplit("\t", 1)
                result[name] = int(activity)
            except ValueError:
                continue
        return result

    def _alert(self, record: dict) -> None:
        raw = json.dumps(record, separators=(",", ":"))
        self.r.xadd(
            prefix(self.pod, self.tenant, resource="alerts"),
            {"alert": raw},
            maxlen=1000,
            approximate=True,
        )
        print(raw, flush=True)

    def _ticket(self, agent: str) -> dict | None:
        raw = self.r.lindex(prefix(self.pod, self.tenant, agent, "tasks.doing"), 0)
        try:
            ticket = json.loads(_text(raw))
        except (TypeError, json.JSONDecodeError):
            return None
        return ticket if isinstance(ticket, dict) else None

    def _presence(self, agent: str) -> dict[str, str]:
        return _fields(self.r.hgetall(prefix(self.pod, self.tenant, agent, "presence")) or {})

    def _check_stalls(self, agents: list[str], windows: dict[str, int], now: datetime) -> None:
        now_s = now.timestamp()
        for agent in agents:
            ticket = self._ticket(agent)
            if not ticket or not isinstance(ticket.get("title"), str):
                continue
            started = _timestamp(ticket.get("started_ts"))
            if started is None:
                continue
            doing_age = int((now - started).total_seconds())
            if doing_age < self.stall_seconds:
                continue

            presence = self._presence(agent)
            if presence.get("state") == "working":
                continue
            unchecked = []
            last_activity = _timestamp(presence.get("last_activity"))
            if presence.get("state") == "unknown" or last_activity is None:
                no_activity = None
                unchecked.append("activity")
            else:
                no_activity = max(0, int((now - last_activity).total_seconds()))

            window_activity = windows.get(agent)
            if window_activity is None:
                continue
            no_output = max(0, int(now_s - window_activity))
            if no_output < self.silence_seconds:
                continue

            ticket_id = ticket.get("id")
            if not isinstance(ticket_id, str) or not ticket_id:
                continue
            alerted_key = prefix(self.pod, self.tenant, agent, "alerted")
            if _text(self.r.get(alerted_key)) == ticket_id:
                continue
            record = {
                "v": 1,
                "ts": _iso(now),
                "kind": "stalled",
                "agent": agent,
                "ticket": ticket["title"],
                "doing_age_s": doing_age,
                "no_activity_s": no_activity,
                "no_output_s": no_output,
                "unchecked": unchecked,
            }
            self._alert(record)
            self.r.set(alerted_key, ticket_id, ex=self.cooldown_seconds)

    def _pane_contains_delivery(self, agent: str) -> bool | None:
        rc, output, _ = run_tmux(
            "capture-pane", "-p", "-t", f"{self.session_name}:{agent}", socket=self.socket
        )
        if rc:
            return None
        return "[message from " in output

    def _check_blocked(self, agents: list[str], now: datetime) -> None:
        for agent in agents:
            blocked_key = prefix(self.pod, self.tenant, agent, "blocked")
            blocked = _fields(self.r.hgetall(blocked_key) or {})
            unconsumed = self._pane_contains_delivery(agent)
            if unconsumed is None:
                continue
            if not unconsumed:
                if blocked:
                    self.r.delete(blocked_key)
                continue
            if blocked:
                continue
            # A pending marker may still be present, but it is optional context,
            # never the trigger: the router deletes it after ten seconds and a
            # watchdog pass must remain correct after that.
            markers = self.r.xrange(prefix(self.pod, self.tenant, agent, "pending.verify"), min="-", max="+")
            marker = _fields(markers[-1][1]) if markers else {}
            since = marker.get("ts") or _iso(now)
            stream_id = marker.get("stream_id", "")
            self.r.hset(blocked_key, mapping={"since": since, "stream_id": stream_id})
            self._alert(
                {
                    "v": 1,
                    "ts": _iso(now),
                    "kind": "blocked",
                    "agent": agent,
                    "since": since,
                    "stream_id": stream_id,
                    "unsubmitted": "[message from ",
                }
            )

    def poll(self, *, now: datetime | None = None) -> None:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        agents = self._agents()
        windows = self._window_activity()
        self._check_stalls(agents, windows, now)
        self._check_blocked(agents, now)

    def _credential_accounts(self) -> list[tuple[str, str, Path]]:
        result = [
            ("default", "claude", self.home_root / ".claude" / ".credentials.json"),
            ("default", "agy", self.home_root / ".gemini/antigravity-cli/antigravity-oauth-token"),
            ("default", "codex", self.home_root / ".codex" / "auth.json"),
        ]
        profiles = {
            path.name.removeprefix(".claude-")
            for path in self.home_root.glob(".claude-*")
            if path.is_dir()
        }
        profiles.update(
            path.name.removeprefix(".codex-")
            for path in self.home_root.glob(".codex-*")
            if path.is_dir()
        )
        for profile in sorted(profiles):
            result.append((profile, "claude", self.home_root / f".claude-{profile}" / ".credentials.json"))
            result.append((profile, "codex", self.home_root / f".codex-{profile}" / "auth.json"))
        return result

    def check_credentials(self, *, now: datetime | None = None) -> None:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        warn_seconds = self.credential_warn_days * 86400
        for account, cli, path in self._credential_accounts():
            if cli == "codex":
                status, expiry = "unknown", None
            else:
                try:
                    data = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                raw_expiry = (
                    data.get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
                    if cli == "claude"
                    else data.get("token", {}).get("expiry")
                )
                expiry = _timestamp(raw_expiry)
                if expiry is None:
                    status = "unknown"
                elif (expiry - now).total_seconds() <= warn_seconds:
                    status = "expiring"
                else:
                    continue
            record = {
                "v": 1,
                "ts": _iso(now),
                "kind": "credential",
                "account": account,
                "cli": cli,
                "status": status,
                "expires_ts": _iso(expiry) if expiry else None,
            }
            self._alert(record)


def main() -> None:
    if os.environ.get("WATCHDOG_ENABLED", "1") == "0":
        return
    interval = float(os.environ.get("WATCHDOG_INTERVAL", "30"))
    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    watchdog = Watchdog(
        r,
        pod=os.environ["POD"],
        tenant=os.environ["TENANT"],
        session_name=os.environ.get("TMUX_SESSION", os.environ["TENANT"]),
        socket=os.environ.get("TMUX_SOCKET"),
        stall_seconds=float(os.environ.get("WATCHDOG_STALL_SEC", "600")),
        silence_seconds=float(os.environ.get("WATCHDOG_SILENCE_SEC", "300")),
        cooldown_seconds=int(os.environ.get("WATCHDOG_COOLDOWN_SEC", "3600")),
        credential_warn_days=int(os.environ.get("WATCHDOG_CREDENTIAL_WARN_DAYS", "7")),
    )
    next_credentials = 0.0
    while True:
        try:
            watchdog.poll()
            if time.monotonic() >= next_credentials:
                watchdog.check_credentials()
                next_credentials = time.monotonic() + 3600
        except Exception as exc:
            print(json.dumps({"module": "watchdog", "event": "error", "reason": type(exc).__name__}), flush=True)
        time.sleep(interval)
