import ast
import json
from datetime import datetime, timezone
from pathlib import Path

from flock.bus import (
    AGENT_DATA_RESOURCES,
    AGENT_STATE_RESOURCES,
    DYNAMIC_RESOURCE_PATTERNS,
    PER_AGENT_RESOURCES,
    TENANT_RESOURCES,
    prefix,
)
from flock.control import start_agent, stop_agent
from flock.router.presence import PresenceSampler


def _resource_expression(call: ast.Call):
    for keyword in call.keywords:
        if keyword.arg == "resource":
            return keyword.value
    return call.args[3] if len(call.args) >= 4 else None


def _resource_literal(expression) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.JoinedStr):
        parts = []
        for value in expression.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("*")
            else:
                return None
        return "".join(parts)
    return None


def _is_prefix_call(node: ast.Call) -> bool:
    return (isinstance(node.func, ast.Name) and node.func.id == "prefix") or (
        isinstance(node.func, ast.Attribute) and node.func.attr == "prefix"
    )


def _source_resources() -> set[str]:
    resources = set()
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_prefix_call(node):
                continue
            literal = _resource_literal(_resource_expression(node))
            if literal is not None:
                resources.add(literal)
    return resources


def test_every_source_resource_literal_has_an_explicit_lifecycle_classification():
    assert AGENT_STATE_RESOURCES.isdisjoint(AGENT_DATA_RESOURCES)
    assert PER_AGENT_RESOURCES == AGENT_STATE_RESOURCES | AGENT_DATA_RESOURCES
    classified = PER_AGENT_RESOURCES | TENANT_RESOURCES | DYNAMIC_RESOURCE_PATTERNS
    unclassified = _source_resources() - classified
    assert unclassified == set(), f"classify new Redis resources: {sorted(unclassified)}"


def test_resource_scanner_catches_keyword_positional_and_dynamic_literals():
    tree = ast.parse(
        "prefix(p, t, resource='new-state')\n"
        "prefix(p, t, a, 'new-data')\n"
        "prefix(p, t, resource=f'tasks.{state}')\n"
    )
    found = {
        _resource_literal(_resource_expression(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert found == {"new-state", "new-data", "tasks.*"}


class StatefulRedis:
    def __init__(self):
        self.values = {}
        self.hashes = {}
        self.streams = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.streams.pop(key, None)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        target = self.hashes.setdefault(key, {})
        if mapping is not None:
            target.update(mapping)
        else:
            target[field] = value

    def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def xrevrange(self, key, max="+", min="-", count=None):
        return list(reversed(self.streams.get(key, [])))[:count]


def test_retire_working_agent_then_rehire_same_name_reads_idle_and_keeps_data():
    r = StatefulRedis()
    agent = "sme-2"
    roster = prefix("acme", "hq", resource="roster")
    r.hashes[roster] = {agent: "tmux"}
    r.values[prefix("acme", "hq", agent, "launch")] = "claude"
    r.hashes[prefix("acme", "hq", agent, "presence")] = {
        "state": "working",
        "since": "2026-08-09T12:00:00.000Z",
        "last_activity": "2026-08-09T12:00:00.000Z",
    }
    activity = prefix("acme", "hq", agent, "activity")
    r.streams[activity] = [
        (
            "1-0",
            {"event": json.dumps({"v": 1, "agent": agent, "ts": "2026-08-09T12:00:00Z", "kind": "tool"})},
        )
    ]
    delivering = prefix("acme", "hq", resource="delivering")
    r.hashes[delivering] = {agent: "busy"}
    retained = {
        prefix("acme", "hq", agent, "ingress"),
        prefix("acme", "hq", agent, "tasks.todo"),
    }
    for key in retained:
        r.values[key] = "work"

    stop_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent}},
        kill_window=lambda name: None,
    )
    assert agent not in r.hashes[delivering]
    for resource in AGENT_STATE_RESOURCES:
        key = prefix("acme", "hq", agent, resource)
        assert key not in r.values
        assert key not in r.hashes
        assert key not in r.streams
    assert all(key in r.values for key in retained)

    start_agent(
        r,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent, "cli": "claude"}},
        replace_window=lambda name: None,
    )
    PresenceSampler(r, pod="acme", tenant="hq").poll(
        {agent}, now=datetime(2026, 8, 9, 12, 1, 0, tzinfo=timezone.utc)
    )
    presence = r.hashes[prefix("acme", "hq", agent, "presence")]
    assert presence == {
        "state": "idle",
        "since": "2026-08-09T12:01:00.000Z",
        "last_activity": "",
    }
