import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import redis.exceptions

from flock.api.app import Settings, create_app, _read_stream_entries, _stream_response
from flock.session.app import SessionSettings, create_app as create_session_app
from flock.session.control import ControlModeClient
from fastapi import HTTPException, status


class FakeRedis:
    def __init__(self, data=None):
        self.data = data or {}

    def xrange(self, key, min="-", max="+", count=None):
        raise redis.exceptions.RedisError("Redis connection refused")


def test_row_19_websocket_malformed_json_returns_error_frame():
    async def scenario():
        controller = MagicMock()
        app = create_session_app(
            settings=SessionSettings(tenant="office", session_name="hq", api_token="secret"),
            controller=controller,
        )
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
        incoming.put_nowait({"type": "websocket.receive", "text": "{invalid json format"})
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
            "headers": [(b"authorization", b"Bearer secret")],
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
        return payloads

    payloads = asyncio.run(scenario())
    assert {"error": "invalid json"} in payloads


def test_row_21_redis_stream_read_failure_returns_500():
    r = FakeRedis()
    with pytest.raises(HTTPException) as exc_info:
        _read_stream_entries(r, "key", None, 100)
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_row_20_sse_midflight_error_emits_sse_error_event():
    request = MagicMock()
    request.headers = {}
    request.is_disconnected = AsyncMock(side_effect=[False, False])

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.side_effect = HTTPException(status_code=500, detail="Redis connection lost")
        response = _stream_response(request, MagicMock(), "key", "event", None, "envelope")

        async def collect_events():
            events = []
            async for chunk in response.body_iterator:
                events.append(chunk)
            return events

        events = asyncio.run(collect_events())
        assert len(events) == 1
        assert "event: error" in events[0]
        assert "Redis connection lost" in events[0]


def test_row_22_malformed_as_client_returns_422():
    r = MagicMock()

    def fake_hget(name, key):
        if not isinstance(key, (str, bytes)):
            raise redis.exceptions.DataError("Invalid input of type: 'dict'")
        return None

    r.hget.side_effect = fake_hget
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=r,
    )
    all_routes = {route.path: route for route in app.routes if hasattr(route, "path")}
    post_route = all_routes.get("/agents/{agent}/envelopes")
    assert post_route is not None

    # Invalid segment string
    with pytest.raises(HTTPException) as exc_info:
        post_route.endpoint("architect", {"as": "invalid:segment:name"})
    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Non-string dict payload (would raise DataError in redis-py if passed to hget)
    with pytest.raises(HTTPException) as exc_info2:
        post_route.endpoint("architect", {"as": {"dict": "payload"}})
    assert exc_info2.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Non-string list payload
    with pytest.raises(HTTPException) as exc_info3:
        post_route.endpoint("architect", {"as": ["list", "payload"]})
    assert exc_info3.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
