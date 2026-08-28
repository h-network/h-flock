"""Unit tests for the Telegram bot client (clients/telegram/bot.py)."""

import inspect
import json
import ssl
import tempfile
import threading
from pathlib import Path

from clients.telegram import bot
from clients.telegram.bot import (
    ActivityRender, AlertPusher, CursorStore, DryRunTelegramClient, FlockClient, ReplyPusher,
    TelegramBot, TelegramClient, render_alert, render_reply,
    synthesize_speech, _parse_sse_events, _derive_session_url,
)


class DummyFlockClient:
    def __init__(self, app_name="telegram", base_url="http://127.0.0.1:8080", token="dummy-token"):
        self.app_name = app_name
        self.base_url = base_url
        self.token = token
        self.ssl_context = None
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
        batch = res[:limit]
        return 200, {"agent": self.app_name, "messages": batch, "next_cursor": batch[-1]["cursor"] if batch else after}

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
        batch = res[:limit]
        return 200, {"agent": agent, "activity": batch, "next_cursor": batch[-1]["cursor"] if batch else after}

    def stream_activity(self, agent, after=None):
        for evt in self.activity_queue:
            if after is None or evt["cursor"] > after:
                yield evt


class DummyTelegramClient:
    def __init__(self):
        self.sent_messages = []
        self.sent_voices = []
        self.edited_messages = []
        self.chat_actions = []
        self.answered_callbacks = []
        self.commands_set = []

    def send_message(self, chat_id, text, reply_to_message_id=None, reply_markup=None, **kwargs):
        msg_id = len(self.sent_messages) + len(self.sent_voices) + 1
        entry = {"chat_id": chat_id, "text": text, "message_id": msg_id, "reply_markup": reply_markup, **kwargs}
        self.sent_messages.append(entry)
        return {"ok": True, "result": entry}

    def send_voice(self, chat_id, voice, caption=None, reply_to_message_id=None, reply_markup=None, **kwargs):
        msg_id = len(self.sent_messages) + len(self.sent_voices) + 1
        entry = {
            "chat_id": chat_id,
            "voice": voice,
            "caption": caption,
            "message_id": msg_id,
            "reply_markup": reply_markup,
            **kwargs,
        }
        self.sent_voices.append(entry)
        return {"ok": True, "result": entry}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
        entry = {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": reply_markup, **kwargs}
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

def _make_bot(flock=None, telegram=None, tmpdir=None, allowed_chat_id=None):
    flock = flock or DummyFlockClient()
    telegram = telegram if telegram is not None else DummyTelegramClient()
    store = CursorStore(str(Path(tmpdir) / "cursor.json"))
    bot_instance = TelegramBot(flock, telegram, store, target_agent="architect", allowed_chat_id=allowed_chat_id)
    return bot_instance, flock, telegram


# ── chat_id restriction ────────────────────────────────────────────────────────

def test_chat_allowed_requires_a_configured_id():
    """No configured chat_id must refuse everything, not allow everything --
    the bot can now hire/retire/pause/resume/broadcast, not just chat."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, _, _ = _make_bot(tmpdir=tmpdir, allowed_chat_id=None)
        assert bot_instance._chat_allowed(12345) is False
        assert bot_instance._chat_allowed(0) is False


def test_chat_allowed_matches_configured_id_across_str_int():
    """--chat-id arrives as a str from argparse; Telegram's own chat ids are
    ints -- the comparison must not silently fail on that type mismatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, _, _ = _make_bot(tmpdir=tmpdir, allowed_chat_id="12345")
        assert bot_instance._chat_allowed(12345) is True   # int from Telegram
        assert bot_instance._chat_allowed("12345") is True
        assert bot_instance._chat_allowed(99999) is False


def test_dispatch_update_ignores_a_message_from_an_unconfigured_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=None)
        bot_instance._dispatch_update({"message": {"chat": {"id": 999}, "text": "hire sme-9 please"}})
        assert telegram.sent_messages == []
        assert flock.hired == []


def test_dispatch_update_ignores_a_message_from_the_wrong_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=42)
        bot_instance._dispatch_update({"message": {"chat": {"id": 999}, "text": "/menu"}})
        assert telegram.sent_messages == []


