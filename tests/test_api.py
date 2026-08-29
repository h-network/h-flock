from conftest import FakeRedis, FakePipeline
import asyncio
import base64
import hashlib
import hmac as hmac_lib
import json

import pytest
from flock.api import Settings, create_app
from flock.api import app as api_module
from flock.bus import parse, prefix



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

    if "?" in path:
        path, query = path.split("?", 1)
        query_string = query.encode()
    else:
        query_string = b""

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
        "query_string": query_string,
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
        "source": "api",
        "destination": "alice",
        "kind": "KindAddedLater",
        "payload": {"shape": ["is", "opaque"]},
        "correlation_id": None,
        "module": "api",
    }
    assert len(response_body["correlation_id"]) == 32
    int(response_body["correlation_id"], 16)


def test_post_envelope_qualified_destination_http_routing(client):
    app, redis = client

    status_code, body = request(
        app,
        "POST",
        "/agents/test:office:alice/envelopes",
        token="secret",
        body={"text": "hello"},
    )
    assert status_code == 202
    assert "stream_id" in body
    assert "correlation_id" in body
    queued = parse(redis.lists[prefix("test", "office", "api", "egress")][0])
    assert queued["l2"]["destination"] == "alice"
    assert queued["l3"]["destination"] == "test:office:alice"

    status_code, body = request(
        app,
        "POST",
        "/agents/other:office:alice/envelopes",
        token="secret",
        body={"text": "hello"},
    )
    assert status_code == 422
    assert body == {
        "detail": "no route to non-local destination 'other:office:alice'"
    }

    status_code, body = request(
        app,
        "POST",
        "/agents/test:office:alice:extra/envelopes",
        token="secret",
        body={"text": "hello"},
    )
    assert status_code == 404
    assert body == {"detail": "invalid agent"}


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
    )[0] in (404, 405)


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


def test_non_loopback_bind_requires_tls():
    with pytest.raises(RuntimeError, match="API_TLS_CERT and API_TLS_KEY are required"):
        create_app(
            settings=Settings(pod="test", tenant="office", api_token="secret", api_bind="0.0.0.0"),
            redis_client=FakeRedis(),
        )


def test_partial_tls_configuration_raises_error():
    with pytest.raises(RuntimeError, match="Both API_TLS_CERT and API_TLS_KEY must be provided"):
        create_app(
            settings=Settings(pod="test", tenant="office", api_token="secret", api_tls_cert="/cert.pem"),
            redis_client=FakeRedis(),
        )


def test_non_loopback_bind_with_tls_succeeds():
    app = create_app(
        settings=Settings(
            pod="test",
            tenant="office",
            api_token="secret",
            api_bind="0.0.0.0",
            api_tls_cert="/cert.pem",
            api_tls_key="/key.pem",
        ),
        redis_client=FakeRedis(),
    )
    assert app is not None


def _request_headers(app, method, path, *, token=None, origin=None):
    """Like `request`, but returns response headers too (for CORS assertions)."""
    sent = []
    headers = [(b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

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
    response_headers = {k.decode(): v.decode() for k, v in start["headers"]}
    return start["status"], response_headers


def test_cors_header_absent_when_not_published():
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=FakeRedis(),
    )
    _, headers = _request_headers(app, "GET", "/health", token="secret", origin="https://example.com")
    assert "access-control-allow-origin" not in headers


def test_cors_header_absent_when_published_with_no_origins_configured():
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret", api_published=True),
        redis_client=FakeRedis(),
    )
    _, headers = _request_headers(app, "GET", "/health", token="secret", origin="https://example.com")
    assert "access-control-allow-origin" not in headers


def test_cors_header_present_for_configured_origin_when_published():
    app = create_app(
        settings=Settings(
            pod="test", tenant="office", api_token="secret",
            api_published=True, api_cors_origins=("https://example.com",),
        ),
        redis_client=FakeRedis(),
    )
    _, headers = _request_headers(app, "GET", "/health", token="secret", origin="https://example.com")
    assert headers["access-control-allow-origin"] == "https://example.com"


