"""Read-only access to the tenant roster."""

from .keys import prefix


def members(r, *, pod: str, tenant: str) -> set[str]:
    try:
        keys = r.hkeys(prefix(pod, tenant, resource="roster"))
        return {k.decode() if isinstance(k, bytes) else k for k in keys}
    except Exception:
        # Fallback for set-based roster in older unit tests
        values = r.smembers(prefix(pod, tenant, resource="roster"))
        return {value.decode() if isinstance(value, bytes) else value for value in values}


def is_member(r, *, pod: str, tenant: str, agent: str) -> bool:
    try:
        return bool(r.hexists(prefix(pod, tenant, resource="roster"), agent))
    except Exception:
        return bool(r.sismember(prefix(pod, tenant, resource="roster"), agent))


def vab(r, *, pod: str, tenant: str, agent: str) -> str | None:
    res = r.hget(prefix(pod, tenant, resource="roster"), agent)
    if res is None:
        return None
    return res.decode() if isinstance(res, bytes) else res
