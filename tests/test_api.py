import asyncio
import json
import threading

import pytest
from flock.api import Settings, create_app
from flock.api import app as api_module
from flock.api.app import ReplyStore, _receiver


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.keys = []

    def lrange(self, key, start, end):
        assert (start, end) == (0, -1)
        self.keys.append(key)
        return self

    def execute(self):
        return [self.redis.lists.get(key, []) for key in self.keys]


class FakeRedis:
    def __init__(self):
        self.lengths = {}
        self.lists = {}

    def llen(self, key):
        return self.lengths.get(key, 0)

    def lrange(self, key, start, end):
        assert (start, end) == (0, -1)
        return self.lists.get(key, [])

    def pipeline(self, transaction=False):
        assert transaction is False
        return FakePipeline(self)


@pytest.fixture
def client(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(api_module, "members", lambda *_args, **_kwargs: {b"bob", b"alice"})

    def receive_until_stopped(*_args, **_kwargs):
        threading.Event().wait(0.01)

    monkeypatch.setattr(api_module, "receive", receive_until_stopped)
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=redis,
    )
    yield app, redis


def request(app, method, path, *, token=None, body=None):
    sent = []
    encoded = json.dumps(body).encode() if body is not None else b""
    headers = [(b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(response_body)


def test_every_route_requires_bearer_token(client):
    app, _ = client
    assert request(app, "GET", "/health")[0] == 401
    assert request(app, "GET", "/health", token="wrong")[0] == 401
    assert request(app, "GET", "/health", token="secret") == (200, {"status": "ok"})


def test_send_returns_stream_and_correlation_ids(client, monkeypatch):
    app, _ = client
    sent = {}

    def fake_send(_redis, **kwargs):
        sent.update(kwargs)
        return "stream-1"

    monkeypatch.setattr(api_module, "send", fake_send)
    response_status, response_body = request(
        app, "POST", "/agents/alice/messages", token="secret", body={"text": "hello"}
    )
    assert response_status == 202
    assert response_body["stream_id"] == "stream-1"
    assert response_body["correlation_id"] == sent["correlation_id"]
    assert sent | {"correlation_id": None} == {
        "pod": "test",
        "tenant": "office",
        "producer": "api",
        "recipient": "alice",
        "payload": {"text": "hello"},
        "correlation_id": None,
        "module": "api",
    }
    assert len(response_body["correlation_id"]) == 32
    int(response_body["correlation_id"], 16)


def test_board_aggregate_is_roster_bounded_and_pipelined(client):
    app, redis = client
    redis.lists.update(
        {
            "pod:test:tenant:office:agent:alice:tasks.todo": [b"one"],
        }
    )
    assert request(app, "GET", "/board", token="secret")[1] == {
        "agents": [
            {"agent": "alice", "todo": ["one"], "doing": [], "done": []},
            {"agent": "bob", "todo": [], "doing": [], "done": []},
        ]
    }


def test_non_loopback_bind_requires_token():
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        create_app(settings=Settings(pod="test", tenant="office", api_bind="0.0.0.0"), redis_client=FakeRedis())


def test_loopback_bind_also_requires_token():
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        create_app(settings=Settings(pod="test", tenant="office"), redis_client=FakeRedis())


def test_reply_store_is_bounded_by_correlation_and_reply_count():
    replies = ReplyStore(max_correlations=2, max_replies_per_correlation=2)
    replies.add({"correlation_id": "old", "payload": 1})
    replies.add({"correlation_id": "kept", "payload": 1})
    replies.add({"correlation_id": "kept", "payload": 2})
    replies.add({"correlation_id": "kept", "payload": 3})
    replies.add({"correlation_id": "new", "payload": 1})

    assert replies.get("old") == []
    assert [message["payload"] for message in replies.get("kept")] == [2, 3]


def test_receiver_recovers_after_error_and_identifies_api_module(monkeypatch):
    stop = threading.Event()
    calls = []
    logs = []

    def flaky_receive(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ConnectionError("redis unavailable")
        stop.set()

    monkeypatch.setattr(api_module, "receive", flaky_receive)
    monkeypatch.setattr(api_module, "log_record", lambda *args, **kwargs: logs.append((args, kwargs)))
    _receiver(
        FakeRedis(),
        Settings(pod="test", tenant="office", api_token="secret"),
        ReplyStore(),
        stop,
        backoff_seconds=0,
    )

    assert len(calls) == 2
    assert calls[1]["module"] == "api"
    assert logs == [(('api', 'receiver_error'), {'reason': 'redis unavailable'})]
