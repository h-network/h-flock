"""Telegram bot client for h-flock.

Talks to an h-flock tenant REST API over HTTP, allowing users to interact with
the 'architect' agent via Telegram.
"""

import argparse
import asyncio
import json
import logging
import os
import pathlib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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

    def send_message(self, recipient: str, text: str) -> tuple[int, dict]:
        """Send a text message envelope to an agent."""
        return self.request(
            "POST",
            f"/agents/{recipient}/envelopes",
            {"text": text, "as": self.app_name},
        )

    def get_presence(self, agent: str) -> tuple[int, dict]:
        """Get queue depths and presence state for an agent."""
        return self.request("GET", f"/agents/{agent}")

    def get_board(self, agent: str) -> tuple[int, dict]:
        """Get task board for an agent."""
        return self.request("GET", f"/agents/{agent}/board")

    def get_messages(self, after: str | None = None, limit: int = 100) -> tuple[int, dict]:
        """Catch-up poll mailbox messages for this client."""
        path = f"/agents/{self.app_name}/messages?limit={limit}"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        return self.request("GET", path)

    def get_activity(self, agent: str, after: str | None = None, limit: int = 100) -> tuple[int, dict]:
        """Catch-up poll activity feed events for an agent."""
        path = f"/agents/{agent}/activity?limit={limit}"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        return self.request("GET", path)


