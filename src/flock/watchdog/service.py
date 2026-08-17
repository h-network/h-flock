"""Report tenant stalls and blocked deliveries without repairing either."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

from flock.bus import members, prefix, port_type
from flock.watchdog.activity import ActivityTailer
from flock.watchdog.presence import PresenceSampler
from flock.watchdog.verification import DeliveryVerifier
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
        self._reported_blocks: set[tuple[str, str, str]] = set()

    def _agents(self) -> list[str]:
        return sorted(
            agent
            for agent in members(self.r, pod=self.pod, tenant=self.tenant)
            if port_type(self.r, pod=self.pod, tenant=self.tenant, agent=agent) == "tmux"
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

    @staticmethod
    def _error(job: str, exc: Exception) -> None:
        print(
            json.dumps(
                {
                    "module": "watchdog",
                    "event": "error",
                    "job": job,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _ticket(self, agent: str) -> dict | None:
        raw = self.r.lindex(prefix(self.pod, self.tenant, agent, "tasks.doing"), 0)
        try:
            ticket = json.loads(_text(raw))
        except (TypeError, json.JSONDecodeError):
            return None
        return ticket if isinstance(ticket, dict) else None

    def _presence(self, agent: str) -> dict[str, str]:
        return _fields(self.r.hgetall(prefix(self.pod, self.tenant, agent, "presence")) or {})

    def _blocked(self, agent: str, now: datetime) -> dict | None:
        blocked = _fields(self.r.hgetall(prefix(self.pod, self.tenant, agent, "blocked")) or {})
        since = _timestamp(blocked.get("since"))
        if since is None:
            return None
        return {
            "since": blocked["since"],
            "stream_id": blocked.get("stream_id", ""),
            "unconsumed_s": max(0, int((now - since).total_seconds())),
        }

    def _check_blocked(self, agents: list[str], now: datetime) -> None:
        current = set()
        for agent in agents:
            blocked = self._blocked(agent, now)
            if blocked is None:
                continue
            identity = (agent, blocked["since"], blocked["stream_id"])
            current.add(identity)
            if identity in self._reported_blocks:
                continue
            self._alert({"v": 1, "ts": _iso(now), "kind": "blocked", "agent": agent, **blocked})
        self._reported_blocks.intersection_update(current)
        self._reported_blocks.update(current)

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
                no_output = None
                window_missing = True
            else:
                no_output = max(0, int(now_s - window_activity))
                window_missing = False
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
            if window_missing:
                record["window_missing"] = True
            blocked = self._blocked(agent, now)
            if blocked is not None:
                record["blocked"] = blocked
            self._alert(record)
            self.r.set(alerted_key, ticket_id, ex=self.cooldown_seconds)

    def poll(self, *, now: datetime | None = None) -> None:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        agents = self._agents()
        try:
            windows = self._window_activity()
        except Exception as exc:
            self._error("window_activity", exc)
            windows = {}
        try:
            self._check_stalls(agents, windows, now)
        except Exception as exc:
            self._error("stalls", exc)
        try:
            self._check_blocked(agents, now)
        except Exception as exc:
            self._error("blocked", exc)

    def _credential_accounts(self) -> list[tuple[str, str, Path]]:
        """Return each CLI account used by an enrolled terminal agent once."""
        result = set()
        for agent in self._agents():
            provider = _text(self.r.get(prefix(self.pod, self.tenant, agent, "provider")))
            if provider:
                # Local provider agents talk to the configured model server and
                # intentionally use no vendor account credential.
                continue
            cli = _text(self.r.get(prefix(self.pod, self.tenant, agent, "launch")))
            if cli not in {"agy", "claude", "codex"}:
                continue
            profile = _text(self.r.get(prefix(self.pod, self.tenant, agent, "profile")))
            account = profile or "default"
            if cli == "claude":
                directory = ".claude" if account == "default" else f".claude-{account}"
                path = self.home_root / directory / ".credentials.json"
            elif cli == "codex":
                directory = ".codex" if account == "default" else f".codex-{account}"
                path = self.home_root / directory / "auth.json"
            else:
                # agy has one non-relocatable account, regardless of profile.
                account = "default"
                path = self.home_root / ".gemini/antigravity-cli/antigravity-oauth-token"
            result.add((account, cli, path))
        return sorted(result, key=lambda item: (item[0], item[1]))

    def check_credentials(self, *, now: datetime | None = None) -> None:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        warn_seconds = self.credential_warn_days * 86400
        alerted_key = prefix(self.pod, self.tenant, resource="credential.alerted")
        current_fields = set()
        for account, cli, path in self._credential_accounts():
            field = f"{account}:{cli}"
            current_fields.add(field)
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                status, expiry = "absent", None
            else:
                if not isinstance(data, dict):
                    status, expiry = "absent", None
                elif cli != "claude":
                    status, expiry = "unknown", None
                # ⚠ Only claude records a REFRESH token expiry. agy's
                # `token.expiry` tracks its ACCESS token, which the CLI refreshes
                # by itself — measured: the same file read hours apart on two
                # machines showed the value moving forward while the login stayed
                # valid. Alerting on it fires constantly and correctly, which is
                # exactly the cry-wolf failure this check exists to avoid.
                #
                # So agy joins codex as unknown. Two of three CLIs cannot be
                # checked, and saying so is the honest answer.
                elif cli == "claude":
                    raw_expiry = data.get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
                    expiry = _timestamp(raw_expiry)
                    if expiry is None:
                        status = "unknown"
                    elif (expiry - now).total_seconds() <= 0:
                        status = "expired"
                    elif (expiry - now).total_seconds() <= warn_seconds:
                        status = "expiring"
                    else:
                        self.r.hdel(alerted_key, field)
                        continue
            if _text(self.r.hget(alerted_key, field)) == status:
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
            self.r.hset(alerted_key, field, status)

        stale_fields = {
            _text(field) for field in self.r.hkeys(alerted_key)
        } - current_fields
        if stale_fields:
            self.r.hdel(alerted_key, *stale_fields)


def run_observers(watchdog, jobs, agents) -> list[str]:
    """Poll each observer under its OWN try, and report which failed.

    ⚠ In the switch all five shared one try, so a throw in the first silently
    skipped the rest of the pass and the record named only the exception class.
    Returns the names that raised, so this is testable rather than inspectable.
    """
    failed = []
    for name, job in jobs:
        try:
            job.poll(agents)
        except Exception as exc:
            watchdog._error(name, exc)
            failed.append(name)
    return failed


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
    # ⚠ These three moved out of the switch's forwarding loop. They observe
    # agents — CLI transcripts, presence, whether a paste was followed by input
    # — and the watchdog is already their only consumer: it reads the `presence`
    # and `blocked` hashes they write. Sampling them here keeps file I/O and
    # stream scans off the thread that must not block.
    pod, tenant = os.environ["POD"], os.environ["TENANT"]
    observers = (
        ("activity", ActivityTailer(r, pod=pod, tenant=tenant)),
        ("presence", PresenceSampler(
            r, pod=pod, tenant=tenant,
            working_seconds=float(os.environ.get("PRESENCE_WORKING_SECONDS", "30")))),
        ("verification", DeliveryVerifier(
            r, pod=pod, tenant=tenant,
            verify_after_seconds=float(os.environ.get("VERIFY_AFTER_SECONDS", "10")))),
    )
    # ⚠ Activity kept the switch's 2s cadence, not the watchdog's 30s. It feeds
    # verification, which only judges markers older than VERIFY_AFTER_SECONDS;
    # sampling it at 30s would make "the agent typed" observable up to 30s late
    # and turn healthy agents into unverified ones.
    observe_seconds = float(os.environ.get("ACTIVITY_POLL_SECONDS", "2"))
    next_observe = 0.0

    next_poll = 0.0
    next_credentials = 0.0
    while True:
        if time.monotonic() >= next_observe:
            try:
                run_observers(watchdog, observers, watchdog._agents())
            except Exception as exc:
                watchdog._error("observers", exc)
            next_observe = time.monotonic() + observe_seconds
        # ⚠ Gated separately from the observers. The loop now wakes every
        # observe_seconds (2s) to sample activity, and poll() is the expensive
        # one — it shells out to tmux and reads presence and a ticket per agent.
        # Ungated it would run 15x more often than WATCHDOG_INTERVAL asks for.
        if time.monotonic() >= next_poll:
            try:
                watchdog.poll()
            except Exception as exc:
                watchdog._error("observations", exc)
            next_poll = time.monotonic() + interval
        if time.monotonic() >= next_credentials:
            try:
                watchdog.check_credentials()
                next_credentials = time.monotonic() + 3600
            except Exception as exc:
                watchdog._error("credentials", exc)
        time.sleep(min(interval, observe_seconds))
