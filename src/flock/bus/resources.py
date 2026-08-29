"""Canonical classification and retirement policy for Redis resources."""

from .keys import prefix


AGENT_STATE_RESOURCES = frozenset(
    {
        "blocked",
        "launch",
        "window.cause",
        "profile",
        "provider",
        "paused",
        "activity",
        "activity.offset",
        "alerted",
        "doing.alerted",
        "todo.alerted",
        "hold.alerted",
        "unreplied",
        "unreplied.alerted",
        "acks",
        "presence",
        "pending.verify",
        "delivery.markers",
        "usage.requests",
        "usage.attributed",
        "tags",
        "resume",
        "hmac-keys",
    }
)

DURABLE_DATA_RESOURCES = frozenset(
    {
        "inbox",
        "tasks.todo",
        "tasks.doing",
        "tasks.hold",
        "tasks.done",
    }
)

TRANSPORT_QUEUE_RESOURCES = frozenset(
    {
        "ingress",
        "egress",
        "dead",
    }
)

AGENT_DATA_RESOURCES = DURABLE_DATA_RESOURCES | TRANSPORT_QUEUE_RESOURCES

PER_AGENT_RESOURCES = AGENT_STATE_RESOURCES | AGENT_DATA_RESOURCES
TENANT_RESOURCES = frozenset(
    {"roster", "accounts", "lead", "window.log.offset", "delivering", "alerts", "credential.alerted", "usage"}
)
DYNAMIC_RESOURCE_PATTERNS = frozenset({"tasks.*"})


def purge_agent(r, *, pod: str, tenant: str, agent: str) -> None:
    """Remove identity state while retaining the agent's queues and board."""
    state_keys = [prefix(pod, tenant, agent=agent, resource=resource) for resource in sorted(AGENT_STATE_RESOURCES)]
    r.delete(*state_keys)
    r.hdel(prefix(pod, tenant, resource="delivering"), agent)


def purge_transport(r, *, pod: str, tenant: str) -> int:
    """Purge ephemeral transport queues and delivery locks at boot, preserving durable boards and streams."""
    keys_to_delete = set()
    pattern = f"pod:{pod}:tenant:{tenant}:agent:*:*"
    if hasattr(r, "scan_iter"):
        matched = r.scan_iter(match=pattern)
    elif hasattr(r, "keys"):
        matched = r.keys(pattern)
    else:
        matched = []

    for key in matched:
        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        parts = key_str.split(":")
        if len(parts) >= 7 and parts[6] in TRANSPORT_QUEUE_RESOURCES:
            keys_to_delete.add(key)

    delivering_key = prefix(pod, tenant, resource="delivering")
    keys_to_delete.add(delivering_key)

    if keys_to_delete:
        return r.delete(*keys_to_delete)
    return 0
