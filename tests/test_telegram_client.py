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
        # agent -> port_type; defaults cover the common tmux roster used by tests
        self.roster = {"architect": "tmux", "sme-2": "tmux"}
        self.boards = {"architect": {"todo": [], "doing": [{"title": "Review auth change"}], "hold": [], "done": []}}
        self.added_tickets = []
        self.control_calls = []

    def enrol(self):
        return 202, {"stream_id": "s1", "correlation_id": "c1"}

    def send_message(self, destination, text):
        return 202, {"stream_id": "s2", "correlation_id": "c2"}

    def get_presence(self, agent):
        return 200, {
            "agent": agent,
            "port_type": self.roster.get(agent, "tmux"),
            "depths": {"ingress": 0, "egress": 0, "dead": 0},
            "presence": {"state": self.presence_state, "since": "2026-08-09T15:00:00Z"},
        }

    def get_board(self, agent):
        board = self.boards.get(agent, {"todo": [], "doing": [], "hold": [], "done": []})
        return 200, {"agent": agent, **board}

    def get_agents(self):
        return 200, {"agents": list(self.roster.keys())}

    def get_all_boards(self):
        agents = [{"agent": name, **self.boards.get(name, {"todo": [], "doing": [], "hold": [], "done": []})}
                  for name in self.roster]
        return 200, {"agents": agents}

    def add_ticket(self, agent, title, description=""):
        self.added_tickets.append({"agent": agent, "title": title, "description": description})
        return 202, {"stream_id": "s3", "correlation_id": "c3"}

    def control_agent(self, kind, agent):
        self.control_calls.append({"kind": kind, "agent": agent})
        return 202, {"stream_id": "s4", "correlation_id": "c4"}

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
        self.answered_callbacks = []

    def send_message(self, chat_id, text, reply_to_message_id=None, reply_markup=None):
        msg_id = len(self.sent_messages) + 1
        entry = {"chat_id": chat_id, "text": text, "message_id": msg_id, "reply_markup": reply_markup}
        self.sent_messages.append(entry)
        return {"ok": True, "result": entry}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        entry = {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": reply_markup}
        self.edited_messages.append(entry)
        return {"ok": True, "result": entry}

    def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return {"ok": True}

    def answer_callback_query(self, callback_query_id, text=None):
        self.answered_callbacks.append({"callback_query_id": callback_query_id, "text": text})
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


def test_handle_user_prompt_when_refused_by_policy():
    class RefusingFlockClient(DummyFlockClient):
        def send_message(self, destination, text):
            return 422, {"detail": "policy denied 'telegram' -> 'architect': no shared export/import tag"}

    flock = RefusingFlockClient()
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, telegram, store, target_agent="architect")

        reply = bot_instance.handle_user_prompt(12345, "hello architect")
        assert "policy denied" in reply
        assert len(telegram.sent_messages) == 1
        assert "policy denied" in telegram.sent_messages[0]["text"]


# ── inline menu ──────────────────────────────────────────────────────────────

def _make_bot(flock=None, telegram=None, tmpdir=None):
    flock = flock or DummyFlockClient()
    telegram = telegram if telegram is not None else DummyTelegramClient()
    store = CursorStore(str(Path(tmpdir) / "cursor.json"))
    return TelegramBot(flock, telegram, store, target_agent="architect"), flock, telegram


def test_menu_command_sends_inline_keyboard():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_menu_command(12345)
        assert len(telegram.sent_messages) == 1
        markup = telegram.sent_messages[0]["reply_markup"]
        assert markup["inline_keyboard"][0][0]["callback_data"] == "ov"


def test_handle_text_message_menu_and_status_still_work():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_text_message(12345, "/menu")
        assert telegram.sent_messages[-1]["reply_markup"] is not None

        bot_instance.handle_text_message(12345, "/status")
        assert "State: idle" in telegram.sent_messages[-1]["text"]


def test_tmux_agents_excludes_api_clients():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.roster = {"architect": "tmux", "sme-2": "tmux", "telegram": "api", "host": "control"}
        bot_instance, _, _ = _make_bot(flock=flock, tmpdir=tmpdir)
        assert set(bot_instance._tmux_agents()) == {"architect", "sme-2"}


