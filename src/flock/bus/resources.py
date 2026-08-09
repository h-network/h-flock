"""Canonical classification and retirement policy for Redis resources."""

from .keys import prefix


AGENT_STATE_RESOURCES = frozenset(
    {
        "blocked",
        "launch",
        "profile",
        "paused",
        "inbox",
        "activity",
        "activity.offset",
        "alerted",
        "presence",
        "pending.verify",
    }
)

AGENT_DATA_RESOURCES = frozenset(
    {
        "ingress",
        "egress",
        "dead",
        "tasks.todo",
        "tasks.doing",
        "tasks.hold",
        "tasks.done",
    }
)

PER_AGENT_RESOURCES = AGENT_STATE_RESOURCES | AGENT_DATA_RESOURCES
TENANT_RESOURCES = frozenset({"roster", "lead", "window.log.offset", "delivering", "alerts"})
DYNAMIC_RESOURCE_PATTERNS = frozenset({"tasks.*"})


def purge_agent(r, *, pod: str, tenant: str, agent: str) -> None:
    """Remove identity state while retaining the agent's queues and board."""
    state_keys = [prefix(pod, tenant, agent=agent, resource=resource) for resource in sorted(AGENT_STATE_RESOURCES)]
    r.delete(*state_keys)
    r.hdel(prefix(pod, tenant, resource="delivering"), agent)