def test_cors_header_absent_for_unconfigured_origin_when_published():
    app = create_app(
        settings=Settings(
            pod="test", tenant="office", api_token="secret",
            api_published=True, api_cors_origins=("https://example.com",),
        ),
        redis_client=FakeRedis(),
    )
    _, headers = _request_headers(app, "GET", "/health", token="secret", origin="https://evil.example")
    assert "access-control-allow-origin" not in headers


def test_reply_collection_endpoint_is_not_exposed(client):
    app, _ = client
    assert request(app, "GET", "/messages/correlation", token="secret")[0] == 404


def test_post_envelope_with_valid_as_client(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(
        api_module,
        "send",
        lambda _redis, **kwargs: sent.update(kwargs) or "stream-1",
    )

    status_code, response_body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"text": "hello", "as": "telegram"},
    )
    assert status_code == 202
    assert sent["source"] == "telegram"
    assert sent["destination"] == "alice"
    assert sent["payload"] == {"text": "hello"}


def test_post_envelope_with_invalid_as_client_rejected(client):
    app, _ = client
    # bob has port_type "tmux" (not "api")
    status_code_tmux, _ = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"text": "hello", "as": "bob"},
    )
    assert status_code_tmux == 422

    # unknown is not in roster
    status_code_unknown, _ = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"text": "hello", "as": "unknown"},
    )
    assert status_code_unknown == 422


def _sign(secret, envelope):
    signable = {key: value for key, value in envelope.items() if key != "sig"}
    canonical = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac_lib.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _published_client(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(api_module, "members", lambda *_args, **_kwargs: {b"telegram", b"alice"})
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret", api_published=True),
        redis_client=redis,
    )
    return app, redis


def test_published_as_without_signature_rejected(monkeypatch):
    app, _ = _published_client(monkeypatch)
    status_code, body = request(
        app, "POST", "/agents/alice/envelopes", token="secret", body={"text": "hi", "as": "telegram"},
    )
    assert status_code == 401
    assert "signature" in body["detail"]


def test_published_as_with_wrong_signature_rejected(monkeypatch):
    app, redis = _published_client(monkeypatch)
    hmac_keys_key = prefix("test", "office", "telegram", "hmac-keys")
    redis.hashes[hmac_keys_key] = {
        "telegram-2026-08": json.dumps({"secret": "correct-horse-battery-staple", "created_ts": 1.0})
    }
    status_code, body = request(
        app, "POST", "/agents/alice/envelopes", token="secret",
        body={"text": "hi", "as": "telegram", "kid": "telegram-2026-08", "sig": "wrong"},
    )
    assert status_code == 401
    assert "signature" in body["detail"]


def test_published_as_with_unknown_kid_rejected(monkeypatch):
    app, redis = _published_client(monkeypatch)
    hmac_keys_key = prefix("test", "office", "telegram", "hmac-keys")
    redis.hashes[hmac_keys_key] = {
        "telegram-2026-08": json.dumps({"secret": "correct-horse-battery-staple", "created_ts": 1.0})
    }
    envelope = {"text": "hi", "as": "telegram", "kid": "telegram-2026-07"}
    envelope["sig"] = _sign("correct-horse-battery-staple", envelope)
    status_code, body = request(app, "POST", "/agents/alice/envelopes", token="secret", body=envelope)
    assert status_code == 401


def test_published_as_with_valid_signature_accepted(monkeypatch):
    app, redis = _published_client(monkeypatch)
    hmac_keys_key = prefix("test", "office", "telegram", "hmac-keys")
    secret = "correct-horse-battery-staple"
    redis.hashes[hmac_keys_key] = {
        "telegram-2026-08": json.dumps({"secret": secret, "created_ts": 1.0})
    }
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")
    envelope = {"text": "hi", "as": "telegram", "kid": "telegram-2026-08"}
    envelope["sig"] = _sign(secret, envelope)
    status_code, body = request(app, "POST", "/agents/alice/envelopes", token="secret", body=envelope)
    assert status_code == 202
    assert sent["source"] == "telegram"