def test_overview_command_renders_state_and_open_ticket():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.presence_state = "working"
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)

        text = bot_instance.handle_overview_command(12345)
        assert "architect" in text and "working" in text and "Review auth change" in text
        assert "sme-2" in text and "no open ticket" in text
        assert telegram.sent_messages[-1]["text"] == text


def test_callback_query_dispatch_answers_and_routes():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_callback_query(12345, "cbid-1", "ov")
        assert telegram.answered_callbacks == [{"callback_query_id": "cbid-1", "text": None}]
        assert "Office overview" in telegram.sent_messages[-1]["text"]


def test_addticket_full_flow_via_callbacks_and_text():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        bot_instance.handle_callback_query(12345, "cb-1", "at")
        buttons = telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"]
        assert any(row[0]["callback_data"] == "at:sme-2" for row in buttons)

        bot_instance.handle_callback_query(12345, "cb-2", "at:sme-2")
        assert "Ticket title for sme-2" in telegram.sent_messages[-1]["text"]

        # Mid-flow: a plain text message is consumed as the title, not sent to architect
        reply = bot_instance.handle_text_message(12345, "Fix the flaky test")
        assert "Description?" in reply
        assert 12345 in bot_instance.pending

        reply = bot_instance.handle_text_message(12345, "Seen twice in CI this week")
        assert "Ticket added to sme-2" in reply
        assert 12345 not in bot_instance.pending
        assert flock.added_tickets == [
            {"agent": "sme-2", "title": "Fix the flaky test", "description": "Seen twice in CI this week"}
        ]


def test_addticket_description_dash_skips_it():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "addticket", "agent": "architect", "stage": "title"}
        bot_instance.handle_text_message(12345, "Quick fix")
        bot_instance.handle_text_message(12345, "-")
        assert flock.added_tickets == [{"agent": "architect", "title": "Quick fix", "description": ""}]


def test_addticket_flow_cancel():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "addticket", "agent": "architect", "stage": "title"}
        reply = bot_instance.handle_text_message(12345, "/cancel")
        assert reply == "Cancelled."
        assert 12345 not in bot_instance.pending
        assert flock.added_tickets == []


def test_pending_flow_takes_priority_over_ordinary_prompt():
    """A message during an open flow must not fall through to handle_user_prompt
    (which would send it to target_agent instead of consuming it as an answer)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "addticket", "agent": "architect", "stage": "title"}
        bot_instance.handle_text_message(12345, "not a prompt for architect")
        # send_message (chat) was only used for the flow prompt, never routed as
        # a Message envelope — DummyFlockClient has no record of prompt sends,
        # so we assert indirectly: the flow advanced instead of completing.
        assert bot_instance.pending[12345]["stage"] == "description"


def test_lifecycle_full_flow_via_callbacks():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        bot_instance.handle_callback_query(12345, "cb-1", "lc")
        buttons = telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"]
        assert any(row[0]["callback_data"] == "lc:architect" for row in buttons)

        bot_instance.handle_callback_query(12345, "cb-2", "lc:architect")
        buttons = telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"]
        assert buttons[0][0]["callback_data"] == "lp:architect"
        assert buttons[0][1]["callback_data"] == "lr:architect"

        reply = bot_instance.handle_callback_query(12345, "cb-3", "lp:architect")
        assert reply == "✅ architect paused."
        assert flock.control_calls == [{"kind": "PauseAgent", "agent": "architect"}]


def test_lifecycle_control_failure_reports_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        class FailingFlockClient(DummyFlockClient):
            def control_agent(self, kind, agent):
                return 422, {"detail": "unknown agent"}

        flock = FailingFlockClient()
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        reply = bot_instance.handle_callback_query(12345, "cb-1", "lr:ghost")
        assert "Failed to resume ghost" in reply
        assert "unknown agent" in reply


def test_callback_query_back_to_menu():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_callback_query(12345, "cb-1", "menu")
        assert telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"] == TelegramBot.MAIN_MENU

