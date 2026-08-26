"""Unit tests for the Telegram bot client (clients/telegram/bot.py)."""

import inspect
import json
import ssl
import tempfile
import threading
from pathlib import Path

from clients.telegram import bot
from clients.telegram.bot import (
    AlertPusher, CursorStore, FlockClient, ReplyPusher, TelegramBot,
    render_alert, render_reply, _parse_sse_events,
)


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
        self.hired = []
        self.retired = []
        self.sent_envelopes = []
        self.alerts = []
        self.alerts_next_cursor = None

    def enrol(self):
        return 202, {"stream_id": "s1", "correlation_id": "c1"}

    def send_message(self, destination, text):
        self.sent_envelopes.append({"destination": destination, "text": text})
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

    def add_ticket(self, agent, title, description="", priority=""):
        self.added_tickets.append({"agent": agent, "title": title, "description": description, "priority": priority})
        return 202, {"stream_id": "s3", "correlation_id": "c3"}

    def control_agent(self, kind, agent):
        self.control_calls.append({"kind": kind, "agent": agent})
        return 202, {"stream_id": "s4", "correlation_id": "c4"}

    def hire_agent(self, agent, cli="claude", profile=None, provider=None):
        self.hired.append({"agent": agent, "cli": cli, "profile": profile, "provider": provider})
        return 202, {"stream_id": "s5", "correlation_id": "c5"}

    def retire_agent(self, agent):
        self.retired.append(agent)
        return 202, {"stream_id": "s6", "correlation_id": "c6"}

    def get_messages(self, after=None, limit=100):
        res = []
        for msg in self.messages_queue:
            if after is None or msg["cursor"] > after:
                res.append(msg)
        return 200, {"agent": self.app_name, "messages": res, "next_cursor": res[-1]["cursor"] if res else after}

    def get_alerts(self, after=None, limit=100):
        cursor = self.alerts_next_cursor
        if self.alerts and cursor is None:
            cursor = self.alerts[-1].get("cursor")
        return 200, {"alerts": list(self.alerts[:limit]), "next_cursor": cursor}

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
        self.commands_set = []

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

    def set_my_commands(self, commands):
        self.commands_set.append(commands)
        return {"ok": True}


def test_enrol_retries_until_success_and_seeds_cursor(monkeypatch):
    """Reproduces the live acceptance-VM race: the api door isn't listening
    yet when this client starts, enrol() fails once (or twice), and must
    retry rather than give up permanently."""
    slept = []
    monkeypatch.setattr(bot.time, "sleep", lambda s: slept.append(s))

    class FlakyFlockClient(DummyFlockClient):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def enrol(self):
            self.attempts += 1
            if self.attempts < 3:
                return 500, {"detail": "<urlopen error [Errno 111] Connection refused>"}
            return 202, {"stream_id": "s1", "correlation_id": "c1"}

    flock = FlakyFlockClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, DummyTelegramClient(), store, target_agent="architect")
        ok = bot_instance.enrol()

    assert ok is True
    assert flock.attempts == 3
    assert len(slept) == 2  # retried after attempt 1 and attempt 2, not after the success


def test_enrol_gives_up_after_timeout_without_raising(monkeypatch):
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)

    class AlwaysDownFlockClient(DummyFlockClient):
        def enrol(self):
            return 500, {"detail": "<urlopen error [Errno 111] Connection refused>"}

    flock = AlwaysDownFlockClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, DummyTelegramClient(), store, target_agent="architect")
        # timeout_s=0 -> the deadline has already passed after the first
        # attempt, so this returns quickly instead of retrying for 60s.
        ok = bot_instance.enrol(timeout_s=0)

    assert ok is False


def test_enrol_registers_bot_commands():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, telegram, store, target_agent="architect")
        bot_instance.enrol()

    assert len(telegram.commands_set) == 1
    commands = {c["command"] for c in telegram.commands_set[0]}
    assert {"menu", "status"} <= commands