def test_published_signature_cannot_be_replayed_under_a_different_kid(monkeypatch):
    """The kid itself is covered by the signed material (app.py `_canonical_envelope`)."""
    app, redis = _published_client(monkeypatch)
    hmac_keys_key = prefix("test", "office", "telegram", "hmac-keys")
    secret = "correct-horse-battery-staple"
    redis.hashes[hmac_keys_key] = {
        "telegram-2026-08": json.dumps({"secret": secret, "created_ts": 1.0}),
        "telegram-2026-09": json.dumps({"secret": secret, "created_ts": 2.0}),
    }
    envelope = {"text": "hi", "as": "telegram", "kid": "telegram-2026-08"}
    envelope["sig"] = _sign(secret, envelope)
    # Same signature, presented under a different kid — must not verify.
    forged = dict(envelope, kid="telegram-2026-09")
    status_code, body = request(app, "POST", "/agents/alice/envelopes", token="secret", body=forged)
    assert status_code == 401


def test_published_without_as_is_unaffected(monkeypatch):
    app, _ = _published_client(monkeypatch)
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")
    status_code, _ = request(app, "POST", "/agents/alice/envelopes", token="secret", body={"text": "hi"})
    assert status_code == 202
    assert sent["source"] == "api"


def test_not_published_as_is_unaffected_even_without_signature(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")
    status_code, _ = request(
        app, "POST", "/agents/alice/envelopes", token="secret", body={"text": "hi", "as": "telegram"},
    )
    assert status_code == 202
    assert sent["source"] == "telegram"


def test_get_messages_for_api_client(client):
    app, redis = client
    env = {
        "v": 1,
        "source": "alice",
        "destination": "telegram",
        "kind": "Message",
        "payload": {"text": "reply text"},
        "stream_id": "s-1",
        "correlation_id": "c-1",
        "timestamp": "2026-08-09T01:00:00Z",
    }
    inbox_key = "pod:test:tenant:office:agent:telegram:inbox"
    redis.streams[inbox_key] = [
        (b"1000-0", {b"envelope": json.dumps(env).encode()}),
    ]

    status_code, body = request(app, "GET", "/agents/telegram/messages", token="secret")
    assert status_code == 200
    assert body == {
        "agent": "telegram",
        "messages": [
            {
                "cursor": "1000-0",
                "v": 1,
                "source": "alice",
                "destination": "telegram",
                "kind": "Message",
                "payload": {"text": "reply text"},
                "stream_id": "s-1",
                "correlation_id": "c-1",
                "timestamp": "2026-08-09T01:00:00Z",
            }
        ],
        "next_cursor": "1000-0",
    }


def test_get_messages_cursor_after(client):
    app, redis = client
    env1 = {"v": 1, "source": "alice", "destination": "telegram", "kind": "Message", "payload": {"text": "msg1"}}
    env2 = {"v": 1, "source": "bob", "destination": "telegram", "kind": "Message", "payload": {"text": "msg2"}}
    inbox_key = "pod:test:tenant:office:agent:telegram:inbox"
    redis.streams[inbox_key] = [
        (b"1000-0", {b"envelope": json.dumps(env1).encode()}),
        (b"1001-0", {b"envelope": json.dumps(env2).encode()}),
    ]

    status_code, body = request(app, "GET", "/agents/telegram/messages?after=1000-0", token="secret")
    assert status_code == 200
    assert len(body["messages"]) == 1
    assert body["messages"][0]["cursor"] == "1001-0"
    assert body["messages"][0]["source"] == "bob"
    assert body["next_cursor"] == "1001-0"


def test_get_messages_non_api_agent_returns_404(client):
    app, _ = client
    # bob is port_type "tmux", so GET /agents/bob/messages should return 404
    status_code, _ = request(app, "GET", "/agents/bob/messages", token="secret")
    assert status_code == 404


def test_message_routes_reject_invalid_enrolled_client_name(client):
    app, redis = client
    # A corrupt or legacy roster row must not turn key validation into a 500.
    redis.roster[b"bad:name"] = b"api"

    assert request(app, "GET", "/agents/bad:name/messages", token="secret") == (
        404,
        {"detail": "invalid client agent"},
    )
    assert request(app, "GET", "/agents/bad:name/messages/stream", token="secret") == (
        404,
        {"detail": "invalid client agent"},
    )


def test_hyphenated_agent_names_with_digits(client):
    app, redis = client
    # Set up sme-2 in roster as api client
    redis.roster[b"sme-2"] = b"api"

    # 1. Queue depths for sme-2
    status_code, body = request(app, "GET", "/agents/sme-2", token="secret")
    assert status_code == 200
    assert body == {
        "agent": "sme-2",
        "port_type": "api",
        "depths": {"ingress": 0, "egress": 0, "dead": 0},
        "presence": {"state": "unknown", "since": "", "last_activity": ""},
    }

    # 2. Post envelope to sme-2
    status_code, body = request(app, "POST", "/agents/sme-2/envelopes", token="secret", body={"text": "hello sme-2"})
    assert status_code == 202
    assert "stream_id" in body

    # 3. Post envelope as sme-2
    status_code, body = request(app, "POST", "/agents/alice/envelopes", token="secret", body={"text": "from sme-2", "as": "sme-2"})
    assert status_code == 202

    # 4. Board read for sme-2
    status_code, body = request(app, "GET", "/agents/sme-2/board", token="secret")
    assert status_code == 200
    assert body == {"agent": "sme-2", "todo": [], "doing": [], "hold": [], "done": []}

    # 5. Messages for sme-2
    inbox_key = "pod:test:tenant:office:agent:sme-2:inbox"
    env = {"v": 1, "source": "architect", "destination": "sme-2", "kind": "Message", "payload": {"text": "task for sme-2"}}
    redis.streams[inbox_key] = [(b"2000-0", {b"envelope": json.dumps(env).encode()})]
    status_code, body = request(app, "GET", "/agents/sme-2/messages", token="secret")
    assert status_code == 200
    assert body["agent"] == "sme-2"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["destination"] == "sme-2"


def test_get_activity_empty(client):
    app, _ = client
    # Any valid agent segment name returns 200 with empty activity feed when no stream entries exist
    status_code, body = request(app, "GET", "/agents/sme-2/activity", token="secret")
    assert status_code == 200
    assert body == {"agent": "sme-2", "activity": [], "next_cursor": None}


def test_get_activity_with_events_and_cursor(client):
    app, redis = client
    act1 = {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:00Z", "kind": "input"}
    act2 = {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:01Z", "kind": "tool", "tool": "Bash"}
    act_key = "pod:test:tenant:office:agent:sme-2:activity"
    redis.streams[act_key] = [
        (b"1000-0", {b"event": json.dumps(act1).encode()}),
        (b"1001-0", {b"event": json.dumps(act2).encode()}),
    ]

    # Read all
    status_code, body = request(app, "GET", "/agents/sme-2/activity", token="secret")
    assert status_code == 200
    assert body["agent"] == "sme-2"
    assert len(body["activity"]) == 2
    assert body["activity"][0]["cursor"] == "1000-0"
    assert body["activity"][0]["kind"] == "input"
    assert body["activity"][1]["cursor"] == "1001-0"
    assert body["activity"][1]["tool"] == "Bash"
    assert body["next_cursor"] == "1001-0"

    # Catch-up with cursor
    status_code, body = request(app, "GET", "/agents/sme-2/activity?after=1000-0", token="secret")
    assert status_code == 200
    assert len(body["activity"]) == 1
    assert body["activity"][0]["cursor"] == "1001-0"
    assert body["next_cursor"] == "1001-0"


def test_get_activity_invalid_agent_returns_404(client):
    app, _ = client
    # "all" or invalid segment names return 404
    status_code, _ = request(app, "GET", "/agents/all/activity", token="secret")
    assert status_code == 404
    status_code, _ = request(app, "GET", "/agents/123/activity", token="secret")
    assert status_code == 404


def test_get_agent_queues_and_presence_populated(client):
    app, redis = client
    presence_key = "pod:test:tenant:office:agent:sme-2:presence"
    redis.hashes[presence_key] = {
        b"state": b"working",
        b"since": b"2026-08-09T13:00:00.000Z",
        b"last_activity": b"2026-08-09T13:15:00.000Z",
    }
    status_code, body = request(app, "GET", "/agents/sme-2", token="secret")
    assert status_code == 200
    assert body == {
        "agent": "sme-2",
        "port_type": "tmux",
        "depths": {"ingress": 0, "egress": 0, "dead": 0},
        "presence": {
            "state": "working",
            "since": "2026-08-09T13:00:00.000Z",
            "last_activity": "2026-08-09T13:15:00.000Z",
        },
    }


def test_unknown_agent_returns_404_enrolled_agent_returns_200(client):
    app, _ = client
    # Unenrolled agent nosuchagent -> 404 Not Found across all agent routes
    assert request(app, "GET", "/agents/nosuchagent", token="secret")[0] == 404
    assert request(app, "GET", "/agents/nosuchagent/board", token="secret")[0] == 404
    assert request(app, "GET", "/agents/nosuchagent/messages", token="secret")[0] == 404
    assert request(app, "GET", "/agents/nosuchagent/activity", token="secret")[0] == 404
    assert request(app, "POST", "/agents/nosuchagent/envelopes", token="secret", body={"text": "hi"})[0] == 404

    # Enrolled agent holding nothing (e.g. sme-2 holding nothing) -> 200 OK
    status, body = request(app, "GET", "/agents/sme-2", token="secret")
    assert status == 200
    assert body["agent"] == "sme-2"
    assert body["port_type"] == "tmux"
    assert body["depths"] == {"ingress": 0, "egress": 0, "dead": 0}

    status, body = request(app, "GET", "/agents/sme-2/board", token="secret")
    assert status == 200
    assert body == {"agent": "sme-2", "todo": [], "doing": [], "hold": [], "done": []}

    status, body = request(app, "GET", "/agents/sme-2/activity", token="secret")
    assert status == 200
    assert body["activity"] == []


def test_post_envelopes_broadcast_all_and_host_work(client):
    app, _ = client
    # POST /agents/all/envelopes (broadcast) works even though 'all' is not in roster
    status, body = request(app, "POST", "/agents/all/envelopes", token="secret", body={"text": "broadcast message"})
    assert status == 202
    assert "stream_id" in body

    # POST /agents/host/envelopes (lifecycle) works because 'host' is in roster
    status, body = request(app, "POST", "/agents/host/envelopes", token="secret", body={"kind": "StartAgent", "payload": {"agent": "carol"}})
    assert status == 202
    assert "stream_id" in body


def test_get_alerts_empty(client):
    app, _ = client
    status_code, body = request(app, "GET", "/alerts", token="secret")
    assert status_code == 200
    assert body == {"alerts": [], "next_cursor": None}


def test_get_alerts_with_events_and_cursor(client):
    app, redis = client
    alert1 = {"v": 1, "ts": "2026-08-09T15:00:00Z", "kind": "stalled", "agent": "sme-2"}
    alert2 = {"v": 1, "ts": "2026-08-09T15:01:00Z", "kind": "stalled", "agent": "sme-3"}
    alerts_key = "pod:test:tenant:office:alerts"
    redis.streams[alerts_key] = [
        (b"2000-0", {b"event": json.dumps(alert1).encode()}),
        (b"2001-0", {b"event": json.dumps(alert2).encode()}),
    ]

    status_code, body = request(app, "GET", "/alerts", token="secret")
    assert status_code == 200
    assert len(body["alerts"]) == 2
    assert body["alerts"][0]["cursor"] == "2000-0"
    assert body["alerts"][0]["agent"] == "sme-2"
    assert body["alerts"][1]["cursor"] == "2001-0"
    assert body["alerts"][1]["agent"] == "sme-3"
    assert body["next_cursor"] == "2001-0"

    status_code, body = request(app, "GET", "/alerts?after=2000-0", token="secret")
    assert status_code == 200
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["cursor"] == "2001-0"
    assert body["next_cursor"] == "2001-0"


def test_get_agent_blocked_presence(client):
    app, redis = client
    presence_key = "pod:test:tenant:office:agent:sme-2:presence"
    blocked_key = "pod:test:tenant:office:agent:sme-2:blocked"
    redis.hashes[presence_key] = {
        b"state": b"idle",
        b"since": b"2026-08-09T15:00:00Z",
        b"last_activity": b"2026-08-09T15:01:00Z",
    }
    redis.hashes[blocked_key] = {
        b"since": b"2026-08-09T15:02:00Z",
        b"stream_id": b"1000-0",
    }

    status, body = request(app, "GET", "/agents/sme-2", token="secret")
    assert status == 200
    assert body["presence"]["state"] == "blocked"
    assert body["presence"]["since"] == "2026-08-09T15:00:00Z"


def test_post_envelope_policy_denied_returns_422(client):
    app, redis = client
    # Set disjoint tags: telegram exports ['finance'], bob imports ['ops']
    telegram_tags_key = "pod:test:tenant:office:agent:telegram:tags"
    bob_tags_key = "pod:test:tenant:office:agent:bob:tags"
    redis.hashes[telegram_tags_key] = {"export": json.dumps(["finance"])}
    redis.hashes[bob_tags_key] = {"import": json.dumps(["ops"])}

    status_code, body = request(
        app,
        "POST",
        "/agents/bob/envelopes",
        token="secret",
        body={"text": "hello bob", "as": "telegram"},
    )
    assert status_code == 422
    assert body == {"detail": "policy denied 'telegram' -> 'bob': no shared export/import tag"}


def test_post_envelope_policy_permitted_returns_202(client):
    app, redis = client
    # Set overlapping tags: telegram exports ['ops', 'finance'], bob imports ['ops']
    telegram_tags_key = "pod:test:tenant:office:agent:telegram:tags"
    bob_tags_key = "pod:test:tenant:office:agent:bob:tags"
    redis.hashes[telegram_tags_key] = {"export": json.dumps(["ops", "finance"])}
    redis.hashes[bob_tags_key] = {"import": json.dumps(["ops"])}

    status_code, body = request(
        app,
        "POST",
        "/agents/bob/envelopes",
        token="secret",
        body={"text": "hello bob", "as": "telegram"},
    )
    assert status_code == 202
    assert "stream_id" in body
    assert "correlation_id" in body


def test_post_envelope_policy_permitted_when_absent_returns_202(client):
    app, redis = client
    # Clear tags: unconfigured participants inside tenant permit by default
    status_code, body = request(
        app,
        "POST",
        "/agents/bob/envelopes",
        token="secret",
        body={"text": "hello bob", "as": "telegram"},
    )
    assert status_code == 202
    assert "stream_id" in body


def test_send_door_non_local_destination_raises_envelope_error(client):
    _, redis = client
    from flock.bus.doors import send
    from flock.bus.envelope import EnvelopeError

    with pytest.raises(EnvelopeError, match="no route to non-local destination 'otherpod:othertenant:bob'"):
        send(
            redis,
            pod="test",
            tenant="office",
            source="telegram",
            destination="otherpod:othertenant:bob",
            payload={"text": "remote msg"},
        )


def test_post_envelope_attachment_valid_accepted(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")

    # 2 MB binary file payload (larger than 1MB default limit)
    raw_data = b"x" * (2 * 1024 * 1024)
    b64_data = base64.b64encode(raw_data).decode("ascii")

    envelope = {
        "kind": "Attachment",
        "payload": {
            "filename": "diagram.png",
            "mime_type": "image/png",
            "content_base64": b64_data,
            "caption": "system architecture diagram",
        },
    }
    status_code, body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body=envelope,
    )
    assert status_code == 202
    assert "stream_id" in body
    assert sent["kind"] == "Attachment"
    assert sent["payload"]["filename"] == "diagram.png"


def test_post_envelope_attachment_exact_max_boundary_accepted(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")

    # Exactly 10,485,760 bytes (10 MiB)
    raw_data = b"y" * 10_485_760
    b64_data = base64.b64encode(raw_data).decode("ascii")

    envelope = {
        "kind": "Attachment",
        "payload": {
            "filename": "archive.tar.gz",
            "mime_type": "application/gzip",
            "content_base64": b64_data,
        },
    }
    status_code, body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body=envelope,
    )
    assert status_code == 202
    assert "stream_id" in body


def test_post_envelope_attachment_exceeding_decoded_max_rejected(client):
    app, _ = client
    # 10,485,761 bytes (> 10 MiB)
    raw_data = b"z" * (10_485_760 + 1)
    b64_data = base64.b64encode(raw_data).decode("ascii")

    envelope = {
        "kind": "Attachment",
        "payload": {
            "filename": "big.bin",
            "mime_type": "application/octet-stream",
            "content_base64": b64_data,
        },
    }
    status_code, body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body=envelope,
    )
    assert status_code == 422
    assert "exceeds maximum size limit" in body["detail"]


def test_post_envelope_attachment_exceeding_derived_base64_bound_rejected(client):
    app, _ = client
    # base64 length > ATTACHMENT_BASE64_MAX_BYTES (13,981,016)
    oversized_b64 = "A" * 13_981_020

    envelope = {
        "kind": "Attachment",
        "payload": {
            "filename": "big.bin",
            "mime_type": "application/octet-stream",
            "content_base64": oversized_b64,
        },
    }
    status_code, body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body=envelope,
    )
    assert status_code == 422
    assert "exceeds maximum allowed encoded size" in body["detail"]


def test_post_envelope_non_attachment_exceeding_1mb_rejected(client):
    app, _ = client
    # Sugar message exceeding 1MB
    status_code, body = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"text": "m" * (1024 * 1024 + 100)},
    )
    assert status_code == 422
    assert "exceeds maximum size limit of 1MB" in body["detail"]

    # Command exceeding 1MB
    status_code_cmd, _ = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"kind": "Command", "payload": {"text": "c" * (1024 * 1024 + 100)}},
    )
    assert status_code_cmd == 422

    # Unknown kind exceeding 1MB
    status_code_custom, _ = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"kind": "CustomKind", "payload": {"data": "u" * (1024 * 1024 + 100)}},
    )
    assert status_code_custom == 422