def test_dispatch_update_processes_a_message_from_the_allowed_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=42)
        bot_instance._dispatch_update({"message": {"chat": {"id": 42}, "text": "/menu"}})
        assert len(telegram.sent_messages) == 1


def test_dispatch_update_ignores_a_callback_from_the_wrong_chat():
    """Not even answer_callback_query -- an unauthorized tap gets nothing
    back, not even acknowledgement that a bot is listening."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=42)
        bot_instance._dispatch_update({
            "callback_query": {"id": "cb-1", "data": "hi", "message": {"chat": {"id": 999}}},
        })
        assert telegram.sent_messages == []
        assert telegram.answered_callbacks == []


def test_dispatch_update_processes_a_callback_from_the_allowed_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=42)
        bot_instance._dispatch_update({
            "callback_query": {"id": "cb-1", "data": "ov", "message": {"chat": {"id": 42}}},
        })
        assert telegram.answered_callbacks == [{"callback_query_id": "cb-1", "text": None}]
        assert len(telegram.sent_messages) == 1


def test_direct_handler_calls_bypass_the_allowlist():
    """CLI-driven one-shots (--prompt/--status/--menu) and dry-run mode call
    handlers directly, never through _dispatch_update -- they're operator
    invocations from shell access, not untrusted Telegram network input, so
    the allowlist (which guards inbound Telegram updates) does not apply."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bot_instance, flock, telegram = _make_bot(tmpdir=tmpdir, allowed_chat_id=42)
        bot_instance.handle_text_message(999, "/menu")
        assert len(telegram.sent_messages) == 1


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


def test_synthesize_speech_empty_text_raises_value_error():
    try:
        synthesize_speech("   ", "en-GB-RyanNeural")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_synthesize_speech_failure_cleans_up_and_raises(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, text, voice):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"broken")
            raise RuntimeError("network down")

    monkeypatch.setattr(bot.edge_tts, "Communicate", FakeCommunicate)

    out_file = tmp_path / "test.mp3"
    try:
        synthesize_speech("hello", "en-GB-RyanNeural", output_path=out_file)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "network down" in str(exc)
        assert not out_file.exists()


def test_synthesize_speech_success(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, path):
            Path(path).write_bytes(f"audio:{self.voice}:{self.text}".encode("utf-8"))

    monkeypatch.setattr(bot.edge_tts, "Communicate", FakeCommunicate)

    out_file = tmp_path / "voice.mp3"
    res_path = synthesize_speech("hello world", "en-GB-RyanNeural", output_path=out_file)
    assert Path(res_path).exists()
    assert Path(res_path).read_bytes() == b"audio:en-GB-RyanNeural:hello world"

    # Default voice parameter test
    out_file_default = tmp_path / "voice_default.mp3"
    res_path_default = synthesize_speech("default call", output_path=out_file_default)
    assert Path(res_path_default).read_bytes() == b"audio:en-GB-RyanNeural:default call"


def test_telegram_client_send_voice_multipart(monkeypatch):
    client = TelegramClient(bot_token="fake-token")
    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["data"] = req.data
        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"ok": true, "result": {"message_id": 42}}'
        return FakeResp()

    monkeypatch.setattr(bot.urllib.request, "urlopen", fake_urlopen)

    res = client.send_voice(
        chat_id=12345,
        voice=b"MP3_DATA_BYTES",
        caption="Voice caption",
        reply_to_message_id=99,
        reply_markup={"inline_keyboard": []},
    )

    assert res.get("ok") is True
    assert captured["url"] == "https://api.telegram.org/botfake-token/sendVoice"
    content_type = captured["headers"]["Content-type"]
    assert "multipart/form-data; boundary=" in content_type
    body = captured["data"].decode("utf-8", errors="replace")
    assert 'name="chat_id"\r\n\r\n12345' in body
    assert 'name="caption"\r\n\r\nVoice caption' in body
    assert 'name="reply_to_message_id"\r\n\r\n99' in body
    assert 'name="voice"; filename="voice.mp3"' in body
    assert "MP3_DATA_BYTES" in body


def test_dry_run_telegram_client_send_voice(capsys):
    client = DryRunTelegramClient()
    res = client.send_voice(12345, b"RAW_BYTES", caption="dry voice test")
    assert res.get("ok") is True
    assert res["result"]["caption"] == "dry voice test"
    out = capsys.readouterr().out
    assert "[DRY-RUN Telegram] sendVoice" in out
    assert "chat=12345" in out
    assert "caption='dry voice test'" in out