def test_run_polling_does_not_enrol_itself():
    """enrol() is the caller's job now (main(), once, before dispatch) — a
    second call from inside run_polling would silently double the retry
    budget and was removed for exactly that reason."""
    class _StopPolling(BaseException):
        """Not an Exception: run_polling's `except Exception` (which retries
        forever on any failure) must not swallow this, or the loop never ends."""

    class CountingFlockClient(DummyFlockClient):
        def __init__(self):
            super().__init__()
            self.enrol_calls = 0

        def enrol(self):
            self.enrol_calls += 1
            return 202, {}

    class OneShotTelegramClient(DummyTelegramClient):
        def get_updates(self, offset=None, timeout=20):
            raise _StopPolling

    flock = CountingFlockClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, OneShotTelegramClient(), store, target_agent="architect")
        try:
            bot_instance.run_polling()
        except _StopPolling:
            pass
    assert flock.enrol_calls == 0


def test_handle_user_prompt_returns_immediately_without_waiting():
    """Live bug this replaced: one chat's unanswered prompt used to block
    forever waiting for a reply, freezing the whole bot for every chat.
    handle_user_prompt must now post and return -- no wait loop at all."""
    flock = DummyFlockClient()
    flock.presence_state = "working"  # would have looped forever under the old design
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(flock, telegram, store, target_agent="architect")

        reply = bot_instance.handle_user_prompt(111, "hi")

        assert reply == "✅ Sent to architect."
        assert telegram.sent_messages[-1]["text"] == "✅ Sent to architect."


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
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot = TelegramBot(flock, telegram, store, target_agent="architect")

        reply = bot.handle_user_prompt(12345, "please check auth")

        assert reply == "✅ Sent to architect."
        assert len(telegram.sent_messages) == 1
        assert telegram.sent_messages[0]["text"] == "✅ Sent to architect."


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


def test_menu_command_sends_sticky_keyboard():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_menu_command(12345)
        assert len(telegram.sent_messages) == 1
        markup = telegram.sent_messages[0]["reply_markup"]
        assert markup["resize_keyboard"] is True
        assert markup["is_persistent"] is True
        flat = [b["text"] for row in markup["keyboard"] for b in row]
        assert flat == [
            "📋 Overview", "🎫 Add ticket",
            "⏯ Lifecycle", "🔔 Alerts",
            "🎯 Message: architect", "➕ Hire",
            "📢 Broadcast",
        ]
        # every static label resolves to a dispatch code; the dynamic target
        # button is matched by prefix instead (see handle_text_message)
        assert set(flat) - {"🎯 Message: architect"} == set(TelegramBot.STICKY_LABELS)


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
        assert "Priority?" in reply
        assert 12345 in bot_instance.pending

        reply = bot_instance.handle_callback_query(12345, "cb-3", "ap:high")
        assert "Ticket added to sme-2" in reply
        assert 12345 not in bot_instance.pending
        assert flock.added_tickets == [
            {"agent": "sme-2", "title": "Fix the flaky test", "description": "Seen twice in CI this week", "priority": "high"}
        ]


def test_addticket_description_dash_skips_it():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "addticket", "agent": "architect", "stage": "title"}
        bot_instance.handle_text_message(12345, "Quick fix")
        bot_instance.handle_text_message(12345, "-")
        bot_instance.handle_callback_query(12345, "cb-1", "ap:normal")
        assert flock.added_tickets == [
            {"agent": "architect", "title": "Quick fix", "description": "", "priority": "normal"}
        ]


def test_addticket_priority_stray_text_reprompts_without_losing_the_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "addticket", "agent": "architect", "stage": "priority",
                                        "title": "Quick fix", "description": ""}
        reply = bot_instance.handle_text_message(12345, "high please")
        assert "Tap a priority button" in reply
        assert 12345 in bot_instance.pending
        assert flock.added_tickets == []


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


def test_lifecycle_picker_includes_retire():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_callback_query(12345, "cb-1", "lc:architect")
        buttons = telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"]
        assert any(b["callback_data"] == "lret:architect" for row in buttons for b in row)


def test_retire_requires_typing_the_exact_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        reply = bot_instance.handle_callback_query(12345, "cb-1", "lret:architect")
        assert "Type 'architect' exactly" in reply
        assert bot_instance.pending[12345] == {"flow": "retire", "agent": "architect"}

        reply = bot_instance.handle_text_message(12345, "architeckt")  # typo
        assert "doesn't match" in reply
        assert 12345 in bot_instance.pending  # still open for retry
        assert flock.retired == []

        reply = bot_instance.handle_text_message(12345, "architect")
        assert "architect retired" in reply
        assert 12345 not in bot_instance.pending
        assert flock.retired == ["architect"]


