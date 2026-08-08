import asyncio
import json

import pytest
from flock.api import Settings, create_app
from flock.api import app as api_module


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
    try:
        parsed = json.loads(response_body)
    except Exception:
        parsed = response_body.decode("utf-8", "replace")
    return start["status"], parsed


def test_every_route_requires_bearer_token(client):
    app, _ = client
    assert request(app, "GET", "/health")[0] == 401
    assert request(app, "GET", "/health", token="wrong")[0] == 401
    assert request(app, "GET", "/health", token="secret") == (200, {"status": "ok"})


def test_restdoc_endpoint_requires_auth_and_serves_html(client):
    app, _ = client
    assert request(app, "GET", "/restdoc")[0] == 401
    assert request(app, "GET", "/restdoc", token="wrong")[0] == 401
    status, content = request(app, "GET", "/restdoc", token="secret")
    assert status == 200
    assert "flock API &amp; Session Documentation" in content
    assert "Message" in content
    assert "Command" in content
    assert "StartAgent" in content
    assert "StopAgent" in content
    assert "Notice: This list of kinds is current, not authoritative." in content
    assert "Meaning of HTTP 202 Accepted" in content
    assert "120×32" in content
    assert "ws://&lt;host&gt;:8081/session" in content


def test_generated_docs_endpoints_require_auth(client):
    app, _ = client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert request(app, "GET", path)[0] == 401
        assert request(app, "GET", path, token="wrong")[0] == 401
        assert request(app, "GET", path, token="secret")[0] == 200



def test_envelope_passes_unknown_kind_and_payload_without_validation(client, monkeypatch):
    app, _ = client
    sent = {}

    def fake_send(_redis, **kwargs):
        sent.update(kwargs)
        return "stream-1"

    monkeypatch.setattr(api_module, "send", fake_send)
    response_status, response_body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"kind": "KindAddedLater", "payload": {"shape": ["is", "opaque"]}},
    )
    assert response_status == 202
    assert response_body["stream_id"] == "stream-1"
    assert response_body["correlation_id"] == sent["correlation_id"]
    assert sent | {"correlation_id": None} == {
        "pod": "test",
        "tenant": "office",
        "producer": "api",
        "recipient": "alice",
        "kind": "KindAddedLater",
        "payload": {"shape": ["is", "opaque"]},
        "correlation_id": None,
        "module": "api",
    }
    assert len(response_body["correlation_id"]) == 32
    int(response_body["correlation_id"], 16)


def test_text_only_body_is_message_sugar(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(
        api_module,
        "send",
        lambda _redis, **kwargs: sent.update(kwargs) or "stream-1",
    )

    response_status, _ = request(
        app, "POST", "/agents/alice/envelopes", token="secret", body={"text": "hello"}
    )

    assert response_status == 202
    assert sent["kind"] == "Message"
    assert sent["payload"] == {"text": "hello"}


def test_messages_endpoint_is_not_exposed(client):
    app, _ = client
    assert request(
        app, "POST", "/agents/alice/messages", token="secret", body={"text": "hello"}
    )[0] == 404


def test_board_aggregate_is_roster_bounded_and_pipelined(client):
    app, redis = client
    redis.lists.update(
        {
            "pod:test:tenant:office:agent:alice:tasks.todo": [b"one"],
        }
    )
    assert request(app, "GET", "/board", token="secret")[1] == {
        "agents": [
            {"agent": "alice", "todo": ["one"], "doing": [], "hold": [], "done": []},
            {"agent": "bob", "todo": [], "doing": [], "hold": [], "done": []},
        ]
    }


def test_single_agent_board_four_lists_and_json_tickets(client):
    app, redis = client
    ticket1 = json.dumps({"v": 1, "id": "t1", "title": "task 1", "status": "todo"}).encode()
    ticket2 = json.dumps({"id": "t2", "title": "build 10 task", "from": "architect"}).encode()
    ticket3 = json.dumps({"v": 1, "id": "t3", "title": "held task", "status": "hold"}).encode()

    redis.lists.update(
        {
            "pod:test:tenant:office:agent:alice:tasks.todo": [ticket1, ticket2],
            "pod:test:tenant:office:agent:alice:tasks.hold": [ticket3],
        }
    )

    status, body = request(app, "GET", "/agents/alice/board", token="secret")
    assert status == 200
    assert body == {
        "agent": "alice",
        "todo": [
            {"v": 1, "id": "t1", "title": "task 1", "status": "todo"},
            {"id": "t2", "title": "build 10 task", "from": "architect"},
        ],
        "doing": [],
        "hold": [{"v": 1, "id": "t3", "title": "held task", "status": "hold"}],
        "done": [],
    }


def test_non_loopback_bind_requires_token():
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        create_app(settings=Settings(pod="test", tenant="office", api_bind="0.0.0.0"), redis_client=FakeRedis())


def test_loopback_bind_also_requires_token():
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        create_app(settings=Settings(pod="test", tenant="office"), redis_client=FakeRedis())


def test_reply_collection_endpoint_is_not_exposed(client):
    app, _ = client
    assert request(app, "GET", "/messages/correlation", token="secret")[0] == 404

