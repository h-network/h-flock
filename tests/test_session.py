import asyncio
import json

from flock.session.app import SessionSettings, _authorized, create_app
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

    async def update_subscription(self, subscriber, agents):
        self.subscribers.append((subscriber, set(agents)))
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