def test_reply_pusher_voice_reply_success(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        pusher = ReplyPusher(
            flock,
            telegram,
            chat_id=999,
            cursor_store=store,
            tts_voice="en-GB-RyanNeural",
            voice_enabled=True,
        )

        saved_files = []

        def fake_synthesize(text, voice="en-GB-RyanNeural", output_path=None):
            assert text == "architect: spoken reply"
            assert voice == "en-GB-RyanNeural"
            p = Path(tmpdir) / "voice_out.mp3"
            p.write_bytes(b"spoken audio")
            saved_files.append(p)
            return str(p)

        monkeypatch.setattr(bot, "synthesize_speech", fake_synthesize)

        messages = [
            {"l2": {"source": "architect"}, "payload": {"text": "spoken reply"}, "cursor": "20-0"},
        ]

        def fake_stream(after=None):
            yield from messages

        pusher.run(stream_fn=fake_stream)

        assert len(telegram.sent_messages) == 1
        assert telegram.sent_messages[0]["chat_id"] == 999
        assert telegram.sent_messages[0]["text"] == "architect: spoken reply"
        assert len(telegram.sent_voices) == 1
        assert telegram.sent_voices[0]["chat_id"] == 999
        assert store.load() == "20-0"
        assert not saved_files[0].exists()


def test_reply_pusher_text_only_when_voice_disabled():
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        pusher = ReplyPusher(
            flock,
            telegram,
            chat_id=999,
            cursor_store=store,
            voice_enabled=False,
        )

        messages = [
            {"l2": {"source": "architect"}, "payload": {"text": "text only reply"}, "cursor": "21-0"},
        ]

        def fake_stream(after=None):
            yield from messages

        pusher.run(stream_fn=fake_stream)

        assert len(telegram.sent_messages) == 1
        assert telegram.sent_messages[0]["chat_id"] == 999
        assert telegram.sent_messages[0]["text"] == "architect: text only reply"
        assert telegram.sent_voices == []
        assert store.load() == "21-0"


def test_reply_pusher_per_message_voice_override(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        flock = DummyFlockClient()
        telegram = DummyTelegramClient()
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        pusher = ReplyPusher(
            flock,
            telegram,
            chat_id=999,
            cursor_store=store,
            tts_voice="default-voice",
            voice_enabled=True,
        )

        synthesized_voices = []

        def fake_synthesize(text, voice="en-GB-RyanNeural", output_path=None):
            synthesized_voices.append(voice)
            p = Path(tmpdir) / "voice.mp3"
            p.write_bytes(b"audio")
            return str(p)

        monkeypatch.setattr(bot, "synthesize_speech", fake_synthesize)

        messages = [
            {"l2": {"source": "architect"}, "payload": {"text": "custom voice", "voice": "custom-override-voice"}, "cursor": "22-0"},
        ]

        def fake_stream(after=None):
            yield from messages

        pusher.run(stream_fn=fake_stream)
        assert synthesized_voices == ["custom-override-voice"]


def test_telegram_bot_voice_feature_flag_disabled_by_default():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=12345,
        voice_feature_enabled=False,
    )

    assert not bot_instance.is_voice_enabled(12345)
    kb = bot_instance._sticky_keyboard(12345)
    labels = [btn["text"] for row in kb["keyboard"] for btn in row]
    assert "🔇 Voice: OFF" not in labels
    assert "🔊 Voice: ON" not in labels

    reply = bot_instance.handle_voice_toggle(12345)
    assert "Voice replies are not enabled for this tenant" in reply
    assert not bot_instance.is_voice_enabled(12345)


def test_telegram_bot_voice_toggle_and_menu_when_feature_enabled():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=12345,
        voice_feature_enabled=True,
    )

    assert bot_instance.default_tts_voice == "en-GB-RyanNeural"
    assert not bot_instance.is_voice_enabled(12345)
    assert bot_instance._voice_label(12345) == "🔇 Voice: OFF"
    kb = bot_instance._sticky_keyboard(12345)
    labels = [btn["text"] for row in kb["keyboard"] for btn in row]
    assert "🔇 Voice: OFF" in labels

    # Toggle ON via handle_voice_toggle
    reply = bot_instance.handle_voice_toggle(12345)
    assert "🔊 Voice replies enabled" in reply
    assert "en-GB-RyanNeural" in reply
    assert bot_instance.is_voice_enabled(12345)
    assert bot_instance._voice_label(12345) == "🔊 Voice: ON"

    # Toggle OFF via text message "/voice"
    reply = bot_instance.handle_text_message(12345, "/voice")
    assert "🔇 Voice replies disabled" in reply
    assert not bot_instance.is_voice_enabled(12345)

    # Toggle ON via button text "🔇 Voice: OFF"
    reply = bot_instance.handle_text_message(12345, "🔇 Voice: OFF")
    assert "🔊 Voice replies enabled" in reply
    assert bot_instance.is_voice_enabled(12345)

    # Toggle OFF via callback query "vt"
    bot_instance.handle_callback_query(12345, "cb_1", "vt")
    assert not bot_instance.is_voice_enabled(12345)


