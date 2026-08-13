"""Unit tests for the Telegram bot client (clients/telegram/bot.py)."""

import inspect
import json
import ssl
import tempfile
from pathlib import Path

from clients.telegram import bot
from clients.telegram.bot import CursorStore, FlockClient, TelegramBot


class DummyFlockClient:
    def __init__(self, app_name="telegram"):
        self.app_name = app_name
        self.presence_state = "idle"
        self.messages_queue = []
        self.activity_queue = []

    def enrol(self):
        return 202, {"stream_id": "s1", "correlation_id": "c1"}

    def send_message(self, recipient, text):
        return 202, {"stream_id": "s2", "correlation_id": "c2"}

    def get_presence(self, agent):
        return 200, {
            "agent": agent,
            "depths": {"ingress": 0, "egress": 0, "dead": 0},
            "presence": {"state": self.presence_state, "since": "2026-08-09T15:00:00Z"},
        }

    def get_board(self, agent):
        return 200, {
            "agent": agent,
            "todo": [],
            "doing": [{"title": "Review auth change"}],
            "hold": [],
            "done": [],
        }

    def get_messages(self, after=None, limit=100):
        res = []
        for msg in self.messages_queue:
            if after is None or msg["cursor"] > after:
                res.append(msg)
        return 200, {"agent": self.app_name, "messages": res, "next_cursor": res[-1]["cursor"] if res else after}

    def get_activity(self, agent, after=None, limit=100):
        res = []
        for evt in self.activity_queue:
            if after is None or evt["cursor"] > after:
                res.append(evt)
        return 200, {"agent": agent, "activity": res, "next_cursor": res[-1]["cursor"] if res else after}


class DummyTelegramClient:
    def __init__(self):
        self.sent_messages = []
        self.edited_messages = []
        self.chat_actions = []

    def send_message(self, chat_id, text, reply_to_message_id=None):
        msg_id = len(self.sent_messages) + 1
        entry = {"chat_id": chat_id, "text": text, "message_id": msg_id}
        self.sent_messages.append(entry)
        return {"ok": True, "result": entry}

    def edit_message_text(self, chat_id, message_id, text):
        entry = {"chat_id": chat_id, "message_id": message_id, "text": text}
        self.edited_messages.append(entry)
        return {"ok": True, "result": entry}

    def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return {"ok": True}


def test_cursor_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfile = str(Path(tmpdir) / "cursor.json")
        store = CursorStore(cfile)

        assert store.load() is None

        store.save("1000-0")
        assert store.load() == "1000-0"

        store.save("1001-0")
        assert store.load() == "1001-0"


def test_status_command():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot = TelegramBot(flock, telegram, store, target_agent="architect")

        text = bot.handle_status_command(12345)
        assert "State: idle" in text
        assert "Doing: Review auth change" in text
        assert len(telegram.sent_messages) == 1
        assert "State: idle" in telegram.sent_messages[0]["text"]


def test_handle_user_prompt_when_blocked():
    flock = DummyFlockClient()
    flock.presence_state = "blocked"
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot = TelegramBot(flock, telegram, store, target_agent="architect")

        text = bot.handle_user_prompt(12345, "check auth")
        assert text == "architect is not accepting messages right now"
        assert len(telegram.sent_messages) == 1
        assert "not accepting messages" in telegram.sent_messages[0]["text"]


def test_handle_user_prompt_success():
    flock = DummyFlockClient()
    flock.presence_state = "working"
    flock.activity_queue = [
        {"v": 1, "agent": "architect", "ts": "2026-08-09T15:00:00Z", "kind": "tool", "tool": "Read", "cursor": "2000-0"},
        {"v": 1, "agent": "architect", "ts": "2026-08-09T15:00:01Z", "kind": "tool", "tool": "Bash", "cursor": "2001-0"},
    ]
    flock.messages_queue = [
        {
            "v": 2,
            "kind": "Message",
            "stream_id": "s1",
            "ts": "2026-08-09T15:00:02Z",
            "l2": {"source": "architect", "destination": "telegram"},
            "l3": {
                "source": "acme:hq:architect",
                "destination": "acme:hq:telegram",
            },
            "payload": {"text": "Auth check passed. 12 tests green."},
            "cursor": "3000-0",
        }
    ]
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        cpath = str(Path(tmpdir) / "cursor.json")
        store = CursorStore(cpath)
        bot = TelegramBot(flock, telegram, store, target_agent="architect")

        reply = bot.handle_user_prompt(12345, "please check auth")
        assert reply == "Auth check passed. 12 tests green."

        # Cursor updated and saved
        assert store.load() == "3000-0"

        # Check sent messages: initial progress + final answer
        assert len(telegram.sent_messages) == 2
        assert "architect is working" in telegram.sent_messages[0]["text"]
        assert "architect: Auth check passed" in telegram.sent_messages[1]["text"]


def test_door_context_none_for_plain_http():
    assert bot._door_ssl_context("http://localhost:8080", "", False) is None


def test_door_context_insecure_skips_verification():
    ctx = bot._door_ssl_context("https://host:8080", "", True)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_door_context_verifies_by_default():
    ctx = bot._door_ssl_context("https://host:8080", "", False)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_telegram_api_client_takes_no_context():
    """⚠ --insecure is about the h-flock door. api.telegram.org is a public host
    with a real certificate, and must keep being verified."""
    assert "ssl_context" not in inspect.signature(bot.TelegramClient.__init__).parameters
