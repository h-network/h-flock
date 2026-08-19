"""Store health classification shared by the long-lived loops."""

import redis


def classify_store_error(exc: BaseException) -> str:
    if isinstance(exc, (redis.ConnectionError, redis.TimeoutError, OSError)):
        return "unreachable"
    if isinstance(exc, redis.ResponseError):
        text = str(exc).upper()
        for prefix, classification in (
            ("MISCONF", "misconfigured"),
            ("OOM", "out_of_memory"),
            ("READONLY", "read_only"),
            ("NOAUTH", "authentication"),
            ("NOPERM", "authorization"),
            ("BUSY", "busy"),
        ):
            if text.startswith(prefix) or prefix in text:
                return classification
        return "response_error"
    return type(exc).__name__


def verify_store(r, *, require_noeviction: bool = True) -> None:
    r.ping()
    if not require_noeviction:
        return
    policy = r.config_get("maxmemory-policy").get("maxmemory-policy")
    if isinstance(policy, bytes):
        policy = policy.decode()
    if policy != "noeviction":
        raise StoreConfigurationError(
            f"maxmemory-policy must be 'noeviction', got {policy!r}"
        )


class StoreConfigurationError(RuntimeError):
    """A reachable store configuration under which serving would lose data."""
