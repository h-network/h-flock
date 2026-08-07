"""Read-only access to the tenant roster."""

from .keys import prefix


def members(r, *, pod: str, tenant: str) -> set[str]:
    values = r.smembers(prefix(pod, tenant, resource="roster"))
    return {value.decode() if isinstance(value, bytes) else value for value in values}


def is_member(r, *, pod: str, tenant: str, agent: str) -> bool:
    return bool(r.sismember(prefix(pod, tenant, resource="roster"), agent))
