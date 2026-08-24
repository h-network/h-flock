from conftest import FakeRedis
import json
import pytest
from flock.bus import (
    prefix,
    build as build_envelope,
    encode,
    parse as parse_envelope,
    EnvelopeError,
    DeadLetter,
    send,
    receive,
    members,
    is_member,
)



def test_prefix_valid():
    assert prefix("acme", "hq") == "pod:acme:tenant:hq"
    assert prefix("acme", "hq", agent="alice") == "pod:acme:tenant:hq:agent:alice"
    assert prefix("acme", "hq", resource="roster") == "pod:acme:tenant:hq:roster"
    assert prefix("acme", "hq", agent="alice", resource="egress") == "pod:acme:tenant:hq:agent:alice:egress"
    assert prefix("acme", "hq", agent="alice", resource="tasks.todo") == "pod:acme:tenant:hq:agent:alice:tasks.todo"


def test_prefix_invalid():
    with pytest.raises(KeyError):
        prefix("pod", "hq")  # reserved word
    with pytest.raises(KeyError):
        prefix("acme", "tenant")  # reserved word
    with pytest.raises(KeyError):
        prefix("acme", "hq", agent="agent")  # reserved word
    with pytest.raises(KeyError):
        prefix("ACME", "hq")  # uppercase invalid


def test_envelope_build_and_parse():
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    assert env["v"] == 4
    assert env["l2"] == {"source": "alice", "destination": "bob"}
    assert env["l3"] == {
        "source": "default:default:alice",
        "destination": "default:default:bob",
    }
    assert env["kind"] == "Message"
    assert env["payload"] == {"text": "hello"}
    assert "stream_id" in env
    assert "correlation_id" in env
    assert "ts" in env

    raw = encode(env)
    parsed = parse_envelope(raw)
    assert parsed["stream_id"] == env["stream_id"]


def test_envelope_parse_invalid():
    with pytest.raises(EnvelopeError):
        parse_envelope("invalid json")
    with pytest.raises(EnvelopeError):
        parse_envelope(json.dumps({"v": 1, "kind": "Message"}))  # missing required fields


def test_send_and_receive(capsys):
    r = FakeRedis()
    stream_id = send(r, pod="acme", tenant="hq", source="alice", destination="bob", payload={"text": "hi"})
    assert stream_id is not None
    egress_key = prefix("acme", "hq", agent="alice", resource="egress")
    assert len(r.lists[egress_key]) == 1

    # Simulate switch moving egress -> ingress
    ingress_key = prefix("acme", "hq", agent="bob", resource="ingress")
    r.lists[ingress_key] = r.lists.pop(egress_key)

    opened = []

    def mock_opener(env):
        opened.append(env)

    receive(r, pod="acme", tenant="hq", agent="bob", openers={"Message": mock_opener}, timeout=1)
    assert len(opened) == 1
    assert opened[0]["l2"]["source"] == "alice"


def test_opener_dead_letter_is_terminal_and_never_opened(capsys):
    r = FakeRedis()
    envelope = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hi"})
    ingress_key = prefix("acme", "hq", agent="bob", resource="ingress")
    from flock.bus import encode
    r.rpush(ingress_key, encode(envelope))

    def reject(_envelope):
        raise DeadLetter("window_missing")

    receive(r, pod="acme", tenant="hq", agent="bob", openers={"Message": reject}, timeout=1)

    events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
    assert events == ["received", "dead_lettered"]
    dead_key = prefix("acme", "hq", agent="bob", resource="dead")
    assert len(r.lists[dead_key]) == 1


def test_roster():
    r = FakeRedis()
    roster_key = prefix("acme", "hq", resource="roster")
    r.sadd(roster_key, "alice", "bob")
    r.hset(roster_key, "alice", "tmux")
    r.hset(roster_key, "bob", "tmux")

    mem = members(r, pod="acme", tenant="hq")
    assert mem == {"alice", "bob"}

    assert is_member(r, pod="acme", tenant="hq", agent="alice") is True
    assert is_member(r, pod="acme", tenant="hq", agent="carol") is False
    assert r.hget(roster_key, "alice") == "tmux"