def test_telegram_bot_enrol_registers_voice_command():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(flock_client=flock, telegram_client=telegram, cursor_store=store)
    assert bot_instance.enrol() is True
    assert len(telegram.commands_set) == 1
    cmds = {c["command"]: c["description"] for c in telegram.commands_set[0]}
    assert "menu" in cmds
    assert "status" in cmds
    assert "voice" in cmds


def test_telegram_bot_chat_id_type_normalization_with_reply_pusher(monkeypatch):
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CursorStore(str(Path(tmpdir) / "cursor.json"))
        bot_instance = TelegramBot(
            flock_client=flock,
            telegram_client=telegram,
            cursor_store=store,
            allowed_chat_id="46444780",
            voice_feature_enabled=True,
        )

        # Telegram sends integer chat_id in JSON updates
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 46444780},
                "text": "/voice",
            },
        }
        bot_instance._dispatch_update(update)

        # Both int and str lookups should now return True
        assert bot_instance.is_voice_enabled(46444780) is True
        assert bot_instance.is_voice_enabled("46444780") is True

        # ReplyPusher with string chat_id should see voice enabled
        pusher = ReplyPusher(
            flock=flock,
            telegram=telegram,
            chat_id="46444780",
            cursor_store=store,
            voice_enabled_fn=bot_instance.is_voice_enabled,
        )

        synthesized = []

        def fake_synthesize(text, voice="en-GB-RyanNeural", output_path=None):
            synthesized.append((text, voice))
            p = Path(tmpdir) / "test.mp3"
            p.write_bytes(b"dummy audio")
            return str(p)

        monkeypatch.setattr(bot, "synthesize_speech", fake_synthesize)

        messages = [
            {"l2": {"source": "architect"}, "payload": {"text": "live spoken reply"}, "cursor": "30-0"},
        ]

        def fake_stream(after=None):
            yield from messages

        pusher.run(stream_fn=fake_stream)

        assert len(synthesized) == 1
        assert len(telegram.sent_messages) == 2
        assert telegram.sent_messages[-1]["text"] == "architect: live spoken reply"
        assert len(telegram.sent_voices) == 1
        assert telegram.sent_voices[0]["chat_id"] == "46444780"


def test_telegram_bot_int_str_chat_id_in_flows():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        allowed_chat_id=46444780,
    )

    # Set target agent via int chat_id, query via str chat_id and vice versa
    bot_instance.handle_message_agent_pick(46444780, "specialist")
    assert bot_instance._target_for(46444780) == "specialist"
    assert bot_instance._target_for("46444780") == "specialist"

    # Multi-step pending flow started with int chat_id, continued with str chat_id
    bot_instance.handle_addticket_pick_agent(46444780, "architect")
    reply = bot_instance.handle_pending_text("46444780", "My Ticket Title")
    assert "Description?" in reply
    assert "46444780" in bot_instance.pending


