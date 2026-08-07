"""The only constructor for Redis keys."""

import re

_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_RESERVED = {"pod", "tenant", "agent"}


def _validate(value: str | None) -> str:
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value) or value in _RESERVED:
        raise KeyError(value)
    return value


def _validate_resource(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise KeyError(value)
    for segment in value.split("."):
        _validate(segment)
    return value


def _validate_agent(value: str | None) -> str:
    value = _validate(value)
    if value == "all":
        raise KeyError(value)
    return value


def prefix(
    pod: str,
    tenant: str,
    agent: str | None = None,
    resource: str | None = None,
) -> str:
    """Build a structurally tenant-scoped key, validating every value segment."""
    parts = ["pod", _validate(pod), "tenant", _validate(tenant)]
    if agent is not None:
        parts.extend(("agent", _validate_agent(agent)))
    if resource is not None:
        parts.append(_validate_resource(resource))
    return ":".join(parts)