def test_retire_cancel():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "retire", "agent": "architect"}
        reply = bot_instance.handle_text_message(12345, "/cancel")
        assert reply == "Cancelled."
        assert 12345 not in bot_instance.pending
        assert flock.retired == []


def test_retire_failure_reports_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        class FailingFlockClient(DummyFlockClient):
            def retire_agent(self, agent):
                return 422, {"detail": "unknown agent"}

        flock = FailingFlockClient()
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "retire", "agent": "architect"}
        reply = bot_instance.handle_text_message(12345, "architect")
        assert "Failed to retire architect" in reply
        assert "unknown agent" in reply


# ── broadcast ────────────────────────────────────────────────────────────────

def test_broadcast_full_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        reply = bot_instance.handle_text_message(12345, "📢 Broadcast")
        assert "type the message" in reply
        assert bot_instance.pending[12345] == {"flow": "broadcast"}

        reply = bot_instance.handle_text_message(12345, "standup in 5")
        assert reply == "📢 Broadcast sent."
        assert 12345 not in bot_instance.pending
        assert flock.sent_envelopes == [{"destination": "all", "text": "standup in 5"}]


def test_broadcast_cancel():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "broadcast"}
        reply = bot_instance.handle_text_message(12345, "/cancel")
        assert reply == "Cancelled."
        assert 12345 not in bot_instance.pending
        assert flock.sent_envelopes == []


def test_broadcast_failure_reports_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        class FailingFlockClient(DummyFlockClient):
            def send_message(self, destination, text):
                return 422, {"detail": "policy denied"}

        flock = FailingFlockClient()
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "broadcast"}
        reply = bot_instance.handle_text_message(12345, "hi all")
        assert "Broadcast failed" in reply
        assert "policy denied" in reply


# ── hire ─────────────────────────────────────────────────────────────────────

def test_hire_full_flow_via_sticky_button_and_text():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        reply = bot_instance.handle_text_message(12345, "➕ Hire")
        assert "New agent's name?" in reply
        assert bot_instance.pending[12345] == {"flow": "hire", "stage": "name"}

        reply = bot_instance.handle_text_message(12345, "sme-9")
        assert "Profile for sme-9?" in reply
        assert bot_instance.pending[12345] == {"flow": "hire", "stage": "profile", "name": "sme-9"}

        reply = bot_instance.handle_text_message(12345, "-")
        assert "Provider for sme-9?" in reply
        assert bot_instance.pending[12345] == {"flow": "hire", "stage": "provider", "name": "sme-9", "profile": None}

        reply = bot_instance.handle_text_message(12345, "-")
        assert "Hire accepted for sme-9" in reply
        assert 12345 not in bot_instance.pending
        assert flock.hired == [{"agent": "sme-9", "cli": "claude", "profile": None, "provider": None}]


def test_hire_with_a_profile_and_provider():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "hire", "stage": "name"}

        bot_instance.handle_text_message(12345, "sme-9")
        bot_instance.handle_text_message(12345, "work")
        reply = bot_instance.handle_text_message(12345, "gpu-a")

        assert "Hire accepted for sme-9 (profile work, provider gpu-a)" in reply
        assert flock.hired == [{"agent": "sme-9", "cli": "claude", "profile": "work", "provider": "gpu-a"}]


def test_hire_rejects_invalid_name_without_consuming_the_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "hire", "stage": "name"}

        reply = bot_instance.handle_text_message(12345, "123")  # all-digits, refused
        assert "won't work" in reply
        assert bot_instance.pending[12345] == {"flow": "hire", "stage": "name"}  # still open
        assert flock.hired == []

        reply = bot_instance.handle_text_message(12345, "all")  # reserved
        assert "won't work" in reply
        assert flock.hired == []

        # A valid name after the bad attempts still works, and gets to the profile step.
        reply = bot_instance.handle_text_message(12345, "sme-9")
        assert "Profile for sme-9?" in reply
        bot_instance.handle_text_message(12345, "-")
        bot_instance.handle_text_message(12345, "-")
        assert flock.hired == [{"agent": "sme-9", "cli": "claude", "profile": None, "provider": None}]