def test_activity_render_formatting_and_lifecycle():
    render = ActivityRender(chat_id="12345", agent="architect")
    assert render.render() == "🛠 <b>Activity</b> (<code>architect</code>)"

    # Add input event
    render.add_event({"kind": "input", "cursor": "1-0"})
    text1 = render.render()
    assert "🛠 <b>Activity</b> (<code>architect</code>)" in text1
    assert "1. ⏳ 💬 <i>input received</i>" in text1

    # Add tool events
    render.add_event({"kind": "tool", "tool": "Read", "cursor": "2-0"})
    text2 = render.render()
    assert "1. ✓ 💬 <i>input received</i>" in text2
    assert "2. ⏳ <code>Read</code>" in text2

    render.add_event({"kind": "tool", "tool": "Bash", "cursor": "3-0"})
    text3 = render.render()
    assert "1. ✓ 💬 <i>input received</i>" in text3
    assert "2. ✓ <code>Read</code>" in text3
    assert "3. ⏳ <code>Bash</code>" in text3

    # Add output event -> stays in-progress until finalize()
    render.add_event({"kind": "output", "cursor": "4-0"})
    assert render.completed is False
    text4 = render.render()
    assert "🛠 <b>Activity</b> (<code>architect</code>)" in text4
    assert "1. ✓ 💬 <i>input received</i>" in text4
    assert "2. ✓ <code>Read</code>" in text4
    assert "3. ✓ <code>Bash</code>" in text4
    assert "4. ✓ ✍️ <i>output produced</i>" in text4

    # Finalize explicitly
    render.finalize()
    assert render.completed is True
    text5 = render.render()
    assert "🛠 <b>Activity</b> (<code>architect</code>) · completed (4 steps)" in text5
    assert "4. ✓ ✍️ <i>output produced</i>" in text5


def test_activity_render_truncation_and_escaping():
    # Escaping special characters in agent and tool names
    render = ActivityRender(chat_id="99", agent="<dangerous>&agent")
    render.add_event({"kind": "tool", "tool": "<script>alert(1)</script>"})
    text = render.render()
    assert "&lt;dangerous&gt;&amp;agent" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text

    # Truncation when more than 20 events are present
    render_many = ActivityRender(chat_id="99", agent="architect")
    for i in range(25):
        render_many.add_event({"kind": "tool", "tool": f"Tool_{i}"})
    text_many = render_many.render()
    assert "<i>… 5 earlier steps omitted …</i>" in text_many
    assert "25. ⏳ <code>Tool_24</code>" in text_many


def test_activity_render_flush_debouncing():
    client = DummyTelegramClient()
    render = ActivityRender(chat_id="555", agent="architect")

    # Initial flush with no events does nothing
    render.flush(client)
    assert len(client.sent_messages) == 0

    # Add event and flush -> send_message called
    render.add_event({"kind": "input"})
    render.flush(client)
    assert len(client.sent_messages) == 1
    assert render.message_id == 1

    # Second flush immediately without force or completion is debounced
    render.add_event({"kind": "tool", "tool": "Bash"})
    render.flush(client, force=False)
    assert len(client.edited_messages) == 0

    # Forced flush or finalized flush edits the message
    render.finalize()
    render.flush(client, force=True)
    assert len(client.edited_messages) == 1
    assert "<code>Bash</code>" in client.edited_messages[0]["text"]

    # Redundant flush with identical text is skipped (even with force=True)
    render.flush(client, force=True)
    assert len(client.edited_messages) == 1


def test_flock_client_stream_activity(monkeypatch):
    flock = FlockClient("http://fake:8080", "fake-token")

    raw_sse = (
        b"id: 100-0\n"
        b"event: activity\n"
        b'data: {"v":1,"agent":"architect","kind":"tool","tool":"Bash","cursor":"100-0"}\n\n'
    )

    class FakeResponse:
        def __enter__(self):
            return iter(raw_sse.splitlines(keepends=True))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(bot.urllib.request, "urlopen", lambda req, timeout=90, context=None: FakeResponse())

    events = []
    # Consume one event and break
    for ev in flock.stream_activity("architect"):
        events.append(ev)
        break

    assert len(events) == 1
    assert events[0]["tool"] == "Bash"
    assert events[0]["cursor"] == "100-0"


