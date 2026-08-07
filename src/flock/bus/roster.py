from .keys import prefix


def members(r, *, pod: str, tenant: str) -> set[str]:
    roster_key = prefix(pod, tenant, resource="roster")
    res = r.smembers(roster_key)
    return {m.decode("utf-8") if isinstance(m, bytes) else m for m in res}


def is_member(r, *, pod: str, tenant: str, agent: str) -> bool:
    roster_key = prefix(pod, tenant, resource="roster")
    return bool(r.sismember(roster_key, agent))