def test_post_envelope_unknown_kind_under_1mb_accepted(client, monkeypatch):
    app, _ = client
    sent = {}
    monkeypatch.setattr(api_module, "send", lambda _redis, **kwargs: sent.update(kwargs) or "stream-1")
    status_code, _ = request(
        app,
        "POST",
        "/agents/alice/envelopes",
        token="secret",
        body={"kind": "FutureKind", "payload": {"foo": "bar"}},
    )
    assert status_code == 202
    assert sent["kind"] == "FutureKind"


def test_post_envelope_attachment_schema_validation(client):
    app, _ = client

    # Payload not a dict
    for bad_payload in ["string", 123, [1, 2, 3]]:
        status_code, _ = request(
            app, "POST", "/agents/alice/envelopes", token="secret",
            body={"kind": "Attachment", "payload": bad_payload},
        )
        assert status_code == 422

    # Missing required keys
    valid_payload = {
        "filename": "a.txt",
        "mime_type": "text/plain",
        "content_base64": base64.b64encode(b"hello").decode(),
    }
    for required_key in ["filename", "mime_type", "content_base64"]:
        incomplete = {k: v for k, v in valid_payload.items() if k != required_key}
        status_code, _ = request(
            app, "POST", "/agents/alice/envelopes", token="secret",
            body={"kind": "Attachment", "payload": incomplete},
        )
        assert status_code == 422

    # Extra fields (closed schema)
    with_extra = dict(valid_payload, extra="forbidden")
    status_code, _ = request(
        app, "POST", "/agents/alice/envelopes", token="secret",
        body={"kind": "Attachment", "payload": with_extra},
    )
    assert status_code == 422

    # Non-string field types
    for bad_field in [{"filename": 123}, {"mime_type": True}, {"content_base64": None}, {"caption": 456}]:
        bad_types = dict(valid_payload, **bad_field)
        status_code, _ = request(
            app, "POST", "/agents/alice/envelopes", token="secret",
            body={"kind": "Attachment", "payload": bad_types},
        )
        assert status_code == 422