def test_telegram_bot_live_activity_with_user_prompt_and_reply_pusher(monkeypatch):
    flock = DummyFlockClient()
    flock.activity_queue = [{"cursor": "50-0", "agent": "architect", "kind": "input"}]
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=12345,
    )

    activity_events = [
        {"agent": "architect", "kind": "input", "cursor": "51-0"},
        {"agent": "architect", "kind": "tool", "tool": "Read", "cursor": "52-0"},
        {"agent": "architect", "kind": "output", "cursor": "53-0"},
    ]

    def fake_stream(agent, after=None):
        yield from activity_events

    monkeypatch.setattr(flock, "stream_activity", fake_stream)

    # User sends prompt
    reply = bot_instance.handle_user_prompt(12345, "build the feature")
    assert reply == "✅ Sent to architect."

    # Give watcher thread a moment to process the generator
    import time
    time.sleep(0.8)

    # Activity message was sent, and then edited
    assert len(telegram.sent_messages) >= 2  # 1 for activity + 1 for "Sent to architect."
    activity_msg = telegram.sent_messages[0]
    assert "🛠 <b>Activity</b> (<code>architect</code>)" in activity_msg["text"]

    # ReplyPusher delivers final reply
    pusher = ReplyPusher(
        flock=flock,
        telegram=telegram,
        chat_id=12345,
        cursor_store=store,
        activity_finalizer_fn=bot_instance.finalize_activity,
    )

    messages = [
        {"l2": {"source": "architect"}, "payload": {"text": "done building"}, "cursor": "60-0"},
    ]

    def fake_reply_stream(after=None):
        yield from messages

    pusher.run(stream_fn=fake_reply_stream)

    # Activity message should be finalized
    assert len(telegram.edited_messages) >= 1
    last_edit = telegram.edited_messages[-1]
    assert "completed" in last_edit["text"]

    # Final reply delivered
    assert telegram.sent_messages[-1]["text"] == "architect: done building"


def test_telegram_bot_multi_output_turn_does_not_early_exit(monkeypatch):
    """Verify that multiple output events interleaved with tools do not cause early exit."""
    flock = DummyFlockClient()
    flock.activity_queue = [{"cursor": "70-0", "agent": "architect", "kind": "input"}]
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=12345,
    )

    # 7-step turn with multiple outputs interleaved between tools
    activity_events = [
        {"agent": "architect", "kind": "input", "cursor": "71-0"},
        {"agent": "architect", "kind": "output", "cursor": "72-0"},
        {"agent": "architect", "kind": "tool", "tool": "Read", "cursor": "73-0"},
        {"agent": "architect", "kind": "output", "cursor": "74-0"},
        {"agent": "architect", "kind": "tool", "tool": "Edit", "cursor": "75-0"},
        {"agent": "architect", "kind": "tool", "tool": "Bash", "cursor": "76-0"},
        {"agent": "architect", "kind": "output", "cursor": "77-0"},
    ]

    event_index = 0
    event_lock = threading.Lock()

    def fake_stream(agent, after=None):
        nonlocal event_index
        while True:
            with event_lock:
                if event_index < len(activity_events):
                    ev = activity_events[event_index]
                    event_index += 1
                    yield ev
                else:
                    break
            import time
            time.sleep(0.05)

    monkeypatch.setattr(flock, "stream_activity", fake_stream)

    reply = bot_instance.handle_user_prompt(12345, "run multi step task")
    assert reply == "✅ Sent to architect."

    import time
    time.sleep(0.8)

    key = "12345:architect"
    render = bot_instance.activity_renders.get(key)
    assert render is not None
    # All 7 events must have been recorded (not stopped at step 2!)
    assert len(render.events) == 7
    assert [e.get("kind") for e in render.events] == [
        "input", "output", "tool", "output", "tool", "tool", "output"
    ]

    # Final reply arrives via ReplyPusher and finalizes the render
    pusher = ReplyPusher(
        flock=flock,
        telegram=telegram,
        chat_id=12345,
        cursor_store=store,
        activity_finalizer_fn=bot_instance.finalize_activity,
    )

    pusher.run(stream_fn=lambda after=None: iter([
        {"l2": {"source": "architect"}, "payload": {"text": "all done"}, "cursor": "80-0"}
    ]))

    assert render.completed is True
    assert "completed (7 steps)" in render.render()
    assert telegram.sent_messages[-1]["text"] == "architect: all done"