def test_hire_cancel_at_any_stage():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        for state in (
            {"flow": "hire", "stage": "name"},
            {"flow": "hire", "stage": "profile", "name": "sme-9"},
            {"flow": "hire", "stage": "provider", "name": "sme-9", "profile": None},
        ):
            bot_instance.pending[12345] = state
            reply = bot_instance.handle_text_message(12345, "/cancel")
            assert reply == "Cancelled."
            assert 12345 not in bot_instance.pending
        assert flock.hired == []


def test_hire_failure_reports_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        class FailingFlockClient(DummyFlockClient):
            def hire_agent(self, agent, cli="claude", profile=None, provider=None):
                return 422, {"detail": "unknown account 'bogus'; available accounts: default, work"}

        flock = FailingFlockClient()
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        bot_instance.pending[12345] = {"flow": "hire", "stage": "provider", "name": "sme-9", "profile": "bogus"}
        reply = bot_instance.handle_text_message(12345, "-")
        assert "Failed to hire sme-9" in reply
        assert "available accounts: default, work" in reply


# ── message agent ────────────────────────────────────────────────────────────

def test_message_agent_picker_and_prompt_routing():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)

        reply = bot_instance.handle_text_message(12345, "🎯 Message: architect")
        assert "pick a different agent" in reply
        buttons = telegram.sent_messages[-1]["reply_markup"]["inline_keyboard"]
        assert any(row[0]["callback_data"] == "ta:sme-2" for row in buttons)

        reply = bot_instance.handle_callback_query(12345, "cb-1", "ta:sme-2")
        assert "Now messaging sme-2" in reply
        assert bot_instance.chat_target_agent[12345] == "sme-2"
        # the re-sent sticky keyboard reflects the new target immediately
        markup = telegram.sent_messages[-1]["reply_markup"]
        flat = [b["text"] for row in markup["keyboard"] for b in row]
        assert "🎯 Message: sme-2" in flat

        bot_instance.handle_text_message(12345, "how's it going?")
        assert telegram.sent_messages[-1]["text"] == "✅ Sent to sme-2."


def test_message_agent_selection_is_per_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_callback_query(111, "cb-1", "ta:sme-2")

        assert bot_instance._target_for(111) == "sme-2"
        assert bot_instance._target_for(222) == "architect"  # untouched chat keeps the default

        bot_instance.handle_text_message(222, "hello")
        assert telegram.sent_messages[-1]["text"] == "✅ Sent to architect."


def test_status_command_respects_per_chat_target():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.boards["sme-2"] = {"todo": [], "doing": [{"title": "Fix the flaky test"}], "hold": [], "done": []}
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        bot_instance.chat_target_agent[12345] = "sme-2"

        text = bot_instance.handle_status_command(12345)
        assert "Agent Status: sme-2" in text
        assert "Fix the flaky test" in text


