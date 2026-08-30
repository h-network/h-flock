"""Unit tests for flock.port delivery registry and decoupled dispatch."""

import json
import pytest
from unittest.mock import MagicMock, patch

from conftest import FakeRespRedis
from flock.bus import build as build_envelope, encode, prefix
from flock.port.deliver import deliver_api, deliver_one, deliver_unroutable
from flock.tmux.deliver import deliver_tmux
from flock.port.registry import (
    get_delivery_handler,
    register_port_type,
    reset_registry,
    unregister_port_type,
)
from flock.port import registry as port_registry


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


def test_registry_default_handlers():
    tmux_handler = get_delivery_handler("tmux")
    assert tmux_handler is deliver_tmux

    api_handler = get_delivery_handler("api")
    assert api_handler is deliver_api

    from flock.control.runner import deliver_one as control_deliver_one
    control_handler = get_delivery_handler("control")
    assert control_handler is control_deliver_one

    assert get_delivery_handler("unknown_type") is None
    assert get_delivery_handler("") is None


def test_register_and_dispatch_custom_callable():
    mock_handler = MagicMock()
    register_port_type("custom_lane", mock_handler)

    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "worker-x", "custom_lane")

    deliver_one(r, pod="acme", tenant="hq", agent="worker-x")

    mock_handler.assert_called_once_with(
        r=r,
        pod="acme",
        tenant="hq",
        agent="worker-x",
    )


def test_register_and_resolve_lazy_import():
    spec = ("flock.port.deliver", "deliver_api")
    register_port_type("lazy_port", spec)
    assert port_registry._PORT_REGISTRY["lazy_port"] == spec
    handler = get_delivery_handler("lazy_port")
    assert handler is deliver_api


def test_register_rejects_unresolvable_lazy_import():
    with pytest.raises(ValueError, match="cannot resolve nonexistent.module.missing_func"):
        register_port_type("broken_port", ("nonexistent.module", "missing_func"))


def test_register_rejects_non_callable_handler():
    with pytest.raises(ValueError, match="handler must be callable"):
        register_port_type("broken_port", object())


def test_register_rejects_lazy_import_of_non_callable_attribute():
    with pytest.raises(ValueError, match="handler must be callable"):
        register_port_type("broken_port", ("flock.port.registry", "_DEFAULT_REGISTRY"))


def test_lazy_non_callable_handler_returns_none(caplog):
    port_registry._PORT_REGISTRY["broken_port"] = ("flock.port.registry", "_DEFAULT_REGISTRY")

    assert get_delivery_handler("broken_port") is None
    assert "is not callable" in caplog.text


def test_deliver_one_dispatches_tmux(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "bob", "tmux")

    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello tmux"})
    ingress_key = prefix("acme", "hq", "bob", "ingress")
    r.rpush(ingress_key, encode(env))

    with patch("flock.tmux.openers.list_windows", return_value={"bob"}), \
         patch("flock.tmux.ops.run_tmux", return_value=(0, "", "")):
        deliver_one(r, pod="acme", tenant="hq", agent="bob")

    assert len(r.lists.get(ingress_key, [])) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [rec["event"] for rec in records]
    assert "received" in events
    assert "opened" in events


@pytest.mark.parametrize("session_env", [None, ""])
def test_tmux_handler_resolves_empty_or_absent_session_at_its_edge(monkeypatch, session_env):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "bob", "tmux")
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    r.rpush(prefix("acme", "hq", "bob", "ingress"), encode(env))

    if session_env is None:
        monkeypatch.delenv("TMUX_SESSION", raising=False)
    else:
        monkeypatch.setenv("TMUX_SESSION", session_env)
    monkeypatch.setenv("TMUX_SOCKET", "/tmp/flock-test.sock")

    with patch("flock.tmux.deliver.messages_opener") as mock_opener:
        deliver_one(r, pod="acme", tenant="hq", agent="bob")

    assert mock_opener.call_args.kwargs["session_name"] == "hq"
    assert mock_opener.call_args.kwargs["socket"] == "/tmp/flock-test.sock"


def test_tmux_handler_resolves_configured_session_at_its_edge(monkeypatch):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "bob", "tmux")
    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})
    r.rpush(prefix("acme", "hq", "bob", "ingress"), encode(env))
    monkeypatch.setenv("TMUX_SESSION", "custom-session")
    monkeypatch.delenv("TMUX_SOCKET", raising=False)

    with patch("flock.tmux.deliver.messages_opener") as mock_opener:
        deliver_one(r, pod="acme", tenant="hq", agent="bob")

    assert mock_opener.call_args.kwargs["session_name"] == "custom-session"
    assert mock_opener.call_args.kwargs["socket"] is None


def test_deliver_one_dispatches_api(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "telegram", "api")

    env = build_envelope(kind="Message", source="architect", destination="telegram", payload={"text": "status"})
    ingress_key = prefix("acme", "hq", "telegram", "ingress")
    inbox_key = prefix("acme", "hq", agent="telegram", resource="inbox")
    r.rpush(ingress_key, encode(env))

    deliver_one(r, pod="acme", tenant="hq", agent="telegram")

    assert len(r.lists.get(ingress_key, [])) == 0
    assert len(r.streams.get(inbox_key, [])) == 1

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [rec["event"] for rec in records]
    assert "received" in events
    assert "opened" in events


def test_deliver_one_dispatches_control():
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "host", "control")

    mock_control = MagicMock()
    with patch("flock.control.runner.deliver_one", mock_control):
        deliver_one(r, pod="acme", tenant="hq", agent="host")

    mock_control.assert_called_once_with(
        r=r,
        pod="acme",
        tenant="hq",
        agent="host",
    )


def test_deliver_one_unroutable_dead_letters(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "ghost", "unsupported_device")

    env = build_envelope(kind="Message", source="architect", destination="ghost", payload={"text": "lost"})
    ingress_key = prefix("acme", "hq", "ghost", "ingress")
    dead_key = prefix("acme", "hq", "ghost", "dead")
    r.rpush(ingress_key, encode(env))

    deliver_one(r, pod="acme", tenant="hq", agent="ghost")

    assert len(r.lists.get(ingress_key, [])) == 0
    assert len(r.lists.get(dead_key, [])) == 1

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [rec["event"] for rec in records]
    assert "received" in events
    assert "dead_lettered" in events
    assert records[1]["reason"] == "unroutable port_type: 'unsupported_device'"