def test_telegram_bot_no_activity_push_flag():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=12345,
        no_activity_push=True,
    )

    reply = bot_instance.handle_user_prompt(12345, "build the feature")
    assert reply == "✅ Sent to architect."
    assert len(bot_instance.activity_renders) == 0
    # Only "✅ Sent to architect." message is sent
    assert len(telegram.sent_messages) == 1
    assert telegram.sent_messages[0]["text"] == "✅ Sent to architect."


def test_get_activity_tail_pagination_and_true_tail():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
    )

    # 0 events -> returns None
    assert bot_instance._get_activity_tail("architect") is None

    # 550 events (more than 1, less than 1000)
    flock.activity_queue = [
        {"agent": "architect", "kind": "tool", "tool": "Bash", "cursor": f"{i}-0"}
        for i in range(1, 551)
    ]
    # Must return the TRUE tail (550-0), NOT the first event (1-0)!
    assert bot_instance._get_activity_tail("architect") == "550-0"

    # 2500 events (spanning 3 pages of 1000)
    flock.activity_queue = [
        {"agent": "architect", "kind": "tool", "tool": "Bash", "cursor": f"{i:05d}-0"}
        for i in range(1, 2501)
    ]
    assert bot_instance._get_activity_tail("architect") == "02500-0"


def test_reply_pusher_seed_cursor_pagination():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    pusher = ReplyPusher(
        flock=flock,
        telegram=telegram,
        chat_id=123,
        cursor_store=store,
    )

    # 0 messages -> None
    assert pusher._seed_cursor() is None

    # 1500 messages (spanning 2 pages of 1000)
    flock.messages_queue = [
        {"cursor": f"{i:05d}-0", "payload": {"text": f"msg {i}"}}
        for i in range(1, 1501)
    ]
    assert pusher._seed_cursor() == "01500-0"


def test_derive_session_url():
    assert _derive_session_url("http://localhost:8080") == "ws://localhost:8081/session"
    assert _derive_session_url("https://office.example.com:8080") == "wss://office.example.com:8081/session"
    assert _derive_session_url("http://127.0.0.1:8080", "ws://custom:9999/session") == "ws://custom:9999/session"
    assert _derive_session_url("http://127.0.0.1:8080", "https://custom:9999") == "wss://custom:9999/session"


def test_activity_render_liveness_pulse():
    render = ActivityRender(chat_id="123", agent="architect")
    render.add_event({"kind": "input"})
    assert "still working" not in render.render()

    # Touch liveness
    render.touch_liveness()
    rendered = render.render()
    assert "1. ⏳ 💬 <i>input received</i>" in rendered
    assert "⏳ <i>still working… (updated just now)</i>" in rendered

    # Finalize -> liveness line is removed
    render.finalize()
    finalized = render.render()
    assert "still working" not in finalized
    assert "completed (1 steps)" in finalized


def test_telegram_bot_watch_liveness_pulse():
    flock = DummyFlockClient()
    telegram = DummyTelegramClient()
    store = CursorStore()
    bot_instance = TelegramBot(
        flock_client=flock,
        telegram_client=telegram,
        cursor_store=store,
        target_agent="architect",
        allowed_chat_id=123,
    )

    render = ActivityRender(chat_id=123, agent="architect")
    render.add_event({"kind": "input"})
    render.flush(telegram)
    assert len(telegram.sent_messages) == 1
    # Reset last_flush_ts so immediate test calls aren't debounced
    render.last_flush_ts = 0.0

    sent_frames = []
    received_count = 0

    class FakeWS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, data):
            sent_frames.append(data)

        def recv(self, timeout=None):
            nonlocal received_count
            if timeout == 2.0:
                # Initial snapshot
                return '{"agent": "architect", "data": "snapshot"}'
            if timeout == 5.0:
                received_count += 1
                if received_count == 1:
                    return '{"agent": "architect", "data": "new terminal bytes"}'
                if received_count == 2:
                    raise TimeoutError()
                render.finalize()
                return '{"agent": "architect", "data": "extra"}'
            raise TimeoutError()

    bot_instance._watch_liveness(
        chat_id=123,
        agent="architect",
        render=render,
        timeout_s=10.0,
        ws_connect_fn=lambda: FakeWS(),
    )

    assert len(sent_frames) == 1
    assert "subscribe" in sent_frames[0]
    assert render.liveness_ts is None  # cleared on finalize
    assert len(telegram.edited_messages) >= 1



