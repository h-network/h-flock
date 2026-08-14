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
from flock.switch.presence import PresenceSampler


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
        count = 0
        for key in keys:
            if key in self.values or key in self.hashes or key in self.streams:
                count += 1
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.streams.pop(key, None)
        return count


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

    def keys(self, pattern="*"):
        import fnmatch
        all_keys = set(self.values.keys()) | set(self.hashes.keys()) | set(self.streams.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]

    def scan_iter(self, match="*"):
        return iter(self.keys(match))



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


def test_durable_and_transport_resources_partition_agent_data():
    from flock.bus import DURABLE_DATA_RESOURCES, TRANSPORT_QUEUE_RESOURCES
    assert DURABLE_DATA_RESOURCES.isdisjoint(TRANSPORT_QUEUE_RESOURCES)
    assert AGENT_DATA_RESOURCES == DURABLE_DATA_RESOURCES | TRANSPORT_QUEUE_RESOURCES


def test_purge_transport_deletes_queues_and_delivering_retains_boards_and_streams():
    from flock.bus import purge_transport
    r = StatefulRedis()
    agent = "architect"

    # Durable resources
    durable_keys = {
        prefix("acme", "hq", agent, "tasks.todo"): "ticket-1",
        prefix("acme", "hq", agent, "tasks.doing"): "ticket-2",
        prefix("acme", "hq", agent, "tasks.hold"): "ticket-3",
        prefix("acme", "hq", agent, "tasks.done"): "ticket-4",
        prefix("acme", "hq", agent, "tags"): "tags-data",
    }
    for k, v in durable_keys.items():
        r.values[k] = v

    r.streams[prefix("acme", "hq", agent, "inbox")] = [("1-0", {"envelope": "msg"})]
    r.streams[prefix("acme", "hq", agent, "activity")] = [("2-0", {"event": "tool"})]
    r.streams[prefix("acme", "hq", resource="alerts")] = [("3-0", {"event": "alert"})]

    # Ephemeral transport resources
    ephemeral_keys = {
        prefix("acme", "hq", agent, "ingress"): "queued-inbound",
        prefix("acme", "hq", agent, "egress"): "queued-outbound",
        prefix("acme", "hq", agent, "dead"): "dead-letter",
        prefix("acme", "hq", resource="delivering"): "lock",
    }
    for k, v in ephemeral_keys.items():
        r.values[k] = v

    deleted_count = purge_transport(r, pod="acme", tenant="hq")
    assert deleted_count == 4

    # Ephemeral queues must be gone
    for k in ephemeral_keys:
        assert k not in r.values
        assert k not in r.hashes

    # Durable state must survive
    for k, v in durable_keys.items():
        assert r.values.get(k) == v
    assert prefix("acme", "hq", agent, "inbox") in r.streams
    assert prefix("acme", "hq", agent, "activity") in r.streams
    assert prefix("acme", "hq", resource="alerts") in r.streams


def test_stale_v1_envelope_on_unpurged_ingress_is_rejected_and_dead_lettered():
    """Negative control: if boot purge fails, a stale v1 frame is rejected and dead-lettered."""
    from flock.bus.doors import receive

    class ListRedis:
        def __init__(self):
            self.lists = {}

        def blpop(self, key, timeout=0):
            items = self.lists.get(key, [])
            if items:
                return (key, items.pop(0))
            return None

        def lpop(self, key):
            items = self.lists.get(key, [])
            if items:
                return items.pop(0)
            return None

        def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)
            return len(self.lists[key])

    r = ListRedis()
    agent = "architect"
    ingress_key = prefix("acme", "hq", agent, "ingress")
    dead_key = prefix("acme", "hq", agent, "dead")

    # Stale v1 flat envelope lingering on unpurged queue
    v1_raw = json.dumps({"v": 1, "source": "sme-2", "destination": "architect", "kind": "Message", "payload": {"text": "stale"}})
    r.rpush(ingress_key, v1_raw)

    opened = []
    receive(
        r,
        pod="acme",
        tenant="hq",
        agent=agent,
        openers={"Message": lambda env: opened.append(env)},
        timeout=1,
        blocking=False,
    )

    # Must NOT have opened stale v1 frame
    assert len(opened) == 0
    # Must have moved raw v1 envelope to dead letters
    assert len(r.lists.get(dead_key, [])) == 1
    assert r.lists[dead_key][0] == v1_raw

