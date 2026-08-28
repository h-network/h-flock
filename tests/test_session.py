import asyncio
import json

from flock.session.app import SessionSettings, _authorized, _connection_log, create_app
from flock.session.control import ControlModeClient, Subscriber


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class FakeWebSocket:
    def __init__(self, authorization):
        self.headers = FakeHeaders(authorization=authorization)


class FakeController:
    def __init__(self):
        self.sent = []
        self.subscribers = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def update_subscription(self, subscriber, agents, *, refresh=False):
        self.subscribers.append((subscriber, set(agents), refresh))
        subscriber.agents = set(agents)
        for agent in sorted(agents):
            subscriber.queue.put_nowait({"agent": agent, "data": f"snapshot:{agent}"})
        return []

    def unsubscribe(self, subscriber):
        subscriber.agents.clear()

    async def send_keys(self, agent, data):
        self.sent.append((agent, data))


def test_bearer_auth_is_exact_and_constant_scheme_insensitive():
    assert _authorized(FakeWebSocket("Bearer secret"), "secret")
    assert _authorized(FakeWebSocket("bearer secret"), "secret")
    assert not _authorized(FakeWebSocket("Bearer wrong"), "secret")
    assert not _authorized(FakeWebSocket(""), "secret")


def test_session_close_record_names_session_writer(capsys):
    _connection_log("c-1", "browser", {"architect"}, "read", "earlier")

    assert json.loads(capsys.readouterr().out)["writer"] == "session"


def test_snapshot_precedes_output_arriving_during_capture():
    async def scenario():
        controller = ControlModeClient("hq")
        controller.pane_to_agent = {"%1": "alice"}
        controller.agent_to_pane = {"alice": "%1"}

        async def command(*args):
            # The snapshot is capture-pane plus a cursor query; live output that
            # arrives mid-capture must still land after it.
            assert args[0] in ("capture-pane", "display-message")
            if args[0] == "display-message":
                return ["0 0"]
            controller._publish("%1", b"live")
            return ["snapshot"]

        controller.command = command
        subscriber = Subscriber()
        assert await controller.update_subscription(subscriber, {"alice"}) == []
        return [subscriber.queue.get_nowait(), subscriber.queue.get_nowait()]

    # ⚠ The snapshot now clears and homes first, then restores the cursor, so the
    # client's row 1 is the pane's row 1. Without that the client rendered the
    # whole scrollback and then received absolutely-positioned updates for a
    # 32-row screen, which is why an operator saw keystrokes echo far below the
    # prompt.
    assert asyncio.run(scenario()) == [
        {"agent": "alice", "data": "\x1b[2J\x1b[Hsnapshot\x1b[1;1H"},
        {"agent": "alice", "data": "live"},
    ]


def test_refresh_resnapshots_an_already_subscribed_agent():
    async def scenario():
        controller = ControlModeClient("hq")
        controller.pane_to_agent = {"%1": "alice"}
        controller.agent_to_pane = {"alice": "%1"}

        captures = 0

        async def command(*args):
            nonlocal captures
            if args[0] == "display-message":
                return ["0 0"]
            captures += 1
            return [f"frame-{captures}"]

        controller.command = command
        subscriber = Subscriber()
        await controller.update_subscription(subscriber, {"alice"})
        first = subscriber.queue.get_nowait()

        # Same set, no refresh: nothing new — "added" is empty the second time.
        await controller.update_subscription(subscriber, {"alice"})
        assert subscriber.queue.empty()

        # Same set, refresh=true: a fresh capture-pane is taken and published.
        await controller.update_subscription(subscriber, {"alice"}, refresh=True)
        second = subscriber.queue.get_nowait()
        return first, second, captures

    first, second, captures = asyncio.run(scenario())
    assert first["data"] == "\x1b[2J\x1b[Hframe-1\x1b[1;1H"
    assert second["data"] == "\x1b[2J\x1b[Hframe-2\x1b[1;1H"
    assert captures == 2


def test_keystrokes_are_hex_encoded_for_control_protocol():
    async def scenario():
        controller = ControlModeClient("hq")
        controller.agent_to_pane = {"alice": "%1"}
        calls = []

        async def command(*args):
            calls.append(args)
            return []

        controller.command = command
        await controller.send_keys("alice", "A\n\x03")
        return calls

    assert asyncio.run(scenario()) == [
        ("send-keys", "-t", "%1", "-H", "41", "0a", "03")
    ]


