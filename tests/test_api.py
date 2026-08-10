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
        self.streams = {}
        self.hashes = {}
        self.roster = {b"bob": b"tmux", b"alice": b"tmux", b"telegram": b"api", b"host": b"tmux", b"sme-2": b"tmux"}

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def llen(self, key):
        return self.lengths.get(key, 0)

    def lrange(self, key, start, end):
        assert (start, end) == (0, -1)
        return self.lists.get(key, [])

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value.encode() if isinstance(value, str) else value)
        return len(self.lists[key])

    def pipeline(self, transaction=False):
        assert transaction is False
        return FakePipeline(self)

    def hexists(self, key, field):
        f = field.encode() if isinstance(field, str) else field
        return f in self.roster

    def hget(self, key, field):
        f = field.encode() if isinstance(field, str) else field
        return self.roster.get(f)

    def hkeys(self, key):
        return list(self.roster.keys())

    def xrange(self, name, min="-", max="+", count=None):
        entries = self.streams.get(name, [])
        result = []
        exclusive = False
        min_str = min
        if isinstance(min_str, bytes):
            min_str = min_str.decode()
        if isinstance(min_str, str) and min_str.startswith("("):
            exclusive = True
            min_str = min_str[1:]

        for entry_id, fields in entries:
            eid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            if min_str != "-":
                if exclusive and eid <= min_str:
                    continue
                if not exclusive and eid < min_str:
                    continue
            result.append((entry_id, fields))
            if count and len(result) >= count:
                break
        return result


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
    assert sent["producer"] == "telegram"
    assert sent["recipient"] == "alice"
    assert sent["payload"] == {"text": "hello"}


def test_post_envelope_with_invalid_as_client_rejected(client):
    app, _ = client
    # bob has vab "tmux" (not "api")
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


def test_get_messages_for_api_client(client):
    app, redis = client
    env = {
        "v": 1,
        "producer": "alice",
        "recipient": "telegram",
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
                "producer": "alice",
                "recipient": "telegram",
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
    env1 = {"v": 1, "producer": "alice", "recipient": "telegram", "kind": "Message", "payload": {"text": "msg1"}}
    env2 = {"v": 1, "producer": "bob", "recipient": "telegram", "kind": "Message", "payload": {"text": "msg2"}}
    inbox_key = "pod:test:tenant:office:agent:telegram:inbox"
    redis.streams[inbox_key] = [
        (b"1000-0", {b"envelope": json.dumps(env1).encode()}),
        (b"1001-0", {b"envelope": json.dumps(env2).encode()}),
    ]

    status_code, body = request(app, "GET", "/agents/telegram/messages?after=1000-0", token="secret")
    assert status_code == 200
    assert len(body["messages"]) == 1
    assert body["messages"][0]["cursor"] == "1001-0"
    assert body["messages"][0]["producer"] == "bob"
    assert body["next_cursor"] == "1001-0"


def test_get_messages_non_api_agent_returns_404(client):
    app, _ = client
    # bob is vab "tmux", so GET /agents/bob/messages should return 404
    status_code, _ = request(app, "GET", "/agents/bob/messages", token="secret")
    assert status_code == 404


def test_hyphenated_agent_names_with_digits(client):
    app, redis = client
    # Set up sme-2 in roster as api client
    redis.roster[b"sme-2"] = b"api"

    # 1. Queue depths for sme-2
    status_code, body = request(app, "GET", "/agents/sme-2", token="secret")
    assert status_code == 200
    assert body == {
        "agent": "sme-2",
        "vab": "api",
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
    env = {"v": 1, "producer": "architect", "recipient": "sme-2", "kind": "Message", "payload": {"text": "task for sme-2"}}
    redis.streams[inbox_key] = [(b"2000-0", {b"envelope": json.dumps(env).encode()})]
    status_code, body = request(app, "GET", "/agents/sme-2/messages", token="secret")
    assert status_code == 200
    assert body["agent"] == "sme-2"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["recipient"] == "sme-2"


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
        "vab": "tmux",
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
    assert body["vab"] == "tmux"
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






