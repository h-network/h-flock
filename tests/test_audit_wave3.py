import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from flock.api.app import Settings, create_app
from flock.session.app import SessionSettings, create_app as create_session_app
from fastapi import HTTPException, status


def test_row_33_websocket_query_token_authentication():
    async def scenario():
        controller = MagicMock()
        app = create_session_app(
            settings=SessionSettings(tenant="office", session_name="hq", api_token="secret"),
            controller=controller,
        )
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
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
            "query_string": b"token=secret",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8081),
            "subprotocols": [],
            "root_path": "",
        }
        await app(scope, receive, send)
        return sent

    sent = asyncio.run(scenario())
    assert any(msg["type"] == "websocket.accept" for msg in sent)


def test_row_34_websocket_unauthorized_sends_close_4401():
    async def scenario():
        controller = MagicMock()
        app = create_session_app(
            settings=SessionSettings(tenant="office", session_name="hq", api_token="secret"),
            controller=controller,
        )
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
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
            "query_string": b"token=wrong_token",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8081),
            "subprotocols": [],
            "root_path": "",
        }
        await app(scope, receive, send)
        return sent

    sent = asyncio.run(scenario())
    close_msg = next((msg for msg in sent if msg["type"] == "websocket.close"), None)
    assert close_msg is not None
    assert close_msg["code"] == 4401
    assert close_msg.get("reason") == "unauthorized"


def test_row_35_alerts_endpoint_uses_alert_preferred_field():
    r = MagicMock()
    alerts_data = [
        (b"1700000000000-0", {b"alert": b'{"module":"watchdog","event":"test"}'})
    ]
    r.xrange.return_value = alerts_data
    r.hget.return_value = b"api"

    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=r,
    )
    all_routes = {route.path: route for route in app.routes if hasattr(route, "path")}
    alerts_route = all_routes.get("/alerts")
    assert alerts_route is not None

    res = alerts_route.endpoint()
    assert len(res["alerts"]) == 1
    assert res["alerts"][0]["module"] == "watchdog"


def test_row_45_envelope_payload_exceeding_1mb_returns_422():
    r = MagicMock()
    r.hget.return_value = b"api"
    r.smembers.return_value = {b"architect"}
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=r,
    )
    all_routes = {route.path: route for route in app.routes if hasattr(route, "path")}
    post_route = all_routes.get("/agents/{agent}/envelopes")
    assert post_route is not None

    large_text = "x" * (1024 * 1024 + 100)
    with pytest.raises(HTTPException) as exc_info:
        post_route.endpoint("architect", {"text": large_text})
    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "exceeds maximum size limit" in exc_info.value.detail