def websocket_exchange(messages, *, token="secret"):
    async def scenario():
        controller = FakeController()
        app = create_app(
            settings=SessionSettings(
                tenant="hq", api_token="secret", session_name="hq"
            ),
            controller=controller,
        )
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
        for message in messages:
            incoming.put_nowait(
                {"type": "websocket.receive", "text": json.dumps(message)}
            )
        sent = []

        async def receive():
            if incoming.empty():
                await asyncio.sleep(0.01)
                return {"type": "websocket.disconnect", "code": 1000}
            return await incoming.get()

        async def send(message):
            sent.append(message)

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": "/session",
            "raw_path": b"/session",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8081),
            "subprotocols": [],
            "root_path": "",
        }
        await app(scope, receive, send)
        payloads = [
            json.loads(message["text"])
            for message in sent
            if message["type"] == "websocket.send" and "text" in message
        ]
        return sent, payloads, controller

    return asyncio.run(scenario())


def test_read_only_subscription_refuses_input_server_side():
    sent, payloads, controller = websocket_exchange(
        [
            {"subscribe": ["alice"], "mode": "read-only"},
            {"agent": "alice", "data": "touch /tmp/no"},
        ]
    )
    assert any(message["type"] == "websocket.accept" for message in sent)
    assert {"error": "read-only"} in payloads
    assert controller.sent == []


def test_read_write_subscription_sends_input():
    _, _, controller = websocket_exchange(
        [
            {"subscribe": ["alice"], "mode": "read-write"},
            {"agent": "alice", "data": "echo yes\n"},
        ]
    )
    assert controller.sent == [("alice", "echo yes\n")]


def test_subscribe_refresh_field_reaches_the_controller():
    _, _, controller = websocket_exchange(
        [
            {"subscribe": ["alice"], "mode": "read-only"},
            {"subscribe": ["alice"], "mode": "read-only", "refresh": True},
        ]
    )
    assert [refresh for _, _, refresh in controller.subscribers] == [False, True]


def test_bad_token_is_closed_before_accept():
    sent, _, controller = websocket_exchange([], token="wrong")
    assert sent[0]["type"] == "websocket.close"
    assert sent[0]["code"] == 4401
    assert not any(message["type"] == "websocket.accept" for message in sent)
    assert controller.sent == []


def test_session_has_one_websocket_route_and_no_bus_door_imports():
    app = create_app(
        settings=SessionSettings(tenant="hq", api_token="secret", session_name="hq"),
        controller=FakeController(),
    )
    assert [route.path for route in app.routes if route.path == "/session"] == [
        "/session"
    ]


def test_start_requires_isolated_tmux(monkeypatch):
    import pytest
    from flock.tmux import AmbientTmuxError

    monkeypatch.delenv("TMUX_SOCKET", raising=False)
    monkeypatch.delenv("TMUX_TMPDIR", raising=False)
    controller = ControlModeClient("hq", socket=None)
    with pytest.raises(AmbientTmuxError):
        asyncio.run(controller.start())


def test_refresh_panes_uses_session_scope_flag():
    async def scenario():
        controller = ControlModeClient("hq")
        calls = []

        async def command(*args):
            calls.append(args)
            return ["%0\talice", "%1\tbob"]

        controller.command = command
        await controller.refresh_panes()
        return calls, controller.agent_to_pane

    calls, mapping = asyncio.run(scenario())
    assert calls == [("list-panes", "-s", "-t", "hq", "-F", "#{pane_id}\t#{window_name}")]
    assert mapping == {"alice": "%0", "bob": "%1"}


def test_refresh_panes_handles_hyphenated_names_with_digits():
    async def scenario():
        controller = ControlModeClient("hq")

        async def command(*args):
            return ["%0\tarchitect", "%1\tsme-2", "%2\tsme-3"]

        controller.command = command
        await controller.refresh_panes()
        return controller.agent_to_pane, controller.pane_to_agent

    agent_to_pane, pane_to_agent = asyncio.run(scenario())
    assert agent_to_pane == {"architect": "%0", "sme-2": "%1", "sme-3": "%2"}
    assert pane_to_agent == {"%0": "architect", "%1": "sme-2", "%2": "sme-3"}


def test_session_non_loopback_bind_requires_tls():
    import pytest
    settings = SessionSettings(
        tenant="office",
        api_token="secret",
        session_name="office",
        session_bind="0.0.0.0",
    )
    with pytest.raises(RuntimeError, match="SESSION_TLS_CERT and SESSION_TLS_KEY are required"):
        settings.validate()


def test_session_partial_tls_configuration_raises_error():
    import pytest
    settings = SessionSettings(
        tenant="office",
        api_token="secret",
        session_name="office",
        session_tls_cert="/cert.pem",
    )
    with pytest.raises(RuntimeError, match="Both SESSION_TLS_CERT and SESSION_TLS_KEY must be provided"):
        settings.validate()


def test_session_non_loopback_bind_with_tls_succeeds():
    settings = SessionSettings(
        tenant="office",
        api_token="secret",
        session_name="office",
        session_bind="0.0.0.0",
        session_tls_cert="/cert.pem",
        session_tls_key="/key.pem",
    )
    settings.validate()


