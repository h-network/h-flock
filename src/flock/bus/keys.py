import re

SEGMENT_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RESERVED = {"pod", "tenant", "agent"}


def prefix(
    pod: str,
    tenant: str,
    agent: str | None = None,
    resource: str | None = None,
) -> str:
    """
    Build key: pod:<pod>:tenant:<tenant>[:agent:<agent>][:<resource>]
    Validates every segment against ^[a-z0-9][a-z0-9-]{0,62}$
    Rejects reserved words pod / tenant / agent
    Raises KeyError on anything invalid.
    """
    for name, val in [("pod", pod), ("tenant", tenant)]:
        if not val or not SEGMENT_REGEX.match(val) or val in RESERVED:
            raise KeyError(f"Invalid {name} segment: {val!r}")

    parts = [f"pod:{pod}:tenant:{tenant}"]

    if agent is not None:
        if not agent or not SEGMENT_REGEX.match(agent) or agent in RESERVED:
            raise KeyError(f"Invalid agent segment: {agent!r}")
        parts.append(f"agent:{agent}")

    if resource is not None:
        for sub in resource.split("."):
            if not sub or not SEGMENT_REGEX.match(sub):
                raise KeyError(f"Invalid resource segment: {resource!r}")
        parts.append(resource)

    return ":".join(parts)
