"""Telegram bot client for h-flock.

Talks to an h-flock tenant REST API over HTTP, allowing users to interact with
the 'architect' agent via Telegram.
"""

import argparse
import asyncio
import base64
import html
import json
import logging
import os
import pathlib
import re
import ssl
import sys
import edge_tts
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from websockets.sync.client import connect as ws_connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("flock_telegram")


class FlockClient:
    """Thin REST client for h-flock API based on API.md."""

    def __init__(self, base_url: str, token: str, app_name: str = "telegram",
                 ssl_context: "ssl.SSLContext | None" = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.app_name = app_name
        # ⚠ This context reaches the h-flock door and nothing else. The Telegram
        # Bot API is a public host with a real certificate — weakening
        # verification there would be a different decision entirely, so
        # TelegramClient does not take one.
        self.ssl_context = ssl_context

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
        try:
            # context is ignored for http:// urls, so this needs no branch
            with urllib.request.urlopen(req, timeout=10, context=self.ssl_context) as resp:
                resp_body = resp.read().decode("utf-8")
                parsed = json.loads(resp_body) if resp_body else {}
                return resp.status, parsed
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            try:
                parsed = json.loads(err_body)
            except Exception:
                parsed = {"detail": err_body}
            return err.code, parsed
        except Exception as exc:
            return 500, {"detail": str(exc)}

    def enrol(self) -> tuple[int, dict]:
        """Enrol application client with host using StartAgent and port_type: api."""
        return self.request(
            "POST",
            "/agents/host/envelopes",
            {"kind": "StartAgent", "payload": {"agent": self.app_name, "port_type": "api"}},
        )

    def send_message(self, destination: str, text: str) -> tuple[int, dict]:
        """Send a text message envelope to an agent."""
        return self.request(
            "POST",
            f"/agents/{destination}/envelopes",
            {"text": text, "as": self.app_name},
        )

    def send_command(self, destination: str, text: str) -> tuple[int, dict]:
        """Send a Command-kind envelope. Unlike send_message's Message-kind
        shorthand, flock.port's command_opener pastes payload.text raw with
        a trailing newline and no "[message from X]" wrapper — so a native
        CLI slash command (e.g. Claude Code's /clear) is interpreted by the
        underlying CLI instead of read as chat text saying "/clear"."""
        return self.request(
            "POST",
            f"/agents/{destination}/envelopes",
            {"kind": "Command", "payload": {"text": text}, "as": self.app_name},
        )

    def send_attachment(
        self, destination: str, filename: str, mime_type: str, content_base64: str, caption: str | None = None
    ) -> tuple[int, dict]:
        """Send an Attachment-kind envelope (docs/CONTRACTS.md) — file bytes
        on the bus, not a path shared out of band. The api re-validates and
        re-checks the decoded size regardless of what this client already
        checked (a direct bus caller can bypass both the api and here)."""
        payload = {"filename": filename, "mime_type": mime_type, "content_base64": content_base64}
        if caption:
            payload["caption"] = caption
        return self.request(
            "POST",
            f"/agents/{destination}/envelopes",
            {"kind": "Attachment", "payload": payload, "as": self.app_name},
        )

    def get_presence(self, agent: str) -> tuple[int, dict]:
        """Get queue depths and presence state for an agent."""
        return self.request("GET", f"/agents/{agent}")

    def get_board(self, agent: str) -> tuple[int, dict]:
        """Get task board for an agent."""
        return self.request("GET", f"/agents/{agent}/board")

    def get_agents(self) -> tuple[int, dict]:
        """List every enrolled agent in the tenant roster (names only)."""
        return self.request("GET", "/agents")

    def get_all_boards(self) -> tuple[int, dict]:
        """Get task boards for every enrolled agent in one round-trip."""
        return self.request("GET", "/board")

    def add_ticket(self, agent: str, title: str, description: str = "", priority: str = "") -> tuple[int, dict]:
        """Add a ticket to an agent's board without interrupting them."""
        payload: dict = {"title": title}
        if description:
            payload["description"] = description
        if priority:
            payload["priority"] = priority
        return self.request(
            "POST",
            f"/agents/{agent}/envelopes",
            {"kind": "AddTicket", "payload": payload, "as": self.app_name},
        )

    def control_agent(self, kind: str, agent: str) -> tuple[int, dict]:
        """Send a PauseAgent/ResumeAgent lifecycle envelope, addressed to host."""
        return self.request(
            "POST",
            "/agents/host/envelopes",
            {"kind": kind, "payload": {"agent": agent}, "as": self.app_name},
        )

    def retire_agent(self, agent: str) -> tuple[int, dict]:
        """StopAgent: removes roster membership and identity state. Queues
        and boards are kept for a later re-hire — destructive to identity,
        not to work already recorded."""
        return self.request(
            "POST",
            "/agents/host/envelopes",
            {"kind": "StopAgent", "payload": {"agent": agent}, "as": self.app_name},
        )

    def hire_agent(self, agent: str, cli: str = "claude", profile: str | None = None,
                    provider: str | None = None) -> tuple[int, dict]:
        """StartAgent with port_type "tmux": a new terminal agent with its own
        window and CLI. Unlike StopAgent (retire), this is not destructive —
        no identity or queues are ever removed by hiring.

        ⚠ `profile` is validated server-side against the tenant's account
        registry (`available_profiles`, `control/openers.py`), which lists
        the valid accounts in its error if the name is wrong. There is no
        REST endpoint that exposes that registry ahead of time — `office
        profiles` reads Redis directly — so this client cannot offer a picker
        and doesn't pretend to; a bad profile name is a clear 422, not a
        guess. `provider` points the agent at a named local model endpoint
        (`AGENT_PROVIDERS`) — format-checked only, no registry to validate
        against either."""
        payload: dict = {"agent": agent, "port_type": "tmux", "cli": cli}
        if profile:
            payload["profile"] = profile
        if provider:
            payload["provider"] = provider
        return self.request(
            "POST",
            "/agents/host/envelopes",
            {"kind": "StartAgent", "payload": payload, "as": self.app_name},
        )

    def get_messages(self, after: str | None = None, limit: int = 100) -> tuple[int, dict]:
        """Catch-up poll mailbox messages for this client."""
        path = f"/agents/{self.app_name}/messages?limit={limit}"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        return self.request("GET", path)

    def poll_messages_forever(self, after: str | None = None, interval: float = 1.0):
        """Yield each new mailbox message for this client as it arrives,
        forever — a blocking generator wrapping repeated `get_messages`
        calls, so ReplyPusher can consume it exactly like AlertPusher
        consumes `stream_alerts`. Polling rather than SSE: `GET
        /agents/{client}/messages/stream` exists, but this client is a
        plain synchronous urllib caller with no long-lived-connection
        machinery beyond what `stream_alerts` already built for one
        endpoint — a second one wasn't worth it for a mailbox this low in
        volume. Errors are logged and retried on the same interval rather
        than raised, so one bad poll never kills the pushing thread.
        """
        cursor = after
        while True:
            code, data = self.get_messages(after=cursor)
            if code == 200:
                for msg in data.get("messages", []):
                    cursor = msg.get("cursor", cursor)
                    yield msg
            else:
                logger.warning(f"poll_messages_forever: GET /agents/{self.app_name}/messages failed: status={code}, body={data}")
            time.sleep(interval)

    def get_activity(self, agent: str, after: str | None = None, limit: int = 100) -> tuple[int, dict]:
        """Catch-up poll activity feed events for an agent."""
        path = f"/agents/{agent}/activity?limit={limit}"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        return self.request("GET", path)

    def get_alerts(self, after: str | None = None, limit: int = 100) -> tuple[int, dict]:
        """Catch-up poll watchdog alerts (blocked / stalled / credential —
        API.md's Watchdog Alerts Feed). ⚠ There is no "give me the tail"
        query: without `after`, this reads from the OLDEST stored alert, same
        as every other stream endpoint. A caller wanting "recent" must fetch
        with a large `limit` and take the tail itself (see TelegramBot's
        handle_alerts_command)."""
        path = f"/alerts?limit={limit}"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        return self.request("GET", path)

    def stream_alerts(self, after: str | None = None):
        """Yield alert dicts from GET /alerts/stream as they arrive.

        Blocking generator — never returns on its own — meant to run in its
        own thread. Reconnects with capped exponential backoff on any
        connection failure or stream-side `error` event, resuming from the
        last cursor seen so a reconnect does not replay what was already
        delivered.

        ⚠ Uses a finite socket timeout despite API.md §4a's "SSE heartbeats
        are not guaranteed, do not infer death from silence" — that warning
        is about not treating silence as a *logical* error (do not, say, tell
        a user "alerts are broken"). For a background reconnect loop the
        trade-off flips: periodically reconnecting an idle-but-healthy stream
        is harmless (cursor-based resume, no duplicates, no gap), while a
        socket that died without a FIN and is never noticed hangs this thread
        forever. Bounded timeout + resume is strictly safer here.
        """
        cursor = after
        backoff = 1.0
        while True:
            path = "/alerts/stream"
            if cursor:
                path += f"?after={urllib.parse.quote(cursor)}"
            req = urllib.request.Request(f"{self.base_url}{path}", headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=90, context=self.ssl_context) as resp:
                    backoff = 1.0
                    for event_type, event_id, data in _parse_sse_events(resp):
                        if event_id:
                            cursor = event_id
                        if event_type == "error" or data is None:
                            continue
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(parsed, dict):
                            continue
                        if parsed.get("cursor"):
                            cursor = parsed["cursor"]
                        yield parsed
            except Exception as exc:
                logger.warning(f"alerts stream disconnected, retrying in {backoff:.0f}s: {exc}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def stream_activity(self, agent: str, after: str | None = None):
        """Yield activity dicts from GET /agents/{agent}/activity/stream as they arrive."""
        cursor = after
        backoff = 1.0
        while True:
            path = f"/agents/{agent}/activity/stream"
            if cursor:
                path += f"?after={urllib.parse.quote(cursor)}"
            req = urllib.request.Request(f"{self.base_url}{path}", headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=90, context=self.ssl_context) as resp:
                    backoff = 1.0
                    for event_type, event_id, data in _parse_sse_events(resp):
                        if event_id:
                            cursor = event_id
                        if event_type == "error" or data is None:
                            continue
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(parsed, dict):
                            continue
                        if parsed.get("cursor"):
                            cursor = parsed["cursor"]
                        yield parsed
            except Exception as exc:
                logger.warning(f"activity stream for {agent} disconnected, retrying in {backoff:.0f}s: {exc}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def _parse_sse_events(line_iter):
    """Parse raw SSE lines into `(event_type, id, data)` tuples, one per
    blank-line-terminated frame. Pure and network-free so it is directly unit
    testable; `stream_alerts` is the only network-touching caller."""
    event_type = None
    event_id = None
    data_lines: list[str] = []
    for raw_line in line_iter:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")
        if line == "":
            if data_lines:
                yield event_type, event_id, "\n".join(data_lines)
            event_type, data_lines = None, []
            continue
        if line.startswith(":"):
            continue  # comment / keepalive
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line.startswith("id:"):
            event_id = line[len("id:"):].strip()


# Same rule and reserved set clients/web/ui/lifecycle.js enforces client-side
# for hire — kept identical so a name this bot refuses is refused everywhere,
# not just here. The api would refuse it too, but telling the user before the
# round trip is worth the duplication of one regex.
_AGENT_NAME = re.compile(r"^(?![0-9]+$)[a-z0-9][a-z0-9-]{0,62}$")
_RESERVED_AGENT_NAMES = {"all", "pod", "tenant", "agent"}

_ALERT_ICONS = {"blocked": "⊘", "stalled": "⏳", "credential": "🔑"}

# Telegram's own Bot API ceiling for getFile — a "photo" upload is always
# recompressed by Telegram well under this, so it is cheap insurance rather
# than an expected case, checked against PhotoSize's own reported file_size
# before downloading anything at all.
TELEGRAM_MAX_FILE_BYTES = 20 * 1024 * 1024

# docs/CONTRACTS.md's Attachment section — the strictly decoded content is
# capped at 10 MiB, smaller than TELEGRAM_MAX_FILE_BYTES above. A photo
# between 10 and 20MB downloads fine from Telegram but must still be
# refused as an Attachment, so this is checked separately and is not the
# same limit reused twice.
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024

# filename: non-empty UTF-8 basename, at most 255 UTF-8 bytes, not "." or
# "..", and none of "/", "\", NUL, another ASCII control character, or
# U+007F.
_ATTACHMENT_FILENAME_FORBIDDEN = re.compile(r"[/\\\x00-\x1f\x7f]")

# mime_type: at most 255 ASCII bytes, no parameters/whitespace/controls/wildcards.
_ATTACHMENT_MIME_TYPE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)


def _valid_attachment_filename(name: str) -> bool:
    if not name or name in (".", "..") or len(name.encode("utf-8")) > 255:
        return False
    return not _ATTACHMENT_FILENAME_FORBIDDEN.search(name)


def _valid_attachment_mime_type(value: str) -> bool:
    return bool(value) and len(value) <= 255 and bool(_ATTACHMENT_MIME_TYPE_RE.match(value))


# caption: at most 65,536 UTF-8 bytes (docs/CONTRACTS.md).
ATTACHMENT_MAX_CAPTION_BYTES = 65536

# "The payload is a closed shape ... no other field is accepted"
# (docs/CONTRACTS.md) — ReplyPusher._push_attachment enforces this the same
# as the api door and the tmux opener do, since it runs on envelopes a
# direct bus caller could have written with no api validation at all.
ATTACHMENT_ALLOWED_PAYLOAD_KEYS = frozenset({"filename", "mime_type", "content_base64", "caption"})

# A leading "@name rest of message" — a one-off destination override for
# just that one message, unlike 🎯 Message agent's handle_message_agent_pick
# which changes the persistent chat_target_agent. Deliberately anchored to
# the START of the text only: an "@word" anywhere else in the message is
# ordinary content, not a second routing directive — Slack-style inline
# mentions notify, they don't redirect an entire message, and this one
# does redirect, so it needs to be unambiguous about which text it applies
# to. That also settles "what about multiple @mentions" without a separate
# rule: only the first token position is ever inspected, so a later "@foo"
# in the body is just text. The name is captured loosely and lowercased
# (chat clients auto-capitalize) — handle_mention_prompt is what actually
# validates it against `_AGENT_NAME`/the roster.
_MENTION_RE = re.compile(r"^@([A-Za-z0-9-]{1,63})(?:[ \t]+(.*))?$", re.DOTALL)


def _parse_mention(text: str) -> tuple[str, str] | None:
    match = _MENTION_RE.match(text)
    if not match:
        return None
    return match.group(1).lower(), (match.group(2) or "").strip()


# `/run <agent> <command>` — a policy-reviewed exception to Command being
# "deliberately not exposed" (README §2a, web/SPEC.md §6): a full Command
# passthrough is unbounded remote execution from a phone with no live view
# of the pane, exactly what that note objected to. This is bounded to a
# fixed, pre-vetted set of native CLI slash commands instead — see
# handle_run_command for the full reasoning and the single-line
# requirement (an allowed command's own text could otherwise carry a
# newline, submitting a second, unvetted line of raw input on delivery).
# Global rather than per-CLI: the api exposes no field for which CLI an
# agent runs (same limitation PANE_WATCH_CHROME_OVERRIDES exists for), and
# claude/codex/agy's actual command grammars are not something this client
# can verify without a live agent of each kind to check against — an
# operator who runs CLIs where these two names mean something else, or
# wants more, sets --run-allowed-commands/RUN_ALLOWED_COMMANDS instead of
# this default.
DEFAULT_RUN_ALLOWED_COMMANDS = ("/clear", "/compact")


def _parse_command_allowlist(spec: str) -> frozenset[str]:
    """Parse "/clear,/compact" — comma-separated, each entry stripped of
    surrounding whitespace, blank entries dropped."""
    return frozenset(item.strip() for item in spec.split(",") if item.strip())


def render_alert(alert: dict) -> str:
    """One-line rendering of a GET /alerts entry, shared by the on-demand
    Alerts menu and the live AlertPusher so the two never drift."""
    kind = alert.get("kind", "unknown")
    icon = _ALERT_ICONS.get(kind, "🔔")
    agent = alert.get("agent", "?")

    def _minutes(seconds) -> str:
        return f"{seconds // 60}m" if isinstance(seconds, int) else "unknown"

    if kind == "blocked":
        return f"{icon} blocked — {agent} — unconsumed {_minutes(alert.get('unconsumed_s'))}"
    if kind == "stalled":
        ticket = alert.get("ticket", "")
        return f"{icon} stalled — {agent} — \"{ticket}\" — doing {_minutes(alert.get('doing_age_s'))}"
    if kind == "credential":
        return f"{icon} credential — {alert.get('account', '?')}/{alert.get('cli', '?')} — {alert.get('status', '?')}"
    # Forward-compatible fallback for a kind this client does not know yet.
    details = {k: v for k, v in alert.items() if k not in ("v", "ts", "cursor", "kind")}
    return f"{icon} {kind} — {json.dumps(details)}"


# Matches the deployed convention (container/entrypoint.sh's own
# --cursor-file "/home/ubuntu/.flock/telegram.cursor.json") rather than a
# bare relative filename. A bare "cursor.json" default lands wherever CWD
# happens to be — including the repo root itself for an ad hoc local run
# with no --cursor-file, where it sits as an untracked file forever after.
DEFAULT_CURSOR_FILE = str(pathlib.Path.home() / ".flock" / "telegram.cursor.json")


class CursorStore:
    """Persists cursor to disk so bot restarts do not replay mailbox."""

    def __init__(self, filepath: str = DEFAULT_CURSOR_FILE):
        self.filepath = pathlib.Path(filepath)

    def load(self) -> str | None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                return data.get("cursor")
            except Exception as exc:
                logger.warning(f"Failed to load cursor from {self.filepath}: {exc}")
        return None

    def save(self, cursor: str | None) -> None:
        if not cursor:
            return
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self.filepath.write_text(json.dumps({"cursor": cursor, "updated_at": time.time()}), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to save cursor to {self.filepath}: {exc}")


class AlertPusher:
    """Consumes GET /alerts/stream and pushes each new alert to a fixed
    Telegram chat as it happens — the point (per the ticket) is not having to
    be watching the pane or the menu to find out.

    ⚠ Only the three kinds `GET /alerts` documents ever arrive here: blocked,
    stalled, credential. `doing_duration` and `todo_duration` — the two
    lead-only alerts watchdog added — are pasted directly into the *lead's*
    tmux pane as an ordinary Message envelope (`flock.watchdog.service`
    `_notify_lead`) and never touch the alerts stream at all (confirmed by
    reading `_check_doing_duration`/`_check_todo_duration` against `_alert`).
    They are invisible to this client and to `GET /alerts` alike — there is
    currently no API surface that exposes them to anything but the lead's own
    pane.
    """

    def __init__(self, flock: "FlockClient", telegram, chat_id, cursor_store: CursorStore):
        self.flock = flock
        self.telegram = telegram
        self.chat_id = chat_id
        self.cursor_store = cursor_store

    def _seed_cursor(self) -> str | None:
        """On a fresh cursor store, start at the current tail rather than
        replay the whole retained history (up to 1000 alerts) as if every one
        were new — the same reasoning TelegramBot.enrol applies to mailboxes."""
        code, data = self.flock.get_alerts(limit=1000)
        if code == 200 and data.get("next_cursor"):
            return data["next_cursor"]
        return None

    def run(self, stream_fn=None) -> None:
        """Blocking; run this in its own thread. `stream_fn` defaults to
        `self.flock.stream_alerts` and is overridable so tests can inject a
        finite, network-free generator."""
        stream_fn = stream_fn or self.flock.stream_alerts
        cursor = self.cursor_store.load()
        if cursor is None:
            cursor = self._seed_cursor()
            if cursor:
                self.cursor_store.save(cursor)
        for alert in stream_fn(after=cursor):
            cursor = alert.get("cursor", cursor)
            if cursor:
                self.cursor_store.save(cursor)
            if self.telegram:
                self.telegram.send_message(self.chat_id, render_alert(alert))


def render_reply(message: dict, fallback_source: str) -> str:
    """One-line rendering of a mailbox message for ReplyPusher."""
    source = message.get("l2", {}).get("source") or fallback_source
    payload = message.get("payload")
    text = payload.get("text") if isinstance(payload, dict) else None
    return f"{source}: {text}" if text else f"{source} sent a message"


DEFAULT_TTS_VOICE = "en-GB-RyanNeural"


def synthesize_speech(
    text: str,
    voice: str = DEFAULT_TTS_VOICE,
    output_path: str | pathlib.Path | None = None,
) -> str:
    """Render text to an MP3 file using edge-tts."""
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("empty text for TTS synthesis")
    selected_voice = voice or DEFAULT_TTS_VOICE

    if output_path is None:
        fd, temp_path = tempfile.mkstemp(suffix=".mp3", prefix="flock_tts_")
        os.close(fd)
        target_path = temp_path
    else:
        target_path = str(output_path)

    try:
        communicate = edge_tts.Communicate(cleaned_text, selected_voice)
        asyncio.run(communicate.save(target_path))
        return target_path
    except Exception:
        pathlib.Path(target_path).unlink(missing_ok=True)
        raise


class ReplyPusher:
    """Consumes this bot's own mailbox (GET /agents/{app_name}/messages) and
    pushes each new reply into a fixed Telegram chat as it arrives.

    Same shape as AlertPusher (seed cursor from the tail, run in its own
    thread, persist cursor as it goes) — polling instead of SSE since that's
    what `FlockClient.poll_messages_forever` wraps. This is what actually
    delivers a reply now: `handle_user_prompt` only posts and returns,
    matching the real fire-and-forget delivery model (`POST
    /agents/{agent}/envelopes` always returns 202 immediately; nothing in
    switch/port/api waits on anything). The old design had
    `handle_user_prompt` itself poll-and-wait inline, which blocked the
    entire polling loop for every chat while one reply was pending — measured
    live on the acceptance VM. This owns that job instead, independently.
    """

    def __init__(
        self,
        flock: "FlockClient",
        telegram,
        chat_id,
        cursor_store: CursorStore,
        tts_voice: str | None = None,
        voice_enabled: bool = False,
        voice_enabled_fn=None,
        activity_finalizer_fn=None,
    ):
        self.flock = flock
        self.telegram = telegram
        self.chat_id = chat_id
        self.cursor_store = cursor_store
        self.tts_voice = tts_voice or os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE)
        self.voice_enabled = voice_enabled
        self.voice_enabled_fn = voice_enabled_fn
        self.activity_finalizer_fn = activity_finalizer_fn

    def _seed_cursor(self) -> str | None:
        """On a fresh cursor store, start at the current tail — a message
        that arrived before this process started is not an answer to
        anything sent through it; replaying it looks like lag at best and a
        stale, mismatched reply at worst."""
        cursor = None
        try:
            while True:
                code, data = self.flock.get_messages(after=cursor, limit=1000)
                if code != 200:
                    break
                items = data.get("messages", [])
                if not items:
                    break
                cursor = data.get("next_cursor")
                if len(items) < 1000:
                    break
            return cursor
        except Exception as exc:
            logger.debug(f"Failed to seed mailbox cursor: {exc}")
        return None

    def run(self, stream_fn=None) -> None:
        """Blocking; run this in its own thread. `stream_fn` defaults to
        `self.flock.poll_messages_forever` and is overridable so tests can
        inject a finite, network-free generator."""
        stream_fn = stream_fn or self.flock.poll_messages_forever
        cursor = self.cursor_store.load()
        if cursor is None:
            cursor = self._seed_cursor()
            if cursor:
                self.cursor_store.save(cursor)
        for message in stream_fn(after=cursor):
            cursor = message.get("cursor", cursor)
            if cursor:
                self.cursor_store.save(cursor)
            if self.telegram:
                source = message.get("l2", {}).get("source")
                if self.activity_finalizer_fn and source:
                    self.activity_finalizer_fn(self.chat_id, source)

                if message.get("kind") == "Attachment":
                    # ⚠ Not a text reply — the api stores this kind's mailbox
                    # entry with content_base64 unchanged (docs/CONTRACTS.md),
                    # and render_reply only ever reads payload.text, so
                    # falling through to it here would render a useless
                    # "<agent> sent a message" instead of delivering the file.
                    self._push_attachment(message, source)
                    continue

                reply_text = render_reply(message, self.flock.app_name)
                self.telegram.send_message(self.chat_id, reply_text)
                is_voice = (
                    self.voice_enabled_fn(self.chat_id)
                    if self.voice_enabled_fn
                    else self.voice_enabled
                )
                if is_voice:
                    msg_voice = (
                        message.get("payload", {}).get("voice")
                        if isinstance(message.get("payload"), dict)
                        else None
                    ) or self.tts_voice or DEFAULT_TTS_VOICE
                    voice_file = synthesize_speech(reply_text, msg_voice)
                    try:
                        self.telegram.send_voice(self.chat_id, voice_file)
                    finally:
                        pathlib.Path(voice_file).unlink(missing_ok=True)

    def _push_attachment(self, message: dict, source: str | None) -> None:
        """The other direction of the Attachment feature (docs/CONTRACTS.md):
        an agent's `office send-file` lands here as a mailbox entry with
        `kind: "Attachment"`, decoded and forwarded via `sendDocument`.

        ⚠ Re-validates the full contract independently, not just "is there
        something to send" — `docs/CONTRACTS.md` promises an api-type client
        "validates and decodes the same payload contract" the api door and
        the tmux opener do, the same defense-in-depth reasoning the opener's
        own re-check is built on: this envelope already passed the api
        door's validation in the normal flow, but a direct bus caller
        bypasses that door entirely and would otherwise reach this code
        with no real validation at all. Closed schema, filename basename
        rules, mime_type grammar, caption length and the decoded-size cap
        are all checked — reuses `_valid_attachment_filename`/
        `_valid_attachment_mime_type`/`ATTACHMENT_MAX_BYTES` from the send
        side (`handle_photo_message`) rather than a second copy of the same
        rules. A rejection is reported back to the chat, same as any other
        failure here — never silently dropped.
        """
        label = source or self.flock.app_name

        def reject(reason: str) -> None:
            self.telegram.send_message(self.chat_id, f"{label} sent an attachment, but it was rejected: {reason}.")

        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        extra_keys = sorted(set(payload.keys()) - ATTACHMENT_ALLOWED_PAYLOAD_KEYS)
        if extra_keys:
            reject(f"unexpected field(s) {', '.join(extra_keys)}")
            return

        filename = payload.get("filename")
        if not isinstance(filename, str) or not _valid_attachment_filename(filename):
            reject("invalid or missing filename")
            return

        mime_type = payload.get("mime_type")
        if not isinstance(mime_type, str) or not _valid_attachment_mime_type(mime_type):
            reject("invalid or missing mime_type")
            return

        content_b64 = payload.get("content_base64")
        if not isinstance(content_b64, str) or not content_b64:
            reject("missing content_base64")
            return

        caption_field = payload.get("caption")
        if caption_field is not None and (
            not isinstance(caption_field, str) or len(caption_field.encode("utf-8")) > ATTACHMENT_MAX_CAPTION_BYTES
        ):
            reject("invalid caption")
            return

        try:
            data = base64.b64decode(content_b64, validate=True)
        except (ValueError, TypeError) as exc:
            reject(f"content_base64 failed strict decoding ({exc})")
            return
        if len(data) > ATTACHMENT_MAX_BYTES:
            reject("decoded content exceeds the 10MB attachment limit")
            return

        caption = f"from {label}" + (f": {caption_field}" if caption_field else "")
        result = self.telegram.send_document(self.chat_id, filename, data, mime_type=mime_type, caption=caption)
        if not result.get("ok"):
            self.telegram.send_message(
                self.chat_id,
                f"Failed to deliver {label}'s attachment ({filename}): {result.get('description', 'unknown error')}",
            )


class TelegramClient:
    """Wrapper for Telegram Bot HTTP API."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def request(self, method: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{method}"
        body = json.dumps(params).encode("utf-8") if params is not None else None
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            logger.error(f"Telegram API error {method}: {err.code} {err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"ok": False, "description": err_body}
        except Exception as exc:
            logger.error(f"Telegram request failed: {exc}")
            return {"ok": False, "description": str(exc)}

    def download_file(self, file_path: str) -> bytes | None:
        """GET the raw bytes of a file already resolved via getFile's
        `file_path` — a different base URL than every other call here
        (`api.telegram.org/file/bot<token>/...`, not `.../bot<token>/<method>`),
        Telegram's own split between the JSON API and file downloads."""
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as exc:
            logger.error(f"Telegram file download failed: {exc}")
            return None

    def request_multipart(
        self,
        method: str,
        fields: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}/{method}"
        boundary = f"----FlockTelegramBoundary{uuid.uuid4().hex}"
        body = bytearray()

        if fields:
            for name, val in fields.items():
                if val is None:
                    continue
                body.extend(f"--{boundary}\r\n".encode("utf-8"))
                body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
                body.extend(str(val).encode("utf-8"))
                body.extend(b"\r\n")

        if files:
            for name, (filename, data, content_type) in files.items():
                body.extend(f"--{boundary}\r\n".encode("utf-8"))
                body.extend(
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8")
                )
                body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
                body.extend(data)
                body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            logger.error(f"Telegram API error {method}: {err.code} {err_body}")
            try:
                return json.loads(err_body)
            except Exception:
                return {"ok": False, "description": err_body}
        except Exception as exc:
            logger.error(f"Telegram multipart request failed: {exc}")
            return {"ok": False, "description": str(exc)}

    def send_voice(
        self,
        chat_id: int | str,
        voice: str | bytes | pathlib.Path,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        """Send voice audio via Telegram sendVoice endpoint using multipart upload."""
        if isinstance(voice, (str, pathlib.Path)):
            voice_path = pathlib.Path(voice)
            filename = voice_path.name or "voice.mp3"
            with open(voice_path, "rb") as f:
                voice_data = f.read()
        else:
            filename = "voice.mp3"
            voice_data = bytes(voice)

        fields: dict = {"chat_id": chat_id}
        if caption:
            fields["caption"] = caption[:1024]
        if reply_to_message_id:
            fields["reply_to_message_id"] = reply_to_message_id
        if reply_markup is not None:
            fields["reply_markup"] = json.dumps(reply_markup)

        files = {"voice": (filename, voice_data, "audio/mpeg")}
        return self.request_multipart("sendVoice", fields=fields, files=files)

    def send_document(
        self,
        chat_id: int | str,
        filename: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
        caption: str | None = None,
    ) -> dict:
        """Send file bytes via Telegram's sendDocument endpoint — the agent
        -> Telegram direction of the Attachment feature (docs/CONTRACTS.md),
        same multipart upload shape send_voice already uses."""
        fields: dict = {"chat_id": chat_id}
        if caption:
            # Telegram's own caption limit (1024 chars) applies here
            # regardless of the bus's much larger one (65,536 UTF-8 bytes,
            # docs/CONTRACTS.md) — same truncation send_voice already does.
            fields["caption"] = caption[:1024]
        files = {"document": (filename, data, mime_type)}
        return self.request_multipart("sendDocument", fields=fields, files=files)

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict:
        data = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        if parse_mode is not None:
            data["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            data["disable_web_page_preview"] = disable_web_page_preview
        return self.request("sendMessage", data)

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict:
        data = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        if parse_mode is not None:
            data["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            data["disable_web_page_preview"] = disable_web_page_preview
        return self.request("editMessageText", data)

    def send_chat_action(self, chat_id: int | str, action: str = "typing") -> dict:
        return self.request("sendChatAction", {"chat_id": chat_id, "action": action})

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        """Stop the inline button's loading spinner. Telegram expects one of
        these per callback_query within its own short timeout, regardless of
        whether the tap led to a visible reply."""
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        return self.request("answerCallbackQuery", data)

    def set_my_commands(self, commands: list[dict]) -> dict:
        """Register the bot's `/` command list with Telegram itself, so it
        shows up in the client's own command picker instead of requiring the
        user to know and type a command blind."""
        return self.request("setMyCommands", {"commands": commands})

    def get_updates(self, offset: int | None = None, timeout: int = 20) -> list[dict]:
        """⚠ getUpdates is per-BOT, not per-chat.

        Two processes polling one token compete for the same queue and each
        takes roughly half the updates — so running this against a token another
        bot is already using makes that bot drop messages, silently, for as long
        as this runs. Keep the window short, or use a token of your own.
        """
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        res = self.request("getUpdates", params)
        if res.get("ok"):
            return res.get("result", [])
        # ⚠ 409 means another process is polling this token. Telegram allows
        # exactly one getUpdates per bot, and the loser receives nothing —
        # forever, while looking perfectly healthy. Swallowing it cost an
        # afternoon: the bot was up, the log was quiet, and no message ever
        # arrived.
        if res.get("error_code") == 409:
            raise RuntimeError(
                "another instance is polling this bot token — stop it first "
                "(Telegram allows one getUpdates per bot)"
            )
        return []


class ChatDict(dict):
    """Dictionary keyed by chat_id that normalizes int and str keys to str."""

    def _k(self, key):
        return str(key)

    def __getitem__(self, key):
        return super().__getitem__(self._k(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._k(key), value)

    def __delitem__(self, key):
        super().__delitem__(self._k(key))

    def __contains__(self, key):
        return super().__contains__(self._k(key))

    def get(self, key, default=None):
        return super().get(self._k(key), default)

    def pop(self, key, *args):
        return super().pop(self._k(key), *args)

    def setdefault(self, key, default=None):
        return super().setdefault(self._k(key), default)


def _parse_int_overrides(spec: str) -> dict[str, int]:
    """Parse "name=int,name2=int" — same exceptions-only shape as
    entrypoint.sh's AGENT_CLIS/AGENT_PROFILES, here for per-agent pane-watch
    chrome-height overrides (see PANE_WATCH_CHROME_OVERRIDES below)."""
    result: dict[str, int] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        try:
            result[name] = int(value.strip())
        except ValueError:
            continue
    return result


def _agent_picker_keyboard(
    agents: list[str], callback_prefix: str, *, back_callback: str = "menu", columns: int = 3
) -> dict:
    """The inline keyboard every agent-picker (add ticket, lifecycle, message
    target, watch) shows: one button per agent, `columns` to a row rather
    than one-per-row — ten-plus enrolled agents made a single column a long
    scroll (measured: an operator's own report). `◀ Back` always gets its
    own row at the end, never folded into the grid, so it stays a single
    predictable tap regardless of how many agents fill the rows above it.
    """
    cells = [{"text": agent, "callback_data": f"{callback_prefix}:{agent}"} for agent in agents]
    rows = [cells[i : i + columns] for i in range(0, len(cells), columns)]
    rows.append([{"text": "◀ Back", "callback_data": back_callback}])
    return {"inline_keyboard": rows}


def _derive_session_url(api_url: str, session_url: str = "") -> str:
    """Derive the session websocket URL (e.g. ws://localhost:8081/session)
    from --session-url or by replacing API URL port with 8081."""
    if session_url:
        u = urllib.parse.urlsplit(session_url)
        scheme = "wss" if u.scheme in ("https", "wss") else "ws"
        netloc = u.netloc or f"{u.hostname or '127.0.0.1'}:{u.port or 8081}"
        path = u.path if (u.path and u.path != "/") else "/session"
        return f"{scheme}://{netloc}{path}"
    u = urllib.parse.urlsplit(api_url)
    scheme = "wss" if u.scheme == "https" else "ws"
    host = u.hostname or "127.0.0.1"
    port = 8081
    return f"{scheme}://{host}:{port}/session"


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Drop cursor-movement/clear and SGR colour codes from a session-door
    snapshot, leaving the plain text `capture-pane` rendered.

    Session snapshots (`LLD-session.md` §3) are `\\x1b[2J\\x1b[H` + the
    `capture-pane -e` lines (which carry colour SGR codes) + a cursor-position
    escape. None of that survives into a Telegram message — a terminal's
    color codes are noise there, not signal — and stripping is safe because
    `capture-pane`'s own line breaks (joined with `\\n` by `control.py`) are
    untouched by this regex.
    """
    return _ANSI_ESCAPE_RE.sub("", text)


# ⚠ These target a second kind of chrome the fixed `chrome_lines` crop can't
# reach: a CLI's own thinking-spinner and update-nag banner, which sit just
# ABOVE the structural input box/hint rows `chrome_lines` already crops, and
# are present or absent depending on CLI *state* (mid-turn, update shipped),
# not CLI identity — a bug ticket caught this leaking on both claude
# ("✻ Churned for 20s", "✔ Update installed · Restart to update") and codex
# ("Boogieing… (17s · ↓ 639 tokens)") panes. Filtered by content rather than
# a wider fixed crop because how many of these rows exist varies run to run;
# a fixed offset would either still leak them some of the time or crop real
# content away the rest of the time.
_UPDATE_BANNER_RE = re.compile(r"update (?:installed|available)|restart to update", re.IGNORECASE)
_TOKEN_COUNT_TAIL_RE = re.compile(r"\btokens?\)\s*$", re.IGNORECASE)
_DONE_TIMESTAMP_RE = re.compile(r"\bdone\s+\d{1,2}:\d{2}\s*[AP]M\b", re.IGNORECASE)
# claude's "<verb> for Ns[ Ns]" spinner line — anchored at the start and
# length-capped so a genuine reply that merely *mentions* a duration
# mid-sentence ("I'll wait for 5s before retrying, then...") isn't caught;
# a spinner line is always short and has nothing before "<verb> for Ns".
_ELAPSED_DURATION_RE = re.compile(r"^\s*(?:\S+\s+){1,2}for\s+\d+[ms](?:\s+\d+s)?\b", re.IGNORECASE)
_TRANSIENT_STATUS_MAX_LEN = 60


def _is_transient_chrome_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _UPDATE_BANNER_RE.search(stripped) or _TOKEN_COUNT_TAIL_RE.search(stripped):
        return True
    if len(stripped) > _TRANSIENT_STATUS_MAX_LEN:
        return False
    return bool(_DONE_TIMESTAMP_RE.search(stripped) or _ELAPSED_DURATION_RE.match(stripped))


def _pane_tail_window(lines: list[str], *, chrome_lines: int, tail_span: int) -> list[str]:
    """The slice of `lines` a human actually wants to see: the last
    `tail_span` rows of the pane, minus the bottom `chrome_lines` (input box,
    shortcut hint, separators — present on claude/codex/agy alike, see
    `clients/telegram/README.md` §2c), then trimmed at either edge of blank
    rows and of the transient spinner/update-banner chrome
    `_is_transient_chrome_line` recognises, so a short reply doesn't render
    as mostly empty space or a "thinking…" line mistaken for content.
    """
    if chrome_lines < 0 or tail_span <= chrome_lines:
        raise ValueError("tail_span must be greater than chrome_lines")
    end = len(lines) - chrome_lines
    start = max(0, len(lines) - tail_span)
    window = list(lines[start:end]) if end > start else []
    while window and _is_transient_chrome_line(window[0]):
        window.pop(0)
    while window and _is_transient_chrome_line(window[-1]):
        window.pop()
    return window


class PaneWatchRender:
    """One refreshing Telegram message showing a live slice of an agent's
    tmux pane — the `/watch` counterpart to `ActivityRender`, holding pane
    text instead of a structured event list. Same send-once-then-edit,
    diff-skip, rate-limited flush shape, deliberately kept separate rather
    than folded into `ActivityRender`: the two render entirely different
    content and only accidentally share a flush loop.
    """

    MAX_LEN = 3800

    def __init__(self, chat_id: int | str, agent: str) -> None:
        self.chat_id = str(chat_id)
        self.agent = agent
        self.message_id: int | None = None
        self.completed: bool = False
        self.last_flush_ts: float = 0.0
        self.last_rendered_text: str | None = None
        self.lock = threading.Lock()

    def render(self, pane_lines: list[str], *, footer: str | None = None) -> str:
        header = f"👁 <b>Watching</b> (<code>{html.escape(self.agent)}</code>)"
        body = html.escape("\n".join(pane_lines)) if pane_lines else "<i>(no content in this window yet)</i>"
        lines = [header, "", f"<pre>{body}</pre>"]
        if footer:
            lines.append(footer)
        text = "\n".join(lines)
        if len(text) > self.MAX_LEN:
            text = text[: self.MAX_LEN - 20] + "\n…[truncated]"
        return text

    def flush(
        self,
        telegram_client,
        pane_lines: list[str],
        *,
        footer: str | None = None,
        reply_markup: dict | None = None,
        clear_markup: bool = False,
        force: bool = False,
    ) -> None:
        if not telegram_client:
            return
        with self.lock:
            now = time.time()
            if not force and self.message_id is not None and not self.completed and (now - self.last_flush_ts < 1.5):
                return
        text = self.render(pane_lines, footer=footer)
        with self.lock:
            if self.message_id is not None and not force and text == self.last_rendered_text:
                return
            self.last_flush_ts = now

        markup = {"inline_keyboard": []} if clear_markup else reply_markup
        try:
            if self.message_id is None:
                resp = telegram_client.send_message(
                    self.chat_id, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup,
                )
                msg_id = resp.get("result", {}).get("message_id") if isinstance(resp, dict) else None
                with self.lock:
                    self.message_id = msg_id
                    self.last_rendered_text = text
            else:
                telegram_client.edit_message_text(
                    self.chat_id, self.message_id, text, parse_mode="HTML",
                    disable_web_page_preview=True, reply_markup=markup,
                )
                with self.lock:
                    self.last_rendered_text = text
        except Exception as exc:
            logger.debug(f"PaneWatchRender flush failed (chat={self.chat_id}, msg={self.message_id}): {exc}")


class ActivityRender:
    """Coalesces real-time agent execution events (input, tool, output)
    into a single live-updating Telegram message using editMessageText.
    """

    MAX_LEN = 3800

    def __init__(self, chat_id: int | str, agent: str) -> None:
        self.chat_id = str(chat_id)
        self.agent = agent
        self.events: list[dict] = []
        self.message_id: int | None = None
        self.completed: bool = False
        self.last_flush_ts: float = 0.0
        self.last_rendered_text: str | None = None
        self.lock = threading.Lock()

    def add_event(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)

    def finalize(self) -> None:
        with self.lock:
            self.completed = True

    def render(self) -> str:
        with self.lock:
            header = f"🛠 <b>Activity</b> (<code>{html.escape(self.agent)}</code>)"
            if self.completed:
                header += f" · completed ({len(self.events)} steps)"
            lines = [header]
            total = len(self.events)
            display_events = self.events
            omitted = 0
            if total > 20:
                omitted = total - 20
                display_events = self.events[-20:]

            if omitted > 0:
                lines.append(f"<i>… {omitted} earlier steps omitted …</i>")

            start_idx = omitted + 1
            for i, ev in enumerate(display_events, start=start_idx):
                kind = ev.get("kind", "")
                is_latest = (i == total and not self.completed)
                glyph = "⏳" if is_latest else "✓"
                if kind == "input":
                    desc = "💬 <i>input received</i>"
                elif kind == "output":
                    desc = "✍️ <i>output produced</i>"
                    glyph = "✓"
                elif kind == "tool":
                    tool_name = ev.get("tool", "tool")
                    desc = f"<code>{html.escape(tool_name)}</code>"
                else:
                    desc = html.escape(str(kind or "event"))
                lines.append(f"{i}. {glyph} {desc}")

            text = "\n".join(lines)
            if len(text) > self.MAX_LEN:
                text = text[: self.MAX_LEN - 20] + "\n…[truncated]"
            return text

    def flush(self, telegram_client, force: bool = False) -> None:
        """Send initial message or edit existing message. Debounced/throttled."""
        if not telegram_client:
            return
        with self.lock:
            if not self.events and self.message_id is None:
                return
            now = time.time()
            if not force and self.message_id is not None and not self.completed and (now - self.last_flush_ts < 0.8):
                return

        text = self.render()
        with self.lock:
            if self.message_id is not None and text == self.last_rendered_text:
                return
            self.last_flush_ts = now

        try:
            if self.message_id is None:
                resp = telegram_client.send_message(
                    self.chat_id,
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                msg_id = resp.get("result", {}).get("message_id") if isinstance(resp, dict) else None
                with self.lock:
                    self.message_id = msg_id
                    self.last_rendered_text = text
            else:
                telegram_client.edit_message_text(
                    self.chat_id,
                    self.message_id,
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                with self.lock:
                    self.last_rendered_text = text
        except Exception as exc:
            logger.debug(f"ActivityRender flush failed (chat={self.chat_id}, msg={self.message_id}): {exc}")


class TelegramBot:
    """Coalesces activity tool calls into a single Telegram progress message."""

    def __init__(
        self,
        flock_client: FlockClient,
        telegram_client: TelegramClient | None,
        cursor_store: CursorStore,
        target_agent: str = "architect",
        allowed_chat_id: int | str | None = None,
        default_tts_voice: str | None = None,
        voice_feature_enabled: bool | None = None,
        no_activity_push: bool = False,
        session_url: str | None = None,
        pane_watch_chrome_default: int = 4,
        pane_watch_chrome_overrides: dict[str, int] | None = None,
        pane_watch_tail_span: int = 12,
        pane_watch_refresh_s: float = 2.0,
        pane_watch_max_duration_s: float = 600.0,
        mini_app_url: str | None = None,
        run_allowed_commands: "frozenset[str] | None" = None,
    ):
        self.flock = flock_client
        self.telegram = telegram_client
        self.cursor_store = cursor_store
        self.target_agent = target_agent
        self.session_url = session_url or os.getenv("FLOCK_SESSION_URL", "")
        # A public HTTPS URL for clients/web/mini.html — Telegram's own
        # requirement for a web_app button, not this codebase's. Unset means
        # no Mini App has been published for this tenant, so the button is
        # simply absent (_sticky_keyboard) rather than opening a broken URL.
        self.mini_app_url = mini_app_url or os.getenv("MINI_APP_URL", "") or None
        # ⚠ Every real inbound update goes through _dispatch_update, which
        # checks this before touching anything. Without it, any Telegram user
        # who finds the bot could hire/retire/pause/resume/broadcast, not
        # just chat — the menu redesign made incoming text powerful enough
        # that "whoever messages first" is no longer an acceptable identity
        # check. See _chat_allowed for what happens when this is None.
        self.allowed_chat_id = str(allowed_chat_id) if allowed_chat_id is not None else None
        # Per-chat multi-step flows (AddTicket's title/description prompts,
        # Hire's name prompt). A chat with no entry here is not mid-flow, so a
        # plain text message from it is a prompt for its target agent, not an
        # answer to a menu.
        self.pending: dict = ChatDict()
        # Which agent a chat's plain-text prompts go to, if the operator has
        # picked one via 🎯 Message agent — falls back to target_agent
        # (--agent) when a chat has never picked one.
        self.chat_target_agent: dict = ChatDict()
        # Tenant-level feature flag for spoken TTS voice replies
        self.voice_feature_enabled = (
            (os.getenv("TELEGRAM_VOICE") == "1")
            if voice_feature_enabled is None
            else bool(voice_feature_enabled)
        )
        # Per-chat toggle for spoken TTS voice replies
        self.chat_voice_enabled: dict = ChatDict()
        self.default_tts_voice = default_tts_voice or os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE)
        self.no_activity_push = (
            (os.getenv("NO_ACTIVITY_PUSH") == "1")
            if no_activity_push is False and os.getenv("NO_ACTIVITY_PUSH") is not None
            else bool(no_activity_push)
        )
        self.activity_renders: dict = ChatDict()
        # `/watch` — one live-tail per chat. `_pane_watches` holds the
        # running thread and its stop switch; a second /watch in the same
        # chat replaces whatever it finds there rather than stacking (§2c).
        self.pane_watch_chrome_default = pane_watch_chrome_default
        self.pane_watch_chrome_overrides = dict(pane_watch_chrome_overrides or {})
        self.pane_watch_tail_span = pane_watch_tail_span
        self.pane_watch_refresh_s = pane_watch_refresh_s
        self.pane_watch_max_duration_s = pane_watch_max_duration_s
        self.pane_watches: dict = ChatDict()
        # `/run <agent> <command>` — see DEFAULT_RUN_ALLOWED_COMMANDS for why
        # this is global rather than per-CLI.
        self.run_allowed_commands = (
            frozenset(run_allowed_commands)
            if run_allowed_commands is not None
            else frozenset(DEFAULT_RUN_ALLOWED_COMMANDS)
        )

    def is_voice_enabled(self, chat_id: int | str) -> bool:
        return self.voice_feature_enabled and self.chat_voice_enabled.get(str(chat_id), False)

    def _voice_label(self, chat_id: int | str) -> str:
        return "🔊 Voice: ON" if self.is_voice_enabled(str(chat_id)) else "🔇 Voice: OFF"

    def _target_for(self, chat_id: int | str) -> str:
        return self.chat_target_agent.get(str(chat_id), self.target_agent)

    def _chat_allowed(self, chat_id: int | str) -> bool:
        """⚠ No configured chat_id means refuse everything, not allow
        everything. The historical reason --chat-id/TELEGRAM_CHAT_ID exists
        (a bot can't start a conversation, so a known chat is supplied to
        drive one directly) was never a security boundary — but incoming
        messages now are one, and defaulting an unset allowlist to "open"
        would silently hand office control to whoever finds the bot first.
        Same call the codebase already makes elsewhere for exposure
        (SPEC-bundled-clients-and-exposure.md: "when nothing is published,
        publish nothing" — an explicit yes, not an absent no). In practice
        this only bites manual/ad-hoc invocations without --chat-id:
        setup.sh's normal flow requires both TELEGRAM_BOT_TOKEN and
        TELEGRAM_CHAT_ID before it enables the bot at all, so a real
        deployment always has one.
        """
        if self.allowed_chat_id is None:
            return False
        return str(chat_id) == self.allowed_chat_id

    def enrol(self, *, timeout_s: float = 60.0) -> bool:
        """Enrol with retry.

        ⚠ container/entrypoint.sh forks the api door and this bundled client
        within the same instant — `start`/`start_client` fork-and-move-on, with
        no wait for api's HTTP server to actually be listening yet. A single
        early attempt can lose that race: measured live on the acceptance VM,
        `enrol()` got `Connection refused`, logged it, and moved on — the bot
        then ran forever unenrolled, and every subsequent send failed with
        "invalid 'as' client: must be an enrolled client with port_type
        'api'", indistinguishable from a real misconfiguration. Retrying with
        backoff for up to `timeout_s` covers the race; re-enrolling an
        already-enrolled name is safe and idempotent (API.md), so retrying
        never does anything destructive.
        """
        deadline = time.time() + timeout_s
        backoff = 1.0
        while True:
            code, body = self.flock.enrol()
            if code == 202:
                logger.info(f"Enrolled application '{self.flock.app_name}': status={code}, body={body}")
                break
            if time.time() >= deadline:
                logger.error(
                    f"Failed to enrol '{self.flock.app_name}' after {timeout_s:.0f}s "
                    f"(last status={code}, body={body}); sends will fail with "
                    f"\"invalid 'as' client\" until this succeeds."
                )
                return False
            logger.warning(f"Enrol attempt failed (status={code}, body={body}); retrying in {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 10.0)

        # Register /menu, /status with Telegram itself so they show up in the
        # client's own "/" command list instead of requiring the user to know
        # and type them blind. Best-effort: a failure here does not affect
        # anything the bot actually does, only how discoverable it is.
        if self.telegram:
            res = self.telegram.set_my_commands([
                {"command": "menu", "description": "Open the office menu (overview, tickets, agents, alerts)"},
                {"command": "status", "description": f"Quick status check for {self.target_agent}"},
                {"command": "watch", "description": "Live-tail an agent's tmux pane (/watch <agent>)"},
                {"command": "unwatch", "description": "Stop this chat's active /watch"},
                {"command": "run", "description": "Run an allowed CLI slash command, no wrapper (/run <agent> <command>)"},
                {"command": "voice", "description": "Toggle spoken voice replies (TTS)"},
            ])
            if not res.get("ok", True):
                logger.warning(f"setMyCommands failed: {res}")

        return True

    def handle_status_command(self, chat_id: int | str) -> str:
        agent = self._target_for(chat_id)
        code, presence_data = self.flock.get_presence(agent)
        code_b, board_data = self.flock.get_board(agent)

        if code != 200:
            text = f"❌ Unable to fetch status for {agent}: {presence_data.get('detail', 'error')}"
        else:
            pres = presence_data.get("presence", {})
            state = pres.get("state", "unknown")
            since = pres.get("since", "unknown")

            doing_tasks = board_data.get("doing", []) if code_b == 200 else []
            doing_str = "none"
            if doing_tasks:
                first = doing_tasks[0]
                doing_str = first.get("title", str(first)) if isinstance(first, dict) else str(first)

            text = (
                f"🤖 Agent Status: {agent}\n"
                f"State: {state} (since {since})\n"
                f"Doing: {doing_str}\n"
                f"Ingress depth: {presence_data.get('depths', {}).get('ingress', 0)}"
            )

        if self.telegram:
            self.telegram.send_message(chat_id, text)
        return text

    # ── sticky menu ──────────────────────────────────────────────────────────
    # The top-level menu is a persistent ReplyKeyboardMarkup — pinned at the
    # bottom of the chat across messages, rather than an inline keyboard
    # attached to one message that scrolls away. Its buttons are ordinary
    # text: tapping one sends its label back as a plain message (no
    # callback_query), so handle_text_message matches the label against
    # STICKY_LABELS before treating text as a prompt for target_agent.
    # Sub-flows one level down (agent pickers, pause/resume) stay inline —
    # contextual, one-shot choices tied to a specific message, which is what
    # inline keyboards are for; the sticky keyboard is for top-level nav that
    # should always be one tap away.
    #
    # ⚠ One button is dynamic: "🎯 Message: <agent>" shows the CURRENT target
    # for this chat and changes as that changes, so the keyboard is rebuilt
    # per-chat (_sticky_keyboard(chat_id)) rather than being one static
    # constant. It is matched by prefix, not exact text (see
    # handle_text_message), since its suffix varies — unlike the Sprint-Z
    # design this was modelled after, staleness here is harmless: tapping an
    # old render of this button always opens a fresh agent picker rather than
    # directly re-invoking a stored (function, args) pair, so there is
    # nothing for a stale label to get wrong.
    STICKY_TARGET_PREFIX = "🎯 Message: "
    STICKY_LABELS = {
        "📋 Overview": "ov",
        "🎫 Add ticket": "at",
        "⏯ Lifecycle": "lc",
        "👁 Watch": "wa",
        "🔔 Alerts": "al",
        "➕ Hire": "hi",
        "📢 Broadcast": "bc",
        "🙈 Hide menu": "hm",
    }

    def _sticky_keyboard(self, chat_id: int | str) -> dict:
        target_label = f"{self.STICKY_TARGET_PREFIX}{self._target_for(chat_id)}"
        last_row = ["📢 Broadcast"]
        if self.voice_feature_enabled:
            last_row.append(self._voice_label(chat_id))
        layout = [
            ["📋 Overview", "🎫 Add ticket"],
            ["⏯ Lifecycle", "👁 Watch"],
            ["🔔 Alerts", "➕ Hire"],
            [target_label],
            last_row,
            ["🙈 Hide menu"],
        ]
        keyboard = [[{"text": label} for label in row] for row in layout]
        if self.mini_app_url:
            # ⚠ web_app is a different button shape than every other sticky
            # button: tapping it opens the Mini App WebView directly,
            # client-side, and never arrives as a text message the way a tap
            # on any STICKY_LABELS button does (handle_text_message never
            # sees this one). Its own row, not folded into an existing one,
            # so it reads as a different kind of action, not just another
            # menu item. Only appears when configured (clients/web's
            # /mini.html + TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID auth path) --
            # no URL to open means no button, same "started only when
            # configured" rule the bot itself follows in entrypoint.sh.
            keyboard.append([{"text": "📊 Dashboard", "web_app": {"url": self.mini_app_url}}])
        return {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def handle_voice_toggle(self, chat_id: int | str) -> str:
        cid = str(chat_id)
        if not self.voice_feature_enabled:
            text = "Voice replies are not enabled for this tenant (set TELEGRAM_VOICE=1 in tenants/<tenant>/.env)."
            if self.telegram:
                self.telegram.send_message(cid, text)
            return text
        current = self.chat_voice_enabled.get(cid, False)
        new_state = not current
        self.chat_voice_enabled[cid] = new_state
        if new_state:
            voice_info = f" (voice: {self.default_tts_voice})" if self.default_tts_voice else ""
            text = f"🔊 Voice replies enabled for this chat{voice_info}."
        else:
            text = "🔇 Voice replies disabled for this chat."
        if self.telegram:
            self.telegram.send_message(cid, text, reply_markup=self._sticky_keyboard(cid))
        return text

    def _dispatch_menu_action(self, chat_id: int | str, code: str) -> str:
        """Shared by the sticky keyboard (text label tap) and any inline
        button still using these same short codes (e.g. a sub-flow's "◀
        Back" — see handle_callback_query)."""
        if code == "menu":
            return self.handle_menu_command(chat_id)
        if code == "ov":
            return self.handle_overview_command(chat_id)
        if code == "at":
            return self.handle_addticket_start(chat_id)
        if code == "lc":
            return self.handle_lifecycle_start(chat_id)
        if code == "al":
            return self.handle_alerts_command(chat_id)
        if code == "hi":
            return self.handle_hire_start(chat_id)
        if code == "ta":
            return self.handle_message_agent_start(chat_id)
        if code == "wa":
            return self.handle_watch_start(chat_id)
        if code == "bc":
            return self.handle_broadcast_start(chat_id)
        if code == "vt":
            return self.handle_voice_toggle(chat_id)
        if code == "hm":
            return self.handle_hide_menu_command(chat_id)
        return ""

    def _tmux_agents(self) -> list[str]:
        """Enrolled agents with a terminal window — the ones a person can add a
        ticket to or pause/resume. Excludes api clients like this bot itself
        (LLD-office.md / clients/web's own port_type == "tmux" filter)."""
        code, data = self.flock.get_agents()
        if code != 200:
            return []
        result = []
        for name in data.get("agents", []):
            pcode, pdata = self.flock.get_presence(name)
            if pcode == 200 and pdata.get("port_type") == "tmux":
                result.append(name)
        return result

    def handle_menu_command(self, chat_id: int | str) -> str:
        text = "h-flock menu — pinned below, always one tap away:"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup=self._sticky_keyboard(chat_id))
        return text

    def handle_hide_menu_command(self, chat_id: int | str) -> str:
        """A persistent `ReplyKeyboardMarkup` (`is_persistent: true`, what
        `/menu` sends) cannot actually be dismissed from the phone —
        Telegram's own "collapse" gesture is a temporary panel toggle, and
        the keyboard comes back on the next refresh. The only real removal
        is the bot explicitly sending `reply_markup: {"remove_keyboard":
        true}` (`ReplyKeyboardRemove`) — nothing did that before this.
        `/menu` (unchanged) brings it straight back."""
        text = "Menu hidden. Send /menu to bring it back."
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup={"remove_keyboard": True})
        return text

    def handle_overview_command(self, chat_id: int | str) -> str:
        # Three calls, not one (API.md §4a): agent list, presence per agent,
        # boards in bulk. GET /agents/{agent} never carries the open ticket.
        agents = self._tmux_agents()
        board_code, board_data = self.flock.get_all_boards()
        boards_by_agent = {}
        if board_code == 200:
            for entry in board_data.get("agents", []):
                boards_by_agent[entry.get("agent")] = entry

        icons = {"working": "●", "idle": "○", "blocked": "⊘", "unknown": "?"}
        lines = ["📋 Office overview"]
        if not agents:
            lines.append("No tmux agents enrolled.")
        for agent in agents:
            pcode, pdata = self.flock.get_presence(agent)
            state = pdata.get("presence", {}).get("state", "unknown") if pcode == 200 else "unknown"
            doing = boards_by_agent.get(agent, {}).get("doing", [])
            ticket = "no open ticket"
            if doing:
                first = doing[0]
                ticket = first.get("title", str(first)) if isinstance(first, dict) else str(first)
            lines.append(f"{icons.get(state, '?')} {agent} — {state} — {ticket}")
        text = "\n".join(lines)
        if self.telegram:
            self.telegram.send_message(chat_id, text)
        return text

    def handle_addticket_start(self, chat_id: int | str) -> str:
        agents = self._tmux_agents()
        if not agents:
            text = "No agents enrolled to add a ticket to."
            if self.telegram:
                self.telegram.send_message(chat_id, text)
            return text
        text = "Add a ticket — pick an agent:"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup=_agent_picker_keyboard(agents, "at"))
        return text

    def handle_addticket_pick_agent(self, chat_id: int | str, agent: str) -> str:
        cid = str(chat_id)
        self.pending[cid] = {"flow": "addticket", "agent": agent, "stage": "title"}
        text = f"Ticket title for {agent}? (/cancel to abort)"
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_addticket_priority(self, chat_id: int | str, priority: str) -> str:
        cid = str(chat_id)
        state = self.pending.get(cid)
        if not state or state.get("flow") != "addticket" or state.get("stage") != "priority":
            return ""
        agent, title = state["agent"], state["title"]
        description = state.get("description", "")
        del self.pending[cid]
        if self.telegram:
            self.telegram.send_chat_action(cid)
        code, resp = self.flock.add_ticket(agent, title, description, priority)
        if code == 202:
            text = f"✅ Ticket added to {agent}: {title} [{priority}]"
        else:
            text = f"❌ Failed to add ticket: {resp.get('detail', 'error')}"
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_lifecycle_start(self, chat_id: int | str) -> str:
        agents = self._tmux_agents()
        if not agents:
            text = "No agents enrolled."
            if self.telegram:
                self.telegram.send_message(chat_id, text)
            return text
        text = "Lifecycle — pick an agent:"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup=_agent_picker_keyboard(agents, "lc"))
        return text

    def handle_lifecycle_pick_agent(self, chat_id: int | str, agent: str) -> str:
        buttons = [
            [
                {"text": "⏸ Pause", "callback_data": f"lp:{agent}"},
                {"text": "▶ Resume", "callback_data": f"lr:{agent}"},
            ],
            [{"text": "🗑 Retire", "callback_data": f"lret:{agent}"}],
            [{"text": "◀ Back", "callback_data": "lc"}],
        ]
        text = f"{agent} — pause, resume, or retire?"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup={"inline_keyboard": buttons})
        return text

    def handle_lifecycle_control(self, chat_id: int | str, kind: str, agent: str) -> str:
        if self.telegram:
            self.telegram.send_chat_action(chat_id)
        code, resp = self.flock.control_agent(kind, agent)
        verb = "paused" if kind == "PauseAgent" else "resumed"
        if code == 202:
            text = f"✅ {agent} {verb}."
        else:
            text = f"❌ Failed to {verb[:-1]} {agent}: {resp.get('detail', 'error')}"
        if self.telegram:
            self.telegram.send_message(chat_id, text)
        return text

    def handle_retire_start(self, chat_id: int | str, agent: str) -> str:
        # ⚠ Same confirm-by-typing-the-name pattern clients/web/ui/lifecycle.js
        # uses for retire, not a yes/no tap — StopAgent removes roster
        # membership and identity state (queues and boards are kept), and a
        # single misplaced tap is too cheap a way to do that.
        cid = str(chat_id)
        self.pending[cid] = {"flow": "retire", "agent": agent}
        text = f"Type '{agent}' exactly to confirm retiring them (queues and boards are kept; /cancel to abort)."
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_message_agent_start(self, chat_id: int | str) -> str:
        agents = self._tmux_agents()
        if not agents:
            text = "No agents enrolled to message."
            if self.telegram:
                self.telegram.send_message(chat_id, text)
            return text
        text = f"Currently messaging {self._target_for(chat_id)} — pick a different agent:"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup=_agent_picker_keyboard(agents, "ta"))
        return text

    def handle_message_agent_pick(self, chat_id: int | str, agent: str) -> str:
        cid = str(chat_id)
        self.chat_target_agent[cid] = agent
        text = f"🎯 Now messaging {agent}. Send any message to reach them."
        if self.telegram:
            # Re-send the sticky keyboard too -- its "🎯 Message: ..." button
            # is stale the instant the target changes, and nothing else
            # would refresh it short of the user sending /menu again.
            self.telegram.send_message(cid, text, reply_markup=self._sticky_keyboard(cid))
        return text

    def _validate_mention_target(self, name: str) -> str | None:
        """`None` if `name` is a valid, existing tmux agent an `@mention` may
        route to; otherwise an error string ready to send back to the chat.
        Checked against the same name shape `hire` enforces
        (`_AGENT_NAME`/`_RESERVED_AGENT_NAMES`) and against the live roster
        (`_tmux_agents()`, so a real but non-tmux client — `telegram` itself,
        `host` — is refused the same as an unknown name, never silently
        misrouted or dead-lettered onto a mailbox/queue that can't paste it
        anywhere). Shared by the text `@mention` path (`handle_mention_prompt`)
        and the photo path (`handle_photo_message`) — one place either kind
        of `@mention` gets validated.
        """
        if not _AGENT_NAME.match(name) or name in _RESERVED_AGENT_NAMES or name not in self._tmux_agents():
            return f"@{name} isn't a known agent to message. Use /menu to see who's enrolled."
        return None

    def handle_mention_prompt(self, chat_id: int | str, name: str, rest: str) -> str:
        """A leading "@name ..." — one-off destination override for this
        message only; `chat_target_agent` is untouched, so the next plain
        message still goes to whatever it was already set to."""
        cid = str(chat_id)
        if not rest:
            text = f"@{name} — nothing to send. Usage: @{name} your message"
            if self.telegram:
                self.telegram.send_message(cid, text)
            return text
        error = self._validate_mention_target(name)
        if error:
            if self.telegram:
                self.telegram.send_message(cid, error)
            return error
        return self.handle_user_prompt(cid, rest, agent_override=name)

    def handle_run_command(self, chat_id: int | str, rest: str) -> str:
        """`/run <agent> <command>` — raw, unwrapped pane injection: a
        Command-kind envelope instead of the Message-kind shorthand every
        other text path uses, so a native CLI slash command (e.g. Claude
        Code's `/clear`) is interpreted by the underlying CLI instead of
        read as chat text saying "/clear". One-off, same as `@mention` —
        `chat_target_agent` is never touched by this.

        ⚠ Bounded to `self.run_allowed_commands` (`DEFAULT_RUN_ALLOWED_COMMANDS`
        unless overridden), an exact, whole-string match — not a prefix a
        caller can tack arguments onto. A full Command passthrough here was
        the first design and was deliberately rejected: unlike README §2a's
        "not exposed at all" objection, which was about a one-tap *button*,
        this is typed by hand — but it is still unbounded remote execution
        with no live view of the pane, exactly the property that objection
        cared about. A fixed, pre-vetted allowlist of session-hygiene
        commands is the resolution, not a loophole around it.

        ⚠ Single-line only, checked before the allowlist. `command_opener`
        pastes the text with one trailing newline appended — an allowed
        command's own text carrying an embedded newline would submit it as
        one line and then paste a second, completely unvetted line of raw
        input right after, defeating the allowlist entirely. None of
        `DEFAULT_RUN_ALLOWED_COMMANDS`' own entries need one; a rejection
        here only ever fires on something a caller added deliberately.

        ⚠ No separate operator/chat_id restriction here beyond the existing
        single `allowed_chat_id` gate every command already goes through
        (`_chat_allowed`) — there is no concept of distinct "operators"
        yet for one chat_id to be restricted relative to another. Revisit
        once that lands; not building speculative restriction infra for a
        model that doesn't exist yet.
        """
        cid = str(chat_id)

        def _reject(text: str) -> str:
            if self.telegram:
                self.telegram.send_message(cid, text)
            return text

        parts = rest.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return _reject("Usage: /run <agent> <command>")
        name, command_text = parts[0].lower(), parts[1]
        error = self._validate_mention_target(name)
        if error:
            return _reject(error)
        if "\n" in command_text or "\r" in command_text:
            return _reject("/run commands must be a single line.")
        if command_text not in self.run_allowed_commands:
            allowed = ", ".join(sorted(self.run_allowed_commands)) or "(none configured)"
            return _reject(f"'{command_text}' isn't an allowed /run command. Allowed: {allowed}")
        return self.handle_user_prompt(cid, command_text, agent_override=name, raw=True)

    def handle_photo_message(self, chat_id: int | str, photo_sizes: list[dict], caption: str) -> str:
        """A photo update never carries `text` — `_dispatch_update`'s
        text-only early return would otherwise silently drop it, which is
        the bug this closes. `photo_sizes[-1]` is Telegram's own convention
        for "smallest to largest" — the best *compressed* version this bot
        ever sees; a "photo" upload is always recompressed by Telegram
        itself, full original quality is only available via a "document"
        upload instead (`handle_document_message`). Shared mechanics —
        routing, size checks, download, sending the `Attachment` envelope —
        live in `_send_incoming_file_as_attachment`.
        """
        if not photo_sizes:
            return ""
        largest = photo_sizes[-1]
        return self._send_incoming_file_as_attachment(
            chat_id, caption, largest.get("file_id"), largest.get("file_size"),
            mime_type="image/jpeg", filename=None, fallback_extension=".jpg", label="photo",
        )

    def handle_document_message(self, chat_id: int | str, document: dict, caption: str) -> str:
        """A "document" upload (send as file, not as photo) is Telegram's
        uncompressed path — `message.document` is a single object with its
        own `file_id`/`file_name`/`mime_type`, not an array of `PhotoSize`
        like `message.photo`, and not always JPEG. Shares every mechanic
        with `handle_photo_message` beyond that (routing, both size
        ceilings, download, sending the envelope) via
        `_send_incoming_file_as_attachment` rather than a second copy.
        """
        if not document:
            return ""
        return self._send_incoming_file_as_attachment(
            chat_id, caption, document.get("file_id"), document.get("file_size"),
            mime_type=document.get("mime_type") or "application/octet-stream",
            filename=document.get("file_name"), fallback_extension="", label="file",
        )

    def _send_incoming_file_as_attachment(
        self,
        chat_id: int | str,
        caption: str,
        file_id: str | None,
        reported_size: int | None,
        mime_type: str,
        filename: str | None,
        fallback_extension: str,
        label: str,
    ) -> str:
        """Shared by `handle_photo_message` and `handle_document_message`.
        Routes exactly like a text message: the caption is the message
        body, and an `@mention` prefix on it overrides the destination
        one-off, same as typed text (`_parse_mention`/
        `_validate_mention_target` — no second routing implementation).
        `filename` is Telegram's own name when it already has one (a
        "document" always does); `None` for a "photo", which only ever
        gives a `file_path` to derive one from once downloaded — either way
        the result is run through the same basename validation with the
        same generated-name fallback, never trusted outright. `mime_type`
        is validated the same way, falling back to
        `application/octet-stream` rather than rejecting a file whose
        content is fine but whose reported type isn't spec-shaped.

        Sends a real `Attachment` envelope (`docs/CONTRACTS.md`) — file
        bytes on the bus, `content_base64`, not a path shared out of band.
        The tmux opener owns writing it to
        `/workdir/<recipient>/attachments/<stream_id>/` and everything about
        that directory's lifecycle (confirmed with tmux directly); this
        method never touches a filesystem at all.
        """
        cid = str(chat_id)
        caption = (caption or "").strip()
        agent_override: str | None = None
        body = caption
        mention = _parse_mention(caption)
        if mention is not None:
            name, rest = mention
            error = self._validate_mention_target(name)
            if error:
                if self.telegram:
                    self.telegram.send_message(cid, error)
                return error
            agent_override = name
            body = rest

        agent = agent_override or self._target_for(cid)

        if not file_id or not self.telegram:
            return ""

        code, presence_data = self.flock.get_presence(agent)
        state = presence_data.get("presence", {}).get("state") if code == 200 else "unknown"
        if state == "blocked":
            reply = f"{agent} is not accepting messages right now"
            self.telegram.send_message(cid, reply)
            return reply

        # ⚠ Two different ceilings, checked separately, not the same limit
        # twice: TELEGRAM_MAX_FILE_BYTES (20MB) is what Telegram will let a
        # bot download at all; ATTACHMENT_MAX_BYTES (10MB, docs/CONTRACTS.md)
        # is what the bus will accept as decoded Attachment content. A file
        # between the two downloads fine and must still be refused here.
        if reported_size and reported_size > TELEGRAM_MAX_FILE_BYTES:
            reply = f"That {label} is too large to fetch (Telegram's own 20MB bot download limit)."
            self.telegram.send_message(cid, reply)
            return reply

        self.telegram.send_chat_action(cid)

        info = self.telegram.request("getFile", {"file_id": file_id})
        file_path = info.get("result", {}).get("file_path") if info.get("ok") else None
        if not file_path:
            reply = f"Couldn't fetch that {label} from Telegram: {info.get('description', 'unknown error')}"
            self.telegram.send_message(cid, reply)
            return reply

        data = self.telegram.download_file(file_path)
        if not data:
            reply = f"Couldn't download that {label} from Telegram."
            self.telegram.send_message(cid, reply)
            return reply
        if len(data) > ATTACHMENT_MAX_BYTES:
            reply = f"That {label} is too large to send as an attachment (10MB limit)."
            self.telegram.send_message(cid, reply)
            return reply

        resolved_filename = filename or pathlib.Path(file_path).name
        if not _valid_attachment_filename(resolved_filename):
            resolved_filename = f"telegram-{label}-{int(time.time())}-{uuid.uuid4().hex[:8]}{fallback_extension}"
        resolved_mime_type = mime_type if _valid_attachment_mime_type(mime_type) else "application/octet-stream"

        code, resp = self.flock.send_attachment(
            agent, resolved_filename, resolved_mime_type, base64.b64encode(data).decode("ascii"), caption=body or None,
        )
        if code != 202:
            reply = f"Failed to send that {label} to {agent}: {resp.get('detail', 'error')}"
            self.telegram.send_message(cid, reply)
            return reply

        reply = f"✅ {label.capitalize()} sent to {agent}."
        self.telegram.send_message(cid, reply)
        return reply

    # ── /watch — live-tail an agent's tmux pane ─────────────────────────────
    # One watch per chat (§2c, clients/telegram/README.md): picking a new
    # agent, or a new /watch of the same one, replaces whatever is already
    # running there rather than stacking watchers.

    def handle_watch_start(self, chat_id: int | str) -> str:
        agents = self._tmux_agents()
        if not agents:
            text = "No agents enrolled to watch."
            if self.telegram:
                self.telegram.send_message(chat_id, text)
            return text
        text = "Watch — pick an agent's live terminal:"
        if self.telegram:
            self.telegram.send_message(chat_id, text, reply_markup=_agent_picker_keyboard(agents, "wp"))
        return text

    def handle_watch_pick(self, chat_id: int | str, agent: str) -> str:
        cid = str(chat_id)
        if agent not in self._tmux_agents():
            text = f"Unknown agent: {agent}"
            if self.telegram:
                self.telegram.send_message(cid, text)
            return text
        self._stop_pane_watch(cid)
        render = PaneWatchRender(cid, agent)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_pane_watch,
            args=(cid, agent, render, stop_event),
            daemon=True,
            name=f"pane-watch-{agent}",
        )
        self.pane_watches[cid] = {
            "agent": agent, "stop_event": stop_event, "render": render, "thread": thread,
        }
        thread.start()
        return f"👁 Watching {agent}…"

    def _stop_pane_watch(self, chat_id: int | str) -> str | None:
        """Signal any watch running in this chat to end. Does not join — the
        watcher thread sends its own final message (§ below) and clears
        itself out of `pane_watches` on the way out."""
        state = self.pane_watches.get(str(chat_id))
        if not state:
            return None
        state["stop_event"].set()
        return state["agent"]

    def handle_watch_stop(self, chat_id: int | str, agent: str) -> str:
        """The inline "⏹ Stop watching" button on the live-tail message
        itself. `answer_callback_query` (called generically for every
        callback) is the only acknowledgement — the watched message updating
        to its final state a moment later is the real feedback."""
        state = self.pane_watches.get(str(chat_id))
        if not state or state["agent"] != agent:
            return ""
        state["stop_event"].set()
        return f"stopping watch on {agent}"

    def handle_watch_stop_command(self, chat_id: int | str) -> str:
        cid = str(chat_id)
        agent = self._stop_pane_watch(cid)
        text = f"⏹ Stopping watch on {agent}…" if agent else "No active watch in this chat."
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_hire_start(self, chat_id: int | str) -> str:
        cid = str(chat_id)
        self.pending[cid] = {"flow": "hire", "stage": "name"}
        text = "New agent's name? (lowercase letters, digits, hyphens; not all digits; /cancel to abort)"
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_broadcast_start(self, chat_id: int | str) -> str:
        cid = str(chat_id)
        self.pending[cid] = {"flow": "broadcast"}
        text = "Broadcast to every agent — type the message, or /cancel to abort."
        if self.telegram:
            self.telegram.send_message(cid, text)
        return text

    def handle_alerts_command(self, chat_id: int | str, limit: int = 10) -> str:
        # GET /alerts has no "give me the tail" query (see FlockClient.get_alerts);
        # fetch up to the stream's own retention cap and slice the tail here.
        code, data = self.flock.get_alerts(limit=1000)
        if code != 200:
            text = f"❌ Unable to fetch alerts: {data.get('detail', 'error')}"
        else:
            alerts = data.get("alerts", [])[-limit:]
            if not alerts:
                text = "🔔 No alerts."
            else:
                text = "\n".join(["🔔 Recent alerts"] + [render_alert(a) for a in alerts])
        if self.telegram:
            self.telegram.send_message(chat_id, text)
        return text

    def handle_pending_text(self, chat_id: int | str, text: str) -> str | None:
        """Consume `text` as an answer to a pending flow's prompt. Returns None
        (leaving `text` untouched by the caller) when the chat has no flow open."""
        cid = str(chat_id)
        state = self.pending.get(cid)
        if not state:
            return None
        if text.strip() == "/cancel":
            del self.pending[cid]
            reply = "Cancelled."
            if self.telegram:
                self.telegram.send_message(cid, reply)
            return reply

        if state["flow"] == "addticket":
            if state["stage"] == "title":
                state["title"] = text.strip()
                state["stage"] = "description"
                reply = "Description? (send - to skip, /cancel to abort)"
                if self.telegram:
                    self.telegram.send_message(cid, reply)
                return reply
            if state["stage"] == "description":
                state["description"] = "" if text.strip() == "-" else text.strip()
                state["stage"] = "priority"
                buttons = [[
                    {"text": "🔵 Low", "callback_data": "ap:low"},
                    {"text": "⚪ Normal", "callback_data": "ap:normal"},
                    {"text": "🔴 High", "callback_data": "ap:high"},
                ]]
                reply = "Priority?"
                if self.telegram:
                    self.telegram.send_message(cid, reply, reply_markup={"inline_keyboard": buttons})
                return reply
            # stage == "priority": this step is answered by tapping a button
            # (handle_addticket_priority), not typed text — stray text here
            # just gets pointed back at the buttons rather than silently lost.
            reply = "Tap a priority button above, or /cancel."
            if self.telegram:
                self.telegram.send_message(cid, reply)
            return reply

        if state["flow"] == "hire":
            if state["stage"] == "name":
                name = text.strip()
                if not _AGENT_NAME.match(name) or name in _RESERVED_AGENT_NAMES:
                    reply = "That name won't work — lowercase letters, digits and hyphens, not all digits, not a reserved word. Try again, or /cancel."
                    if self.telegram:
                        self.telegram.send_message(cid, reply)
                    return reply  # stay in "name" stage; do not consume the pending flow
                state["name"] = name
                state["stage"] = "profile"
                # ⚠ No picker: office profiles reads Redis directly and has no
                # REST equivalent, so this client cannot list valid accounts
                # ahead of time (see FlockClient.hire_agent). A bad name still
                # gets a clear error, listing the valid ones, from the api.
                reply = f"Profile for {name}? (account/profile name, or - for the default; /cancel to abort)"
                if self.telegram:
                    self.telegram.send_message(cid, reply)
                return reply

            if state["stage"] == "profile":
                state["profile"] = None if text.strip() == "-" else text.strip()
                state["stage"] = "provider"
                reply = f"Provider for {state['name']}? (named local model endpoint, or - for the default; /cancel to abort)"
                if self.telegram:
                    self.telegram.send_message(cid, reply)
                return reply

            # stage == "provider"
            provider = None if text.strip() == "-" else text.strip()
            name, profile = state["name"], state["profile"]
            del self.pending[cid]
            if self.telegram:
                self.telegram.send_chat_action(cid)
            code, resp = self.flock.hire_agent(name, profile=profile, provider=provider)
            if code == 202:
                extras = ", ".join(f"{k} {v}" for k, v in (("profile", profile), ("provider", provider)) if v)
                reply = f"✅ Hire accepted for {name}" + (f" ({extras})" if extras else "") + " · window and CLI follow shortly."
            else:
                reply = f"❌ Failed to hire {name}: {resp.get('detail', 'error')}"
            if self.telegram:
                self.telegram.send_message(cid, reply)
            return reply

        if state["flow"] == "retire":
            agent = state["agent"]
            if text.strip() != agent:
                reply = f"That doesn't match '{agent}' — type it exactly to confirm, or /cancel."
                if self.telegram:
                    self.telegram.send_message(cid, reply)
                return reply  # stay open for retry, same as the web console's disabled-until-match button
            del self.pending[cid]
            if self.telegram:
                self.telegram.send_chat_action(cid)
            code, resp = self.flock.retire_agent(agent)
            if code == 202:
                reply = f"✅ {agent} retired · queues and boards retained for a later re-hire."
            else:
                reply = f"❌ Failed to retire {agent}: {resp.get('detail', 'error')}"
            if self.telegram:
                self.telegram.send_message(cid, reply)
            return reply

        if state["flow"] == "broadcast":
            message = text.strip()
            del self.pending[cid]
            if self.telegram:
                self.telegram.send_chat_action(cid)
            code, resp = self.flock.send_message("all", message)
            if code == 202:
                reply = "📢 Broadcast sent."
            else:
                reply = f"❌ Broadcast failed: {resp.get('detail', 'error')}"
            if self.telegram:
                self.telegram.send_message(cid, reply)
            return reply

        return None

    def handle_callback_query(self, chat_id: int | str, callback_id: str, data: str) -> str:
        if self.telegram:
            self.telegram.answer_callback_query(callback_id)
        if data in ("menu", "ov", "at", "lc", "al", "hi", "ta", "vt", "wa"):
            return self._dispatch_menu_action(chat_id, data)
        if data.startswith("wp:"):
            return self.handle_watch_pick(chat_id, data[len("wp:"):])
        if data.startswith("ws:"):
            return self.handle_watch_stop(chat_id, data[len("ws:"):])
        if data.startswith("at:"):
            return self.handle_addticket_pick_agent(chat_id, data[len("at:"):])
        if data.startswith("lc:"):
            return self.handle_lifecycle_pick_agent(chat_id, data[len("lc:"):])
        if data.startswith("lp:"):
            return self.handle_lifecycle_control(chat_id, "PauseAgent", data[len("lp:"):])
        if data.startswith("lr:"):
            return self.handle_lifecycle_control(chat_id, "ResumeAgent", data[len("lr:"):])
        if data.startswith("lret:"):
            return self.handle_retire_start(chat_id, data[len("lret:"):])
        if data.startswith("ta:"):
            return self.handle_message_agent_pick(chat_id, data[len("ta:"):])
        if data.startswith("ap:"):
            return self.handle_addticket_priority(chat_id, data[len("ap:"):])
        return ""

    def handle_text_message(self, chat_id: int | str, text: str) -> str:
        """Entry point for a plain (non-callback) chat message: a pending
        flow's answer, a sticky-keyboard tap, a known command, or a prompt
        for this chat's target agent."""
        pending_reply = self.handle_pending_text(chat_id, text)
        if pending_reply is not None:
            return pending_reply
        if text in self.STICKY_LABELS:
            return self._dispatch_menu_action(chat_id, self.STICKY_LABELS[text])
        if text.startswith(self.STICKY_TARGET_PREFIX):
            return self.handle_message_agent_start(chat_id)
        if text.startswith("🔊 Voice") or text.startswith("🔇 Voice") or text in ("/voice", "/tts"):
            return self.handle_voice_toggle(chat_id)
        if text == "/menu":
            return self.handle_menu_command(chat_id)
        if text == "/status":
            return self.handle_status_command(chat_id)
        if text == "/watch":
            return self.handle_watch_start(chat_id)
        if text.startswith("/watch "):
            return self.handle_watch_pick(chat_id, text[len("/watch "):].strip())
        if text == "/unwatch":
            return self.handle_watch_stop_command(chat_id)
        if text == "/run" or text.startswith("/run "):
            return self.handle_run_command(chat_id, text[len("/run"):].strip())
        if text.startswith("@"):
            mention = _parse_mention(text)
            if mention is not None:
                return self.handle_mention_prompt(chat_id, *mention)
        return self.handle_user_prompt(chat_id, text)

    def _get_activity_tail(self, agent: str) -> str | None:
        """Fetch the current latest activity cursor for an agent before prompting."""
        try:
            cursor = None
            while True:
                code, data = self.flock.get_activity(agent, after=cursor, limit=1000)
                if code != 200:
                    break
                items = data.get("activity", [])
                if not items:
                    break
                cursor = data.get("next_cursor")
                if len(items) < 1000:
                    break
            return cursor
        except Exception as exc:
            logger.debug(f"Failed to fetch activity tail for {agent}: {exc}")
        return None

    def _watch_activity(
        self,
        chat_id: int | str,
        agent: str,
        after_cursor: str | None,
        render: ActivityRender,
        timeout_s: float = 300.0,
        stream_fn=None,
    ) -> None:
        """Background thread consuming activity events for a prompted turn."""
        stream_gen = stream_fn or (lambda: self.flock.stream_activity(agent, after=after_cursor))
        start_time = time.time()
        try:
            for event in stream_gen():
                if render.completed or (time.time() - start_time > timeout_s):
                    break
                if not isinstance(event, dict):
                    continue
                if event.get("agent") and event.get("agent") != agent:
                    continue
                render.add_event(event)
                render.flush(self.telegram)
        except Exception as exc:
            logger.debug(f"Activity watcher exception for {agent}: {exc}")
        finally:
            if render.events and render.message_id:
                render.finalize()
                render.flush(self.telegram, force=True)

    _SNAPSHOT_PREFIX = "\x1b[2J\x1b[H"

    def _run_pane_watch(
        self,
        chat_id: int | str,
        agent: str,
        render: "PaneWatchRender",
        stop_event: threading.Event,
        ws_connect_fn=None,
    ) -> None:
        """Background thread behind `/watch`: connects the session door once,
        and on a fixed cadence asks control.py for one fresh `capture-pane`
        (`{"refresh": true}`, `LLD-session.md` §3) rather than reconstructing
        a screen from the live `%output` diff stream — a client-side terminal
        emulator is more machinery than a periodic snapshot needs. A snapshot
        frame is recognised by the `\\x1b[2J\\x1b[H` clear-and-home prefix
        every capture-pane snapshot starts with (LLD-session §3); anything
        else received in between (an incremental live diff from the same
        persistent subscription) is drained and discarded — we only ever
        render a full fresh frame, never a partial one.
        """
        cid = str(chat_id)
        reply_markup = {"inline_keyboard": [[{"text": "⏹ Stop watching", "callback_data": f"ws:{agent}"}]]}
        chrome = self.pane_watch_chrome_overrides.get(agent, self.pane_watch_chrome_default)
        tail_span = max(self.pane_watch_tail_span, chrome + 1)
        start_time = time.time()
        saw_working = False
        stop_reason = "stopped by request"
        last_window: list[str] = []

        def window_from(data: str) -> list[str]:
            return _pane_tail_window(_strip_ansi(data).split("\n"), chrome_lines=chrome, tail_span=tail_span)

        try:
            base_url = getattr(self.flock, "base_url", "http://127.0.0.1:8080")
            token = getattr(self.flock, "token", "")
            ssl_ctx = getattr(self.flock, "ssl_context", None)
            ws_url = _derive_session_url(base_url, self.session_url or "")

            def _default_connect():
                headers = {"Authorization": f"Bearer {token}"}
                return ws_connect(ws_url, additional_headers=headers, ssl=ssl_ctx)

            connect_fn = ws_connect_fn or _default_connect

            with connect_fn() as ws:
                while True:
                    if stop_event.is_set():
                        stop_reason = "stopped by request"
                        break
                    if time.time() - start_time > self.pane_watch_max_duration_s:
                        stop_reason = f"stopped after {int(self.pane_watch_max_duration_s)}s (time limit)"
                        break

                    ws.send(json.dumps({"subscribe": [agent], "mode": "read-only", "refresh": True}))

                    snapshot_text = None
                    drain_deadline = time.time() + 5.0
                    while time.time() < drain_deadline:
                        try:
                            msg = ws.recv(timeout=max(0.0, drain_deadline - time.time()))
                        except TimeoutError:
                            break
                        if msg is None:
                            break
                        try:
                            payload = json.loads(msg)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        data = payload.get("data")
                        if payload.get("agent") != agent or not isinstance(data, str):
                            continue
                        if data.startswith(self._SNAPSHOT_PREFIX):
                            snapshot_text = data
                            break

                    if snapshot_text is not None:
                        last_window = window_from(snapshot_text)

                    pcode, pdata = self.flock.get_presence(agent)
                    state = pdata.get("presence", {}).get("state") if pcode == 200 else None
                    if state == "working":
                        saw_working = True
                    elif state == "idle" and saw_working:
                        stop_reason = f"stopped: {agent} went idle"
                        render.flush(self.telegram, last_window, reply_markup=reply_markup)
                        break

                    render.flush(self.telegram, last_window, reply_markup=reply_markup)

                    if stop_event.wait(self.pane_watch_refresh_s):
                        stop_reason = "stopped by request"
                        break
        except Exception as exc:
            logger.debug(f"Pane watch exception for {agent}: {exc}")
            stop_reason = "stopped: session connection lost"
        finally:
            render.completed = True
            render.flush(
                self.telegram, last_window,
                footer=f"<i>⏹ {html.escape(stop_reason)}</i>",
                clear_markup=True, force=True,
            )
            # Only clear this chat's slot if a newer /watch hasn't already
            # replaced it — see handle_watch_pick.
            if self.pane_watches.get(cid, {}).get("stop_event") is stop_event:
                self.pane_watches.pop(cid, None)

    def finalize_activity(self, chat_id: int | str, agent: str) -> None:
        """Finalize and flush any live activity message for (chat_id, agent)."""
        key = f"{str(chat_id)}:{agent}"
        render = self.activity_renders.pop(key, None)
        if render:
            render.finalize()
            render.flush(self.telegram, force=True)

    def handle_user_prompt(
        self, chat_id: int | str, text: str, *, agent_override: str | None = None, raw: bool = False
    ) -> str:
        """Post `text` to this chat's target agent (§ 🎯 Message agent,
        default target_agent/--agent) and return immediately. `agent_override`
        is handle_mention_prompt's one-off "@name ..." destination — used for
        this call only, never written to `chat_target_agent`. `raw` is
        handle_run_command's "/run <agent> <text>" — sends a Command-kind
        envelope instead of a Message-kind one (see FlockClient.send_command),
        otherwise identical: same presence/blocked gate, same activity
        watcher, same one-off (never persistent) destination.

        ⚠ No wait, no reply capture here — that used to be a `while not
        completed` loop polling for target_agent's reply, unbounded, run
        inline in the polling loop. It matched nothing about how delivery
        actually works: POST /agents/{agent}/envelopes returns 202
        immediately and always: the switch/port/api chain is fire-and-forget
        all the way to the destination's inbox stream, nothing in it waits on
        anything. The blocking was invented here, not required by the
        transport, and it broke badly in production — one chat waiting
        forever for a reply froze the poller for every other chat too
        (measured live on the acceptance VM). ReplyPusher is what delivers
        the eventual reply now, on its own schedule, matching the actual
        fire-and-forget model.
        """
        cid = str(chat_id)
        agent = agent_override or self._target_for(cid)
        if self.telegram:
            self.telegram.send_chat_action(cid)
        code, presence_data = self.flock.get_presence(agent)
        state = presence_data.get("presence", {}).get("state") if code == 200 else "unknown"

        if state == "blocked":
            reply_text = f"{agent} is not accepting messages right now"
            if self.telegram:
                self.telegram.send_message(cid, reply_text)
            return reply_text

        # Start live activity watcher if enabled
        if not self.no_activity_push and self.telegram:
            tail_cursor = self._get_activity_tail(agent)
            render = ActivityRender(cid, agent)
            key = f"{cid}:{agent}"
            old_render = self.activity_renders.get(key)
            if old_render:
                old_render.finalize()
                old_render.flush(self.telegram, force=True)
            self.activity_renders[key] = render

            watcher = threading.Thread(
                target=self._watch_activity,
                args=(cid, agent, tail_cursor, render),
                daemon=True,
                name=f"activity-watcher-{agent}",
            )
            watcher.start()

        code, resp = self.flock.send_command(agent, text) if raw else self.flock.send_message(agent, text)
        if code != 202:
            self.finalize_activity(cid, agent)
            verb = "run on" if raw else "send message to"
            reply_text = f"Failed to {verb} {agent}: {resp.get('detail', 'error')}"
            if self.telegram:
                self.telegram.send_message(cid, reply_text)
            return reply_text

        reply_text = f"✅ Ran on {agent}." if raw else f"✅ Sent to {agent}."
        if self.telegram:
            self.telegram.send_message(cid, reply_text)
        return reply_text

    def _dispatch_update(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            chat_id = str(callback["message"]["chat"]["id"])
            if not self._chat_allowed(chat_id):
                # ⚠ No reply, no answered callback query, nothing — silence
                # tells an unauthorized sender less than a rejection would
                # (not even that a bot is listening on the other end).
                return
            self.handle_callback_query(chat_id, callback["id"], callback.get("data", ""))
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat_id = str(msg["chat"]["id"])
        if not self._chat_allowed(chat_id):
            return

        photo_sizes = msg.get("photo")
        if photo_sizes:
            self.handle_photo_message(chat_id, photo_sizes, msg.get("caption", ""))
            return

        document = msg.get("document")
        if document:
            self.handle_document_message(chat_id, document, msg.get("caption", ""))
            return

        text = msg.get("text", "").strip()
        if not text:
            return

        self.handle_text_message(chat_id, text)

    def run_polling(self) -> None:
        """Run long-polling loop for Telegram updates.

        Does not call `enrol()` itself — the caller does that once,
        unconditionally, before dispatching to whichever mode runs (see
        `main()`). Enrolling here too would just be a second, redundant call
        with its own 60s retry budget stacked on top of the caller's.

        ⚠ Each update is dispatched to its own thread rather than handled
        inline. `handle_user_prompt` blocks — unboundedly, by design — until
        target_agent replies. Handled inline, that means ONE unanswered
        prompt stops this loop from ever calling `get_updates()` again,
        freezing the bot for every chat, not just the stuck one: measured
        live — a user's "hi" outlived architect's reply-via-office-send, and
        every message the user sent afterward went unread by Telegram's
        getUpdates until the first exchange finally resolved and unblocked
        the loop. They looked lost; they were just never fetched.
        """
        if not self.telegram:
            logger.error("No Telegram token provided; long-polling loop disabled.")
            return

        if self.allowed_chat_id is None:
            logger.warning(
                "No --chat-id/TELEGRAM_CHAT_ID configured: every inbound message and "
                "button tap will be silently ignored (see _chat_allowed). This is not "
                "a hang — set one to let the bot respond to anyone."
            )

        logger.info(f"Telegram bot starting long-polling loop for {self.target_agent}...")
        offset = None

        while True:
            try:
                updates = self.telegram.get_updates(offset=offset, timeout=20)
                for update in updates:
                    offset = update["update_id"] + 1
                    threading.Thread(target=self._dispatch_update, args=(update,), daemon=True).start()
            except Exception as exc:
                logger.error(f"Error in long-polling loop: {exc}")
                time.sleep(3.0)


class DryRunTelegramClient:
    """Dry-run Telegram client that prints formatted output to stdout.
    Allows running and reviewing Telegram bot workflows against real h-flock
    data without requiring a Telegram bot token from BotFather.
    """

    def __init__(self):
        self.next_msg_id = 1

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict:
        msg_id = self.next_msg_id
        self.next_msg_id += 1
        extra = f"\n[keyboard: {reply_markup}]" if reply_markup else ""
        pm = f" [parse_mode={parse_mode}]" if parse_mode else ""
        print(f"[DRY-RUN Telegram] sendMessage (chat={chat_id}, msg_id={msg_id}){pm}:\n{text}{extra}\n")
        return {"ok": True, "result": {"message_id": msg_id, "chat": {"id": chat_id}, "text": text}}

    def send_voice(
        self,
        chat_id: int | str,
        voice: str | bytes | pathlib.Path,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        msg_id = self.next_msg_id
        self.next_msg_id += 1
        voice_desc = f"{len(voice)} bytes" if isinstance(voice, bytes) else str(voice)
        cap_str = f" caption={caption!r}" if caption else ""
        extra = f"\n[keyboard: {reply_markup}]" if reply_markup else ""
        print(f"[DRY-RUN Telegram] sendVoice (chat={chat_id}, msg_id={msg_id}, voice={voice_desc}){cap_str}:{extra}\n")
        return {
            "ok": True,
            "result": {
                "message_id": msg_id,
                "chat": {"id": chat_id},
                "voice": {"file_id": "dry_run_voice"},
                "caption": caption,
            },
        }

    def send_document(
        self,
        chat_id: int | str,
        filename: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
        caption: str | None = None,
    ) -> dict:
        msg_id = self.next_msg_id
        self.next_msg_id += 1
        cap_str = f" caption={caption!r}" if caption else ""
        print(f"[DRY-RUN Telegram] sendDocument (chat={chat_id}, msg_id={msg_id}, filename={filename}, {len(data)} bytes, mime_type={mime_type}){cap_str}\n")
        return {
            "ok": True,
            "result": {
                "message_id": msg_id,
                "chat": {"id": chat_id},
                "document": {"file_id": "dry_run_document", "file_name": filename},
                "caption": caption,
            },
        }

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> dict:
        extra = f"\n[keyboard: {reply_markup}]" if reply_markup else ""
        pm = f" [parse_mode={parse_mode}]" if parse_mode else ""
        print(f"[DRY-RUN Telegram] editMessageText (chat={chat_id}, msg_id={message_id}){pm}:\n{text}{extra}\n")
        return {"ok": True, "result": {"message_id": message_id, "chat": {"id": chat_id}, "text": text}}

    def send_chat_action(self, chat_id: int | str, action: str = "typing") -> dict:
        print(f"[DRY-RUN Telegram] sendChatAction (chat={chat_id}, action={action})")
        return {"ok": True}

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        print(f"[DRY-RUN Telegram] answerCallbackQuery ({callback_query_id}){f': {text}' if text else ''}")
        return {"ok": True}

    def set_my_commands(self, commands: list[dict]) -> dict:
        print(f"[DRY-RUN Telegram] setMyCommands: {commands}")
        return {"ok": True}

    def get_updates(self, offset: int | None = None, timeout: int = 20) -> list[dict]:
        return []


def _door_ssl_context(api_url: str, ca_cert: str, insecure: bool) -> "ssl.SSLContext | None":
    """The context for talking to the h-flock door, or None for plain HTTP.

    ⚠ `--insecure` is for a door with a self-signed certificate, which is what
    `setup.sh` generates. It disables verification entirely, so it says nothing
    about who answered — use `--ca-cert` wherever the certificate has an issuer
    worth checking.
    """
    if not api_url.lower().startswith("https://"):
        if ca_cert or insecure:
            logger.warning("--ca-cert/--insecure ignored: %s is not https", api_url)
        return None
    if insecure:
        logger.warning("TLS verification disabled for %s — traffic is encrypted, "
                       "but the door is not authenticated", api_url)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=ca_cert or None)


def _sibling_path(path: str, suffix: str) -> str:
    """`cursor.json` -> `cursor.alerts.json`: a default alerts-cursor path
    that lives beside --cursor-file without colliding with it."""
    p = pathlib.Path(path)
    return str(p.with_name(f"{p.stem}.{suffix}{p.suffix}"))


def main() -> None:
    parser = argparse.ArgumentParser(description="h-flock Telegram bot client")
    parser.add_argument("--api-url", default=os.getenv("FLOCK_API_URL", "http://localhost:8080"), help="h-flock API base URL")
    parser.add_argument("--ca-cert", default=os.getenv("FLOCK_CA_CERT", ""),
                        help="verify the door's TLS certificate against this CA bundle")
    parser.add_argument("--insecure", action="store_true", default=os.getenv("FLOCK_INSECURE") == "1",
                        help="skip TLS verification (self-signed door certificate)")
    parser.add_argument("--api-token", default=os.getenv("FLOCK_API_TOKEN", os.getenv("API_TOKEN", "")), help="h-flock API Bearer token")
    parser.add_argument("--bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""), help="Telegram Bot API token")
    parser.add_argument("--cursor-file", default=os.getenv("CURSOR_FILE", DEFAULT_CURSOR_FILE), help="File path to store message cursor")
    parser.add_argument("--agent", default="architect", help="Target agent name")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (prints Telegram operations to stdout)")
    parser.add_argument("--prompt", type=str, default="", help="Prompt text to send in dry-run mode")
    parser.add_argument("--status", action="store_true", help="Check status in dry-run mode")
    parser.add_argument("--menu", action="store_true", help="Show the inline menu in dry-run mode")
    # A bot cannot start a conversation: Telegram only lets it reply to a chat
    # it has already heard from. --chat-id supplies one directly so the bot can
    # drive a known chat without waiting for an inbound message first.
    parser.add_argument("--chat-id", type=str, default=os.getenv("TELEGRAM_CHAT_ID", ""),
                        help="Drive this chat directly instead of polling for one")
    parser.add_argument("--alerts-cursor-file", default=os.getenv("ALERTS_CURSOR_FILE", ""),
                        help="File path to store the alerts-stream cursor (default: derived from --cursor-file)")
    parser.add_argument("--no-alert-push", action="store_true", default=os.getenv("NO_ALERT_PUSH") == "1",
                        help="Disable proactively pushing new watchdog alerts to --chat-id")
    parser.add_argument("--no-activity-push", action="store_true", default=os.getenv("NO_ACTIVITY_PUSH") == "1",
                        help="Disable live-updating activity message while an agent works")
    parser.add_argument("--voice", action="store_true", default=os.getenv("TELEGRAM_VOICE") == "1",
                        help="Enable spoken voice replies feature for this tenant")
    parser.add_argument("--tts-voice", default=os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE),
                        help=f"Default edge-tts voice for spoken replies (default: {DEFAULT_TTS_VOICE})")
    parser.add_argument("--session-url", default=os.getenv("FLOCK_SESSION_URL", ""),
                        help="h-flock Session WebSocket URL (default: derived from --api-url, port 8081)")
    parser.add_argument("--pane-watch-chrome-default", type=int,
                        default=int(os.getenv("PANE_WATCH_CHROME_DEFAULT", "4")),
                        help="/watch: bottom pane rows to crop as UI chrome (input box, hints) (default: 4)")
    parser.add_argument("--pane-watch-chrome-overrides", default=os.getenv("PANE_WATCH_CHROME_OVERRIDES", ""),
                        help="/watch: per-agent chrome-row exceptions, \"agent=n,agent2=n\" — "
                             "the bot cannot see which CLI an agent runs (API.md has no such field), "
                             "and Claude/agy and Codex do not agree on chrome height (see README §2c)")
    parser.add_argument("--pane-watch-tail-lines", type=int,
                        default=int(os.getenv("PANE_WATCH_TAIL_LINES", "12")),
                        help="/watch: how many rows back from the bottom of the pane to look (default: 12)")
    parser.add_argument("--pane-watch-refresh-seconds", type=float,
                        default=float(os.getenv("PANE_WATCH_REFRESH_SECONDS", "2.0")),
                        help="/watch: seconds between pane refreshes (default: 2.0)")
    parser.add_argument("--pane-watch-max-duration-seconds", type=float,
                        default=float(os.getenv("PANE_WATCH_MAX_DURATION_SECONDS", "600")),
                        help="/watch: auto-stop a forgotten watch after this many seconds (default: 600)")
    parser.add_argument("--mini-app-url", default=os.getenv("MINI_APP_URL", ""),
                        help="Public HTTPS URL for clients/web/mini.html — adds a 📊 Dashboard "
                             "web_app button to the sticky menu when set; omitted entirely otherwise")
    parser.add_argument("--run-allowed-commands",
                        default=os.getenv("RUN_ALLOWED_COMMANDS", ",".join(DEFAULT_RUN_ALLOWED_COMMANDS)),
                        help="/run: comma-separated exact-match allowlist of native CLI slash commands "
                             f"(default: {','.join(DEFAULT_RUN_ALLOWED_COMMANDS)}) — global, not per-CLI, "
                             "since the api exposes no field for which CLI an agent runs")

    args = parser.parse_args()

    if not args.api_token:
        logger.error("Error: API token required (--api-token or FLOCK_API_TOKEN env var)")
        sys.exit(1)

    ssl_context = _door_ssl_context(args.api_url, args.ca_cert, args.insecure)
    flock = FlockClient(base_url=args.api_url, token=args.api_token, app_name="telegram",
                        ssl_context=ssl_context)
    cursor_store = CursorStore(filepath=args.cursor_file)

    is_dry_run = args.dry_run or not bool(args.bot_token)
    if is_dry_run:
        logger.info("Running in DRY-RUN mode (printing Telegram operations to stdout)...")
        telegram = DryRunTelegramClient()
    else:
        telegram = TelegramClient(bot_token=args.bot_token)

    bot = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=cursor_store,
        target_agent=args.agent,
        allowed_chat_id=args.chat_id or None,
        default_tts_voice=args.tts_voice or None,
        voice_feature_enabled=args.voice,
        no_activity_push=args.no_activity_push,
        session_url=args.session_url or None,
        pane_watch_chrome_default=args.pane_watch_chrome_default,
        pane_watch_chrome_overrides=_parse_int_overrides(args.pane_watch_chrome_overrides),
        pane_watch_tail_span=args.pane_watch_tail_lines,
        pane_watch_refresh_s=args.pane_watch_refresh_seconds,
        pane_watch_max_duration_s=args.pane_watch_max_duration_seconds,
        mini_app_url=args.mini_app_url or None,
        run_allowed_commands=_parse_command_allowlist(args.run_allowed_commands),
    )

    # ⚠ Called once here, unconditionally, before any mode below runs — not
    # per-branch. container/entrypoint.sh forks this process and the api door
    # at essentially the same instant with no readiness wait, so enrolment can
    # lose that race; TelegramBot.enrol() retries with backoff to cover it
    # (see its docstring — this is what was silently broken in production).
    bot.enrol()

    if is_dry_run:
        if args.menu:
            bot.handle_menu_command("dry_run_chat")
        elif args.status:
            bot.handle_status_command("dry_run_chat")
        elif args.prompt:
            bot.handle_user_prompt("dry_run_chat", args.prompt)
        else:
            logger.info("Performing dry-run status check...")
            bot.handle_status_command("dry_run_chat")
    elif args.chat_id and args.prompt:
        bot.handle_user_prompt(args.chat_id, args.prompt)
    elif args.chat_id and args.status:
        bot.handle_status_command(args.chat_id)
    else:
        if args.chat_id:
            # cursor_store (--cursor-file) is entirely ReplyPusher's now — the
            # mailbox cursor it used to track for handle_user_prompt's old
            # wait loop moved here wholesale when that loop was removed.
            reply_pusher = ReplyPusher(
                flock,
                telegram,
                args.chat_id,
                cursor_store,
                tts_voice=args.tts_voice or None,
                voice_enabled_fn=bot.is_voice_enabled,
                activity_finalizer_fn=bot.finalize_activity,
            )
            threading.Thread(target=reply_pusher.run, daemon=True, name="reply-pusher").start()
            if not args.no_alert_push:
                alerts_cursor_file = args.alerts_cursor_file or _sibling_path(args.cursor_file, "alerts")
                pusher = AlertPusher(flock, telegram, args.chat_id, CursorStore(filepath=alerts_cursor_file))
                threading.Thread(target=pusher.run, daemon=True, name="alert-pusher").start()
        else:
            logger.info("TELEGRAM_CHAT_ID not set; live reply/alert push disabled (the menu still works on demand).")
        bot.run_polling()


if __name__ == "__main__":
    main()