def test_post_envelope_attachment_filename_validation(client):
    app, _ = client
    b64 = base64.b64encode(b"test").decode()

    # Empty filename
    res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                     body={"kind": "Attachment", "payload": {"filename": "", "mime_type": "text/plain", "content_base64": b64}})
    assert res == 422

    # Filename > 255 UTF-8 bytes
    long_fn = "a" * 256
    res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                     body={"kind": "Attachment", "payload": {"filename": long_fn, "mime_type": "text/plain", "content_base64": b64}})
    assert res == 422

    # . and .. and path separators and control characters
    for invalid_fn in [".", "..", "dir/file.txt", "dir\\file.txt", "file\x00.txt", "file\n.txt", "file\x1f.txt", "file\x7f.txt"]:
        res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                         body={"kind": "Attachment", "payload": {"filename": invalid_fn, "mime_type": "text/plain", "content_base64": b64}})
        assert res == 422


def test_post_envelope_attachment_mime_type_validation(client):
    app, _ = client
    b64 = base64.b64encode(b"test").decode()

    invalids = [
        "", "image/*", "text/plain; charset=utf-8", "/png", "image/",
        "image/png ", " image/png", "image/png\n", "image/pñg", "a" * 256 + "/b",
    ]
    for invalid_mime in invalids:
        res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                         body={"kind": "Attachment", "payload": {"filename": "test.txt", "mime_type": invalid_mime, "content_base64": b64}})
        assert res == 422


