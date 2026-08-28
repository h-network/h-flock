"""Server-side Read-Only Security Audit & Attack Test (SPEC §6 & Architect Challenge).

Proves that the Session Door server enforces read-only mode server-side and that
clients lying or sending raw WebSocket keystroke frames while in read-only mode are REJECTED
by the backend (not just by browser JavaScript).
"""

import asyncio
import json
from flock.session.app import SessionSettings, create_app
from flock.session.control import Subscriber


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
        self.subscribers.append((subscriber, set(agents)))
        subscriber.agents = set(agents)
        for agent in sorted(agents):
            subscriber.queue.put_nowait({"agent": agent, "data": f"snapshot:{agent}"})
        return []

    def unsubscribe(self, subscriber):
        subscriber.agents.clear()

    async def send_keys(self, agent, data):
        self.sent.append((agent, data))


def execute_ws_attack(messages, *, token="secret"):
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


def test_attack_1_raw_keystroke_on_readonly_socket_rejected_by_server():
    """Attack Test 1: Client connects in read-only mode and attempts sending keystrokes."""
    sent, payloads, controller = execute_ws_attack(
        [
            {"subscribe": ["architect"], "mode": "read-only"},
            {"agent": "architect", "data": "rm -rf / # ATTACK"},
        ]
    )
    # Server accepts WS connection
    assert any(message["type"] == "websocket.accept" for message in sent)
    # Server rejects keystroke with read-only error
    assert {"error": "read-only"} in payloads
    # Zero keystrokes reach tmux controller
    assert controller.sent == []


def test_attack_2_midstream_privilege_escalation_rejected_by_server():
    """Attack Test 2: Client subscribes as read-only, then attempts to mutate mode to read-write."""
    sent, payloads, controller = execute_ws_attack(
        [
            {"subscribe": ["architect"], "mode": "read-only"},
            {"subscribe": ["architect"], "mode": "read-write"},  # Escalation attempt
            {"agent": "architect", "data": "rm -rf / # ATTACK"},
        ]
    )
    # Server rejects mode mutation with mode cannot change error
    assert {"error": "mode cannot change"} in payloads
    assert {"error": "read-only"} in payloads
    # Zero keystrokes reach tmux controller
    assert controller.sent == []


def test_attack_3_unsubscribed_keystroke_rejected_by_server():
    """Attack Test 3: Client attempts to send keystrokes without subscribing at all."""
    sent, payloads, controller = execute_ws_attack(
        [
            {"agent": "architect", "data": "rm -rf / # ATTACK"},
        ]
    )
    assert {"error": "agent is not subscribed"} in payloads
    assert controller.sent == []


def test_legitimate_read_write_socket_allows_keystrokes():
    """Control Test: Read-write mode explicitly requested allows keystrokes."""
    sent, payloads, controller = execute_ws_attack(
        [
            {"subscribe": ["architect"], "mode": "read-write"},
            {"agent": "architect", "data": "ls -la\n"},
        ]
    )
    assert controller.sent == [("architect", "ls -la\n")]