def test_callback_query_back_to_menu():
    """An inline "◀ Back" button (e.g. from the Add Ticket agent picker)
    still resolves to "menu" and re-shows the sticky keyboard."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        bot_instance.handle_callback_query(12345, "cb-1", "menu")
        markup = telegram.sent_messages[-1]["reply_markup"]
        assert markup == bot_instance._sticky_keyboard(12345)


def test_sticky_labels_cover_the_office_options():
    assert set(TelegramBot.STICKY_LABELS.values()) == {"ov", "at", "lc", "al", "hi", "bc"}


def test_sticky_keyboard_tap_dispatches_like_the_matching_inline_code():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.alerts = [{"kind": "blocked", "agent": "sme-2", "unconsumed_s": 60, "cursor": "1-0"}]
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)

        reply = bot_instance.handle_text_message(12345, "🔔 Alerts")
        assert "blocked" in reply


# ── alerts ───────────────────────────────────────────────────────────────────

def test_render_alert_blocked():
    text = render_alert({"kind": "blocked", "agent": "sme-2", "unconsumed_s": 725})
    assert text == "⊘ blocked — sme-2 — unconsumed 12m"


def test_render_alert_stalled():
    text = render_alert({"kind": "stalled", "agent": "architect", "ticket": "fix auth", "doing_age_s": 900})
    assert text == '⏳ stalled — architect — "fix auth" — doing 15m'


def test_render_alert_credential():
    text = render_alert({"kind": "credential", "account": "default", "cli": "claude", "status": "expiring"})
    assert text == "🔑 credential — default/claude — expiring"


def test_render_alert_unknown_kind_degrades_gracefully():
    text = render_alert({"kind": "future_kind", "v": 1, "ts": "x", "cursor": "1-0", "agent": "sme-2", "note": "n"})
    assert text.startswith("🔔 future_kind — ")
    assert '"agent": "sme-2"' in text
    assert '"note": "n"' in text
    # v/ts/cursor/kind are framing, not alert content — excluded from the dump
    assert '"v"' not in text and '"ts"' not in text and '"cursor"' not in text


def test_handle_alerts_command_lists_recent_and_slices_tail():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.alerts = [
            {"kind": "credential", "account": "default", "cli": "claude", "status": "expiring", "cursor": f"{i}-0"}
            for i in range(15)
        ]
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        text = bot_instance.handle_alerts_command(12345, limit=10)
        assert text.count("credential") == 10
        assert telegram.sent_messages[-1]["text"] == text


def test_handle_alerts_command_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir)
        text = bot_instance.handle_alerts_command(12345)
        assert text == "🔔 No alerts."


def test_callback_query_alerts_routes_to_handler():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.alerts = [{"kind": "blocked", "agent": "sme-2", "unconsumed_s": 60, "cursor": "1-0"}]
        bot_instance, _, telegram = _make_bot(flock=flock, tmpdir=tmpdir)
        reply = bot_instance.handle_callback_query(12345, "cb-1", "al")
        assert "blocked" in reply
        assert telegram.answered_callbacks == [{"callback_query_id": "cb-1", "text": None}]


def test_parse_sse_events_single_frame():
    lines = [
        "id: 100-0\n",
        "event: alert\n",
        'data: {"kind": "blocked", "agent": "sme-2"}\n',
        "\n",
    ]
    events = list(_parse_sse_events(lines))
    assert events == [("alert", "100-0", '{"kind": "blocked", "agent": "sme-2"}')]


def test_parse_sse_events_multiple_frames_and_comment_lines():
    lines = [
        ": keepalive\n",
        "id: 1-0\n",
        "event: alert\n",
        'data: {"kind": "stalled"}\n',
        "\n",
        "id: 2-0\n",
        "event: alert\n",
        'data: {"kind": "credential"}\n',
        "\n",
    ]
    events = list(_parse_sse_events(lines))
    assert [e[1] for e in events] == ["1-0", "2-0"]
    assert [e[2] for e in events] == ['{"kind": "stalled"}', '{"kind": "credential"}']


def test_parse_sse_events_multiline_data_is_joined():
    lines = ["event: alert\n", "data: line1\n", "data: line2\n", "\n"]
    events = list(_parse_sse_events(lines))
    assert events[0][2] == "line1\nline2"


def test_parse_sse_events_accepts_bytes():
    lines = [b"event: alert\n", b'data: {"kind": "blocked"}\n', b"\n"]
    events = list(_parse_sse_events(lines))
    assert events == [("alert", None, '{"kind": "blocked"}')]


def test_alert_pusher_pushes_each_new_alert_and_persists_cursor():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "alerts_cursor.json"))
        pusher = AlertPusher(flock, telegram, chat_id=999, cursor_store=store)

        alerts = [
            {"kind": "blocked", "agent": "sme-2", "unconsumed_s": 60, "cursor": "10-0"},
            {"kind": "credential", "account": "default", "cli": "claude", "status": "expired", "cursor": "11-0"},
        ]

        def fake_stream(after=None):
            assert after is None  # no persisted cursor and no history to seed from
            yield from alerts

        pusher.run(stream_fn=fake_stream)

        assert len(telegram.sent_messages) == 2
        assert "blocked" in telegram.sent_messages[0]["text"]
        assert "credential" in telegram.sent_messages[1]["text"]
        assert store.load() == "11-0"


def test_alert_pusher_seeds_from_tail_on_first_run_not_from_history():
    """A fresh cursor store must not replay the whole retained alert history as
    if every entry were new — it should start from GET /alerts's next_cursor."""
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.alerts = [{"kind": "blocked", "agent": "old-agent", "cursor": "1-0"}] * 50
        flock.alerts_next_cursor = "50-0"
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "alerts_cursor.json"))
        pusher = AlertPusher(flock, telegram, chat_id=999, cursor_store=store)

        seen_after = []

        def fake_stream(after=None):
            seen_after.append(after)
            return iter([])

        pusher.run(stream_fn=fake_stream)
        assert seen_after == ["50-0"]
        assert telegram.sent_messages == []
        assert store.load() == "50-0"