def test_post_envelope_attachment_caption_validation(client):
    app, _ = client
    b64 = base64.b64encode(b"test").decode()

    # Caption > 65536 UTF-8 bytes
    long_caption = "c" * 65_537
    res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                     body={"kind": "Attachment", "payload": {"filename": "test.txt", "mime_type": "text/plain", "content_base64": b64, "caption": long_caption}})
    assert res == 422


def test_post_envelope_attachment_base64_strict_validation(client):
    app, _ = client

    invalids = [
        "AA AA",        # whitespace
        "AA\t==",       # whitespace
        "AA\r\n==",     # whitespace
        " AA==",        # leading whitespace
        "AA== ",        # trailing whitespace
        "AA_-",         # URL-safe chars
        "A===",         # invalid padding
        "=====",        # invalid padding
        "AAAAA",        # length not multiple of 4 / excess data
        "AA==\u200b",   # unicode whitespace/non-ascii
    ]
    for invalid_b64 in invalids:
        res, _ = request(app, "POST", "/agents/alice/envelopes", token="secret",
                         body={"kind": "Attachment", "payload": {"filename": "test.txt", "mime_type": "text/plain", "content_base64": invalid_b64}})
        assert res == 422


def test_post_envelope_attachment_unpaired_surrogates_rejected(client):
    app, _ = client
    b64 = base64.b64encode(b"test").decode()

    # Filename with unpaired surrogate
    res, body = request(app, "POST", "/agents/alice/envelopes", token="secret",
                        body={"kind": "Attachment", "payload": {"filename": "bad_\ud800_name.txt", "mime_type": "text/plain", "content_base64": b64}})
    assert res == 422
    assert "must be valid UTF-8" in body["detail"]

    # Caption with unpaired surrogate
    res, body = request(app, "POST", "/agents/alice/envelopes", token="secret",
                        body={"kind": "Attachment", "payload": {"filename": "test.txt", "mime_type": "text/plain", "content_base64": b64, "caption": "bad_\ud800_caption"}})
    assert res == 422
    assert "must be valid UTF-8" in body["detail"]


def test_restdoc_html_includes_attachment_and_qualified_notice(client):
    app, _ = client
    status_code, body = request(app, "GET", "/restdoc", token="secret")
    assert status_code == 200
    assert "Attachment" in body
    assert "The API server does NOT validate <code>kind</code> or <code>payload</code> (with the one named exception of <code>Attachment</code>" in body





