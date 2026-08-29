"""Unit tests for flock.port delivery registry and decoupled dispatch."""

import json
import pytest
from unittest.mock import MagicMock, patch

from conftest import FakeRespRedis
from flock.bus import build as build_envelope, encode, prefix
from flock.port.deliver import deliver_api, deliver_one, deliver_tmux, deliver_unroutable
from flock.port.registry import (
    get_delivery_handler,
    register_port_type,
    reset_registry,
    unregister_port_type,
)


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

    deliver_one(r, pod="acme", tenant="hq", agent="worker-x", session_name="hq")

    mock_handler.assert_called_once_with(
        r=r,
        pod="acme",
        tenant="hq",
        agent="worker-x",
        session_name="hq",
        socket=None,
    )


def test_register_and_resolve_lazy_import():
    register_port_type("lazy_port", ("flock.port.deliver", "deliver_api"))
    handler = get_delivery_handler("lazy_port")
    assert handler is deliver_api


def test_lazy_import_failure_returns_none(caplog):
    register_port_type("broken_port", ("nonexistent.module", "missing_func"))
    handler = get_delivery_handler("broken_port")
    assert handler is None


def test_deliver_one_dispatches_tmux(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "bob", "tmux")

    env = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello tmux"})
    ingress_key = prefix("acme", "hq", "bob", "ingress")
    r.rpush(ingress_key, encode(env))

    with patch("flock.port.openers.list_windows", return_value={"bob"}), \
         patch("flock.tmux.ops.run_tmux", return_value=(0, "", "")):
        deliver_one(r, pod="acme", tenant="hq", agent="bob", session_name="hq")

    assert len(r.lists.get(ingress_key, [])) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [rec["event"] for rec in records]
    assert "received" in events
    assert "opened" in events


def test_deliver_one_dispatches_api(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "telegram", "api")

    env = build_envelope(kind="Message", source="architect", destination="telegram", payload={"text": "status"})
    ingress_key = prefix("acme", "hq", "telegram", "ingress")
    inbox_key = prefix("acme", "hq", agent="telegram", resource="inbox")
    r.rpush(ingress_key, encode(env))

    deliver_one(r, pod="acme", tenant="hq", agent="telegram", session_name="hq")

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
        deliver_one(r, pod="acme", tenant="hq", agent="host", session_name="hq")

    mock_control.assert_called_once_with(
        r=r,
        pod="acme",
        tenant="hq",
        agent="host",
        session_name="hq",
        socket=None,
    )


def test_deliver_one_unroutable_dead_letters(capsys):
    r = FakeRespRedis()
    r.hset("pod:acme:tenant:hq:roster", "ghost", "unsupported_device")

    env = build_envelope(kind="Message", source="architect", destination="ghost", payload={"text": "lost"})
    ingress_key = prefix("acme", "hq", "ghost", "ingress")
    dead_key = prefix("acme", "hq", "ghost", "dead")
    r.rpush(ingress_key, encode(env))

    deliver_one(r, pod="acme", tenant="hq", agent="ghost", session_name="hq")

    assert len(r.lists.get(ingress_key, [])) == 0
    assert len(r.lists.get(dead_key, [])) == 1

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [rec["event"] for rec in records]
    assert "received" in events
    assert "dead_lettered" in events
    assert records[1]["reason"] == "unroutable port_type: 'unsupported_device'"
