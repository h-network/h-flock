"""Canonical configured-account discovery shared by client and fabric."""

from .keys import prefix


def available_profiles(r, *, pod: str, tenant: str) -> tuple[str, ...] | None:
    """Return configured accounts, or None when an older tenant has no record."""
    values = r.smembers(prefix(pod, tenant, resource="accounts"))
    if not values:
        # Compatibility is deliberately permissive, like absent bus policy:
        # tenants created before the canonical key existed must keep working.
        return None
    return tuple(sorted(value.decode() if isinstance(value, bytes) else str(value) for value in values))
