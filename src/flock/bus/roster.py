"""Read-only access to the tenant roster."""

from .keys import prefix


def members(r, *, pod: str, tenant: str) -> set[str]:
    values = r.hkeys(prefix(pod, tenant, resource="roster"))
    return {value.decode() if isinstance(value, bytes) else value for value in values}


def is_member(r, *, pod: str, tenant: str, agent: str) -> bool:
    return bool(r.hexists(prefix(pod, tenant, resource="roster"), agent))


def vab(r, *, pod: str, tenant: str, agent: str) -> str | None:
    value = r.hget(prefix(pod, tenant, resource="roster"), agent)
    if isinstance(value, bytes):
        return value.decode()
    return value