class CursorStore:
    """Persists cursor to disk so bot restarts do not replay mailbox."""

    def __init__(self, filepath: str = "cursor.json"):
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
            self.filepath.write_text(json.dumps({"cursor": cursor, "updated_at": time.time()}), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to save cursor to {self.filepath}: {exc}")


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

    def send_message(self, chat_id: int | str, text: str, reply_to_message_id: int | None = None) -> dict:
        data = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        return self.request("sendMessage", data)

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> dict:
        return self.request("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    def send_chat_action(self, chat_id: int | str, action: str = "typing") -> dict:
        return self.request("sendChatAction", {"chat_id": chat_id, "action": action})

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


class TelegramBot:
    """Coalesces activity tool calls into a single Telegram progress message."""

    def __init__(
        self,
        flock_client: FlockClient,
        telegram_client: TelegramClient | None,
        cursor_store: CursorStore,
        target_agent: str = "architect",
    ):
        self.flock = flock_client
        self.telegram = telegram_client
        self.cursor_store = cursor_store
        self.target_agent = target_agent
        self.cursor = cursor_store.load()
        self.last_edit_time = 0.0
        self.min_edit_interval = 1.5

    def enrol(self) -> None:
        code, body = self.flock.enrol()
        logger.info(f"Enrolled application '{self.flock.app_name}': status={code}, body={body}")

        # ⚠ With no stored cursor, start at the END of the mailbox, not the
        # beginning. Messages that arrived before this process started are not
        # answers to anything it asked — replaying them makes every prompt get
        # the previous exchange's reply, which is indistinguishable from lag.
        if self.cursor is None:
            code, data = self.flock.get_messages(after=None)
            if code == 200 and data.get("next_cursor"):
                self.cursor = data["next_cursor"]
                self.cursor_store.save(self.cursor)
                logger.info(f"No stored cursor; starting from newest ({self.cursor})")

    def render_progress_message(self, tools_list: list[str], status: str = "working",
                                started: float | None = None) -> str:
        """Collapse consecutive repeats and count them.

        ⚠ The activity feed carries tool NAMES only — never arguments, paths or
        commands — so ten shell calls are ten identical events. Listing them
        numbered produced "1. Bash 2. Bash … 10. Bash", which tells a reader
        nothing except that something is happening.

        Collapsing runs keeps the one fact the feed actually has (which tools,
        how many, in what order) and drops the noise.
        """
        elapsed = ""
        if started is not None:
            secs = int(time.time() - started)
            elapsed = f" · {secs}s" if secs < 60 else f" · {secs // 60}m{secs % 60:02d}s"
        lines = [f"⏳ {self.target_agent} is {status}{elapsed}"]

        runs: list[list] = []
        for tool in tools_list:
            if runs and runs[-1][0] == tool:
                runs[-1][1] += 1
            else:
                runs.append([tool, 1])

        for tool, n in runs[-8:]:
            lines.append(f"   ⚙ {tool}" + (f" ×{n}" if n > 1 else ""))
        if len(runs) > 8:
            lines.insert(1, f"   … {len(tools_list) - sum(n for _, n in runs[-8:])} earlier calls")
        return "\n".join(lines)

    def handle_status_command(self, chat_id: int | str) -> str:
        code, presence_data = self.flock.get_presence(self.target_agent)
        code_b, board_data = self.flock.get_board(self.target_agent)

        if code != 200:
            text = f"❌ Unable to fetch status for {self.target_agent}: {presence_data.get('detail', 'error')}"
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
                f"🤖 Agent Status: {self.target_agent}\n"
                f"State: {state} (since {since})\n"
                f"Doing: {doing_str}\n"
                f"Ingress depth: {presence_data.get('depths', {}).get('ingress', 0)}"
            )

        if self.telegram:
            self.telegram.send_message(chat_id, text)
        return text

    def handle_user_prompt(self, chat_id: int | str, text: str) -> str:
        # Check presence first — if blocked, report plainly without endless typing
        code, presence_data = self.flock.get_presence(self.target_agent)
        state = presence_data.get("presence", {}).get("state") if code == 200 else "unknown"

        if state == "blocked":
            reply_text = f"{self.target_agent} is not accepting messages right now"
            if self.telegram:
                self.telegram.send_message(chat_id, reply_text)
            return reply_text

        # Post envelope to architect
        code, resp = self.flock.send_message(self.target_agent, text)
        if code != 202:
            reply_text = f"Failed to send message to {self.target_agent}: {resp.get('detail', 'error')}"
            if self.telegram:
                self.telegram.send_message(chat_id, reply_text)
            return reply_text

        # Send initial progress message to Telegram chat
        progress_text = f"⏳ {self.target_agent} is working"
        msg_id = None
        if self.telegram:
            res = self.telegram.send_message(chat_id, progress_text)
            if res.get("ok"):
                msg_id = res.get("result", {}).get("message_id")

        tools_used: list[str] = []
        last_activity_cursor = None
        last_typing_time = 0.0
        started_at = time.time()

        completed = False
        reply_message_text = None

        while not completed:
            now = time.time()

            # Refresh Telegram typing indicator every ~4 seconds while working
            if self.telegram and (now - last_typing_time >= 4.0):
                self.telegram.send_chat_action(chat_id, "typing")
                last_typing_time = now

            # Poll activity feed
            act_code, act_data = self.flock.get_activity(self.target_agent, after=last_activity_cursor)
            if act_code == 200:
                events = act_data.get("activity", [])
                new_tools = False
                for evt in events:
                    last_activity_cursor = evt.get("cursor", last_activity_cursor)
                    if evt.get("kind") == "tool" and evt.get("tool"):
                        tools_used.append(evt["tool"])
                        new_tools = True

                # Coalesce Telegram edits (at most once per ~1.5s)
                if new_tools and self.telegram and msg_id and (now - self.last_edit_time >= self.min_edit_interval):
                    updated_text = self.render_progress_message(tools_used, started=started_at)
                    self.telegram.edit_message_text(chat_id, msg_id, updated_text)
                    self.last_edit_time = now

            # Poll mailbox for reply from target_agent
            msg_code, msg_data = self.flock.get_messages(after=self.cursor)
            if msg_code == 200:
                msgs = msg_data.get("messages", [])
                # ⚠ Drain the whole batch. Breaking on the first reply left the
                # rest queued, so one extra message — an agent sending twice, or
                # a reply arriving between prompts — put the bot permanently one
                # behind: every prompt then answered with the PREVIOUS reply, and
                # it never caught up because each prompt consumed exactly one.
                replies = []
                for m in msgs:
                    self.cursor = m.get("cursor", self.cursor)
                    if m.get("l2", {}).get("source") == self.target_agent:
                        replies.append(m.get("payload", {}).get("text", str(m.get("payload"))))
                if msgs:
                    self.cursor_store.save(self.cursor)
                if replies:
                    reply_message_text = "\n\n".join(replies)
                    completed = True

            if not completed:
                # Re-check presence to catch if agent becomes blocked
                p_code, p_data = self.flock.get_presence(self.target_agent)
                if p_code == 200:
                    curr_state = p_data.get("presence", {}).get("state")
                    if curr_state == "blocked":
                        blocked_msg = f"{self.target_agent} is not accepting messages right now"
                        if self.telegram and msg_id:
                            self.telegram.edit_message_text(chat_id, msg_id, f"⛔ {blocked_msg}")
                        completed = True
                        reply_message_text = blocked_msg
                        break

                time.sleep(1.0)

        # Post answer as its own separate message
        if reply_message_text and self.telegram and reply_message_text != f"{self.target_agent} is not accepting messages right now":
            self.telegram.send_message(chat_id, f"{self.target_agent}: {reply_message_text}")

        return reply_message_text or ""

    def run_polling(self) -> None:
        """Run long-polling loop for Telegram updates."""
        if not self.telegram:
            logger.error("No Telegram token provided; long-polling loop disabled.")
            return

        self.enrol()
        logger.info(f"Telegram bot starting long-polling loop for {self.target_agent}...")
        offset = None

        while True:
            try:
                updates = self.telegram.get_updates(offset=offset, timeout=20)
                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if not msg:
                        continue

                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "").strip()

                    if not text:
                        continue

                    if text == "/status":
                        self.handle_status_command(chat_id)
                    else:
                        self.handle_user_prompt(chat_id, text)
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

    def send_message(self, chat_id: int | str, text: str, reply_to_message_id: int | None = None) -> dict:
        msg_id = self.next_msg_id
        self.next_msg_id += 1
        print(f"[DRY-RUN Telegram] sendMessage (chat={chat_id}, msg_id={msg_id}):\n{text}\n")
        return {"ok": True, "result": {"message_id": msg_id, "chat": {"id": chat_id}, "text": text}}

    def edit_message_text(self, chat_id: int | str, message_id: int, text: str) -> dict:
        print(f"[DRY-RUN Telegram] editMessageText (chat={chat_id}, msg_id={message_id}):\n{text}\n")
        return {"ok": True, "result": {"message_id": message_id, "chat": {"id": chat_id}, "text": text}}

    def send_chat_action(self, chat_id: int | str, action: str = "typing") -> dict:
        print(f"[DRY-RUN Telegram] sendChatAction (chat={chat_id}, action={action})")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="h-flock Telegram bot client")
    parser.add_argument("--api-url", default=os.getenv("FLOCK_API_URL", "http://localhost:8080"), help="h-flock API base URL")
    parser.add_argument("--ca-cert", default=os.getenv("FLOCK_CA_CERT", ""),
                        help="verify the door's TLS certificate against this CA bundle")
    parser.add_argument("--insecure", action="store_true", default=os.getenv("FLOCK_INSECURE") == "1",
                        help="skip TLS verification (self-signed door certificate)")
    parser.add_argument("--api-token", default=os.getenv("FLOCK_API_TOKEN", os.getenv("API_TOKEN", "")), help="h-flock API Bearer token")
    parser.add_argument("--bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""), help="Telegram Bot API token")
    parser.add_argument("--cursor-file", default=os.getenv("CURSOR_FILE", "cursor.json"), help="File path to store message cursor")
    parser.add_argument("--agent", default="architect", help="Target agent name")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (prints Telegram operations to stdout)")
    parser.add_argument("--prompt", type=str, default="", help="Prompt text to send in dry-run mode")
    parser.add_argument("--status", action="store_true", help="Check status in dry-run mode")
    # A bot cannot start a conversation: Telegram only lets it reply to a chat
    # it has already heard from. --chat-id supplies one directly so the bot can
    # drive a known chat without waiting for an inbound message first.
    parser.add_argument("--chat-id", type=str, default=os.getenv("TELEGRAM_CHAT_ID", ""),
                        help="Drive this chat directly instead of polling for one")

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

    bot = TelegramBot(flock_client=flock, telegram_client=telegram, cursor_store=cursor_store, target_agent=args.agent)

    if is_dry_run:
        bot.enrol()
        if args.status:
            bot.handle_status_command("dry_run_chat")
        elif args.prompt:
            bot.handle_user_prompt("dry_run_chat", args.prompt)
        else:
            logger.info("Performing dry-run status check...")
            bot.handle_status_command("dry_run_chat")
    elif args.chat_id and args.prompt:
        bot.enrol()
        bot.handle_user_prompt(args.chat_id, args.prompt)
    elif args.chat_id and args.status:
        bot.enrol()
        bot.handle_status_command(args.chat_id)
    else:
        bot.run_polling()


if __name__ == "__main__":
    main()
