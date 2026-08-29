"""Report tenant stalls and blocked deliveries without repairing either."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

from flock.bus import (
    EnvelopeError,
    build,
    encode,
    is_member,
    log_record,
    members,
    mirror,
    prefix,
    port_type,
    require_allowed,
)
from flock.bus.queues import admit_ingress
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
        doing_alert_seconds: float = 900,
        todo_alert_seconds: float = 300,
        hold_alert_seconds: float = 3600,
        unreplied_alert_seconds: float = 60,
        ingress_max: int = 300,
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
        self.doing_alert_seconds = doing_alert_seconds
        self.todo_alert_seconds = todo_alert_seconds
        self.hold_alert_seconds = hold_alert_seconds
        self.unreplied_alert_seconds = unreplied_alert_seconds
        self.ingress_max = ingress_max
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
        record = {**record, "writer": "watchdog"}
        raw = json.dumps(record, separators=(",", ":"))
        self.r.xadd(
            prefix(self.pod, self.tenant, resource="alerts"),
            {"alert": raw},
            maxlen=1000,
            approximate=True,
        )
        print(raw, flush=True)
        # ⚠ Alerts bypassed the durable mirror until 2026-08-22 — they reached
        # `docker logs` and the Redis stream, both of which die with the
        # container, so a credential or stall alert left no trace after
        # teardown. Found by diffing the evidence file against `docker logs` on
        # a live tenant, not by reading.
        mirror(raw)

    @staticmethod
    def _error(job: str, exc: Exception) -> None:
        raw = json.dumps(
            {
                "module": "watchdog",
                "event": "error",
                "writer": "watchdog",
                "job": job,
                "reason": f"{type(exc).__name__}: {exc}",
            },
            separators=(",", ":"),
        )
        print(raw, flush=True)
        mirror(raw)

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

    def _lead(self) -> str | None:
        return _text(self.r.get(prefix(self.pod, self.tenant, resource="lead")))

    def _notify_lead(self, lead: str, text: str) -> None:
        """Paste one message directly into the lead's pane.

        ⚠ This is the one place the watchdog addresses a participant instead of
        the alerts stream — see HLD §8c. `office send` cannot be reused as-is:
        it enqueues onto the *sender's own* egress list for the switch to
        forward, and the watchdog is deliberately not a roster member with an
        egress queue anyone polls (§1 — it must not sit in the switch's pass).
        So this builds the same v4 envelope `office send` would and places it
        directly on the lead's ingress queue, then kicks `flock.port` the same
        way the switch does after a normal forward — same envelope shape, same
        `message_opener` rendering, same delivery subprocess. Only the egress
        hop, which nothing was ever going to drain, is skipped.

        ⚠ The ingress write goes through the same `admit_ingress` bound the
        switch uses for every other forward, not a plain `rpush`. Before this,
        a lead whose port stopped draining ingress had nothing capping how
        many nags the watchdog kept appending — the one unbounded write into
        a participant's ingress in an otherwise bounded system. Rejection here
        is not a delivery failure worth retaining: these are best-effort nags,
        not durable envelopes anyone is owed, and the board/`unreplied` state
        that triggered this one is untouched, so it re-fires on its own next
        threshold crossing once the lead's port recovers. So a full queue logs
        `lead_alert_capacity` and drops the alert — no dead-letter, no retry.
        A Redis/eval exception logs `lead_alert_unknown` instead, because the
        write may have committed before the error, mirroring `send_unknown`/
        `forward_unknown` elsewhere in the bus.
        """
        if not is_member(self.r, pod=self.pod, tenant=self.tenant, agent=lead):
            return
        if port_type(self.r, pod=self.pod, tenant=self.tenant, agent=lead) != "tmux":
            return
        try:
            require_allowed(self.r, pod=self.pod, tenant=self.tenant, source="watchdog", destination=lead)
            envelope = build(
                "Message", "watchdog", lead, {"text": text}, pod=self.pod, tenant=self.tenant
            )
            raw = encode(envelope)
        except EnvelopeError as exc:
            self._error("lead_alert", exc)
            return
        try:
            admitted, _, depth = admit_ingress(
                self.r,
                pod=self.pod,
                tenant=self.tenant,
                destinations=[lead],
                raw=raw,
                limit=self.ingress_max,
            )
        except Exception as exc:
            log_record(
                "watchdog", "lead_alert_unknown",
                stream_id=envelope["stream_id"], destination=lead,
                reason=f"admission outcome UNKNOWN after {exc}",
            )
            return
        if not admitted:
            log_record(
                "watchdog", "lead_alert_capacity",
                stream_id=envelope["stream_id"], destination=lead,
                reason=f"lead ingress full: depth {depth} has reached INGRESS_MAX {self.ingress_max}",
            )
            return
        log_record("watchdog", "lead_alert_sent", stream_id=envelope["stream_id"], destination=lead)
        try:
            subprocess.Popen(["flock.port", lead])
        except OSError as exc:
            self._error("lead_alert_kick", exc)

    def _check_doing_duration(self, agents: list[str], now: datetime) -> None:
        """Tell the lead directly when a ticket has sat in `doing` too long.

        Deliberately board-only: no presence, no window. §2's three-signal
        `stalled` rule exists to keep the passive /alerts stream from crying
        wolf at an ordinary long build; this is a narrower, louder nudge aimed
        only at the lead, whose job is to weigh it, not at a stream a human may
        not be watching. The two rules are independent and may both fire for
        the same ticket.
        """
        lead = self._lead()
        if not lead:
            return
        for agent in agents:
            ticket = self._ticket(agent)
            if not ticket or not isinstance(ticket.get("title"), str):
                continue
            started = _timestamp(ticket.get("started_ts"))
            if started is None:
                continue
            doing_age = int((now - started).total_seconds())
            if doing_age < self.doing_alert_seconds:
                continue
            ticket_id = ticket.get("id")
            if not isinstance(ticket_id, str) or not ticket_id:
                continue

            # Re-alert once per threshold crossing (15m, 30m, 45m, ...) rather
            # than once ever, so a ticket stuck for hours keeps nudging the
            # lead — and at most once per crossing, never once per 30s poll.
            multiple = int(doing_age // self.doing_alert_seconds)
            state_key = prefix(self.pod, self.tenant, agent, "doing.alerted")
            previous = _text(self.r.get(state_key)) or ""
            prev_id, _, prev_multiple = previous.partition(":")
            if prev_id == ticket_id and prev_multiple.isdigit() and int(prev_multiple) >= multiple:
                continue

            minutes = doing_age // 60
            text = (
                f'[alert from watchdog] {agent} has been working on '
                f'"{ticket["title"]}" for {minutes} min, request an update'
            )
            self._notify_lead(lead, text)
            self.r.set(state_key, f"{ticket_id}:{multiple}")

    def _check_todo_duration(self, agents: list[str], now: datetime) -> None:
        """Tell the lead directly when a ticket has sat unpicked in `todo`.

        Same family as `_check_doing_duration`, same delivery and dedup shape,
        independent job and state. Presence-independent for the same reason:
        an agent can be perfectly healthy and simply not have looked at its
        board yet, which is exactly the case this exists to surface.

        Unlike `doing` (one ticket, enforced), `todo` can hold several at
        once, so the per-ticket crossing count is a HASH keyed by ticket id
        rather than the single STRING `doing.alerted` uses — more than one of
        an agent's queued tickets can independently be old.
        """
        lead = self._lead()
        if not lead:
            return
        for agent in agents:
            state_key = prefix(self.pod, self.tenant, agent, "todo.alerted")
            raw_tickets = self.r.lrange(prefix(self.pod, self.tenant, agent, "tasks.todo"), 0, -1)
            present_ids = set()
            for raw in raw_tickets:
                try:
                    ticket = json.loads(_text(raw))
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(ticket, dict) or not isinstance(ticket.get("title"), str):
                    continue
                ticket_id = ticket.get("id")
                if not isinstance(ticket_id, str) or not ticket_id:
                    continue
                present_ids.add(ticket_id)
                created = _timestamp(ticket.get("created_ts"))
                if created is None:
                    continue
                todo_age = int((now - created).total_seconds())
                if todo_age < self.todo_alert_seconds:
                    continue

                # Re-alert once per threshold crossing, same rule as doing.alerted.
                multiple = int(todo_age // self.todo_alert_seconds)
                previous = _text(self.r.hget(state_key, ticket_id))
                if previous is not None and previous.isdigit() and int(previous) >= multiple:
                    continue

                minutes = todo_age // 60
                text = (
                    f'[alert from watchdog] {agent} has an unpicked ticket '
                    f'"{ticket["title"]}" waiting {minutes} min'
                )
                self._notify_lead(lead, text)
                self.r.hset(state_key, ticket_id, str(multiple))

            # A ticket taken, cancelled or deleted leaves `todo` and its crossing
            # count is no longer meaningful; drop it rather than let the hash
            # grow with entries no board state will ever match again.
            stale = {_text(field) for field in (self.r.hkeys(state_key) or [])} - present_ids
            if stale:
                self.r.hdel(state_key, *stale)

    def _check_hold_duration(self, agents: list[str], now: datetime) -> None:
        """Tell the lead directly when a ticket has sat on `hold` too long.

        Third rule in the family, same delivery and dedup shape as
        `_check_todo_duration` — `hold`, like `todo`, is not a one-ticket slot,
        so `hold.alerted` is a HASH keyed by ticket id too.

        The threshold is deliberately longer than `doing`'s or `todo`'s: a
        hold is often a legitimate wait on something external, and the point
        is not to nag an agent for parking work sensibly. It exists to force
        a decision on a hold that has sat long enough to stop looking like a
        wait and start looking like abandonment — at which point the ticket
        probably belongs cancelled or deleted, not indefinitely held.
        """
        lead = self._lead()
        if not lead:
            return
        for agent in agents:
            state_key = prefix(self.pod, self.tenant, agent, "hold.alerted")
            raw_tickets = self.r.lrange(prefix(self.pod, self.tenant, agent, "tasks.hold"), 0, -1)
            present_ids = set()
            for raw in raw_tickets:
                try:
                    ticket = json.loads(_text(raw))
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(ticket, dict) or not isinstance(ticket.get("title"), str):
                    continue
                ticket_id = ticket.get("id")
                if not isinstance(ticket_id, str) or not ticket_id:
                    continue
                present_ids.add(ticket_id)
                # A ticket held before `held_ts` existed (or by an older
                # client) has nothing there yet; `office list`'s own
                # `_ticket_age` falls back to `created_ts` for the same
                # reason — "how long has this sat" over showing nothing.
                held = _timestamp(ticket.get("held_ts")) or _timestamp(ticket.get("created_ts"))
                if held is None:
                    continue
                hold_age = int((now - held).total_seconds())
                if hold_age < self.hold_alert_seconds:
                    continue

                # Re-alert once per threshold crossing, same rule as the other two.
                multiple = int(hold_age // self.hold_alert_seconds)
                previous = _text(self.r.hget(state_key, ticket_id))
                if previous is not None and previous.isdigit() and int(previous) >= multiple:
                    continue

                minutes = hold_age // 60
                text = (
                    f'[alert from watchdog] {agent} has had '
                    f'"{ticket["title"]}" on hold for {minutes} min'
                )
                self._notify_lead(lead, text)
                self.r.hset(state_key, ticket_id, str(multiple))

            # A ticket taken off hold, cancelled or deleted leaves `hold` and
            # its crossing count is no longer meaningful.
            stale = {_text(field) for field in (self.r.hkeys(state_key) or [])} - present_ids
            if stale:
                self.r.hdel(state_key, *stale)

    def _check_unreplied_duration(self, agents: list[str], now: datetime) -> None:
        """Tell the lead directly when a client message has sat unanswered.

        Fourth in the doing/todo/hold family, same delivery and dedup shape,
        independent state. Unlike those three, the trigger is not the board —
        it is `unreplied`, a HASH `bus.send` itself writes: opened when a
        client (`api` port_type, e.g. `telegram`) sends a tmux agent a
        Message or Attachment, cleared the instant that agent sends anything
        back to the same client. `since` is the oldest still-unanswered
        message's timestamp; `count` how many have arrived since.

        Board-only-to-the-lead's reasoning (§4) still applies here: pasting the
        nag straight into the owing agent's own pane would risk nothing here
        (the evidence is `unreplied`, cleared only by an actual reply, not by
        window activity), but the family's one exception stays the lead only,
        not a second one for this rule alone.

        ⚠ **Re-alerts back off exponentially, unlike the other three.**
        `WATCHDOG_UNREPLIED_ALERT_SEC` defaults to 60s because a client message
        deserves a fast first nag — a fixed re-alert *period* that short would
        page the lead once a minute for the length of any genuinely long task,
        which is the wrong failure mode to optimize for. Instead the state
        value stored per client is the threshold that was just used, and the
        next one required is double it: 60s, 120s, 240s, ... A quick miss
        still surfaces within a minute; a five-minute task produces two nags,
        not five.
        """
        lead = self._lead()
        if not lead:
            return
        for agent in agents:
            state_key = prefix(self.pod, self.tenant, agent, "unreplied.alerted")
            raw_fields = _fields(self.r.hgetall(prefix(self.pod, self.tenant, agent, "unreplied")) or {})
            present_clients = set()
            for client, raw_value in raw_fields.items():
                try:
                    data = json.loads(raw_value)
                    count = int(data["count"])
                    since = _timestamp(data["since"])
                except (TypeError, ValueError, KeyError):
                    continue
                if since is None or count < 1:
                    continue
                present_clients.add(client)
                age = int((now - since).total_seconds())

                previous = _text(self.r.hget(state_key, client))
                if previous is not None and previous.isdigit():
                    next_threshold = int(previous) * 2
                else:
                    next_threshold = int(self.unreplied_alert_seconds)
                if age < next_threshold:
                    continue

                minutes = age // 60
                plural = "" if count == 1 else "s"
                text = (
                    f'[alert from watchdog] {agent} has {count} unanswered message{plural} from '
                    f'{client}, oldest {minutes} min old'
                )
                self._notify_lead(lead, text)
                self.r.hset(state_key, client, str(next_threshold))

            # A client the agent has since answered leaves `unreplied`; its
            # crossing count is no longer meaningful, same pruning as todo/hold.
            stale = {_text(field) for field in (self.r.hkeys(state_key) or [])} - present_clients
            if stale:
                self.r.hdel(state_key, *stale)

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
        try:
            self._check_doing_duration(agents, now)
        except Exception as exc:
            self._error("doing_duration", exc)
        try:
            self._check_todo_duration(agents, now)
        except Exception as exc:
            self._error("todo_duration", exc)
        try:
            self._check_hold_duration(agents, now)
        except Exception as exc:
            self._error("hold_duration", exc)
        try:
            self._check_unreplied_duration(agents, now)
        except Exception as exc:
            self._error("unreplied_duration", exc)

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
                token_name = f"CLAUDE_OAUTH_TOKEN_{account.upper().replace('-', '_')}"
                if os.environ.get(token_name):
                    # tmux.ops injects this value into the matching window as
                    # CLAUDE_CODE_OAUTH_TOKEN. No credentials file is expected.
                    # Known limit: presence cannot detect an expired or revoked
                    # token; that requires a remote authentication probe.
                    continue
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
                        status = "present"
            previous = _text(self.r.hget(alerted_key, field))
            if previous == status:
                continue
            if status == "present" and previous is None:
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
            if status == "present":
                self.r.hdel(alerted_key, field)
            else:
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
    # ⚠ WATCHDOG_ENABLED silences ALERTING, not telemetry. Until the observers
    # moved here they lived in the switch, so this flag only ever quietened the
    # stall and blocked alerts. Returning here would now also stop
    # ActivityTailer, PresenceSampler and DeliveryVerifier — presence would read
    # `unknown` forever, the activity stream would stay empty, and the Telegram
    # bot would lose its progress indicator. Found by api reviewing build 77;
    # the flag's name promises alerts and three clients depend on the rest.
    alerting = os.environ.get("WATCHDOG_ENABLED", "1") != "0"
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
        doing_alert_seconds=float(os.environ.get("WATCHDOG_DOING_ALERT_SEC", "900")),
        todo_alert_seconds=float(os.environ.get("WATCHDOG_TODO_ALERT_SEC", "300")),
        hold_alert_seconds=float(os.environ.get("WATCHDOG_HOLD_ALERT_SEC", "3600")),
        unreplied_alert_seconds=float(os.environ.get("WATCHDOG_UNREPLIED_ALERT_SEC", "60")),
        ingress_max=int(os.environ.get("INGRESS_MAX", "300")),
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
            verify_after_seconds=float(os.environ.get("VERIFY_AFTER_SECONDS", "120")))),
    )
    # ⚠ Activity kept the switch's 2s cadence, not the watchdog's 30s. It feeds
    # verification, which only judges markers older than VERIFY_AFTER_SECONDS;
    # sampling it at 30s would make "the agent typed" observable up to 30s late
    # and turn healthy agents into unverified ones.
    observe_seconds = float(os.environ.get("ACTIVITY_POLL_SECONDS", "2"))
    next_observe = 0.0

    if not alerting:
        log_record("watchdog", "alerting_disabled",
                   reason="WATCHDOG_ENABLED=0; observers still running")

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
        if alerting and time.monotonic() >= next_poll:
            try:
                watchdog.poll()
            except Exception as exc:
                watchdog._error("observations", exc)
            next_poll = time.monotonic() + interval
        if alerting and time.monotonic() >= next_credentials:
            try:
                watchdog.check_credentials()
                next_credentials = time.monotonic() + 3600
            except Exception as exc:
                watchdog._error("credentials", exc)
        time.sleep(min(interval, observe_seconds))