def test_alert_pusher_resumes_from_persisted_cursor_without_reseeding():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.alerts_next_cursor = "999-0"  # would be wrong to use this
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "alerts_cursor.json"))
        store.save("42-0")
        pusher = AlertPusher(flock, telegram, chat_id=999, cursor_store=store)

        seen_after = []

        def fake_stream(after=None):
            seen_after.append(after)
            return iter([])

        pusher.run(stream_fn=fake_stream)
        assert seen_after == ["42-0"]


# ── ReplyPusher (replaces the old inline blocking wait) ───────────────────────

def test_render_reply_uses_source_and_falls_back_to_provided_name():
    msg = {"l2": {"source": "architect"}, "payload": {"text": "done"}}
    assert render_reply(msg, fallback_source="telegram") == "architect: done"

    no_source = {"payload": {"text": "hi"}}
    assert render_reply(no_source, fallback_source="telegram") == "telegram: hi"

    no_text = {"l2": {"source": "architect"}, "payload": {}}
    assert render_reply(no_text, fallback_source="telegram") == "architect sent a message"


def test_reply_pusher_pushes_each_new_message_and_persists_cursor():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        pusher = ReplyPusher(flock, telegram, chat_id=999, cursor_store=store)

        messages = [
            {"l2": {"source": "architect"}, "payload": {"text": "first"}, "cursor": "10-0"},
            {"l2": {"source": "architect"}, "payload": {"text": "second"}, "cursor": "11-0"},
        ]

        def fake_stream(after=None):
            assert after is None
            yield from messages

        pusher.run(stream_fn=fake_stream)

        assert len(telegram.sent_messages) == 2
        assert telegram.sent_messages[0]["text"] == "architect: first"
        assert telegram.sent_messages[1]["text"] == "architect: second"
        assert store.load() == "11-0"


def test_reply_pusher_seeds_from_tail_on_first_run_not_from_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.messages_queue = [
            {"l2": {"source": "architect"}, "payload": {"text": "old"}, "cursor": "1-0"},
        ] * 20
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        pusher = ReplyPusher(flock, telegram, chat_id=999, cursor_store=store)

        seen_after = []

        def fake_stream(after=None):
            seen_after.append(after)
            return iter([])

        pusher.run(stream_fn=fake_stream)
        # DummyFlockClient.get_messages(after=None) with a non-empty queue
        # returns the last item's cursor as next_cursor -- "1-0" here since
        # every seeded message shares that cursor.
        assert seen_after == ["1-0"]
        assert telegram.sent_messages == []
        assert store.load() == "1-0"


def test_reply_pusher_resumes_from_persisted_cursor_without_reseeding():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        flock.messages_queue = [{"l2": {"source": "architect"}, "payload": {"text": "x"}, "cursor": "999-0"}]
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        store.save("42-0")
        pusher = ReplyPusher(flock, telegram, chat_id=999, cursor_store=store)

        seen_after = []

        def fake_stream(after=None):
            seen_after.append(after)
            return iter([])

        pusher.run(stream_fn=fake_stream)
        assert seen_after == ["42-0"]


def test_poll_messages_forever_yields_and_advances_cursor():
    """Real generator (not injected), exercised for a bounded number of
    iterations by having the second poll raise a sentinel to stop the
    otherwise-infinite loop deterministically."""
    class _Stop(Exception):
        pass

    flock = FlockClient(base_url="http://unused", token="t", app_name="telegram")
    calls = {"n": 0}

    def fake_get_messages(after=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return 200, {"messages": [{"cursor": "5-0", "payload": {"text": "a"}}]}
        raise _Stop

    flock.get_messages = fake_get_messages
    gen = flock.poll_messages_forever(after=None, interval=0)

    first = next(gen)
    assert first["cursor"] == "5-0"
    try:
        next(gen)
        assert False, "expected _Stop to propagate"
    except _Stop:
        pass

