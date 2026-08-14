"""Port-side import/export tag policy."""

import json

from .envelope import EnvelopeError
from .keys import prefix


def tags_key(pod: str, tenant: str, agent: str) -> str:
    """Companion key for one participant's policy, separate from the roster."""
    return prefix(pod, tenant, agent=agent, resource="tags")


def _read_tags(r, *, pod: str, tenant: str, agent: str, side: str) -> set[str] | None:
    raw = r.hget(tags_key(pod, tenant, agent), side)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        values = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise EnvelopeError(f"invalid {side} tags for {agent!r}") from exc
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise EnvelopeError(f"invalid {side} tags for {agent!r}")
    return set(values)


def allows(r, *, pod: str, tenant: str, source: str, destination: str) -> bool:
    """Permit absent policy; otherwise require source export ∩ destination import."""
    export = _read_tags(r, pod=pod, tenant=tenant, agent=source, side="export")
    imports = _read_tags(r, pod=pod, tenant=tenant, agent=destination, side="import")
    if not export or not imports:
        return True
    return bool(export & imports)


def require_allowed(r, *, pod: str, tenant: str, source: str, destination: str) -> None:
    if not allows(r, pod=pod, tenant=tenant, source=source, destination=destination):
        raise EnvelopeError(
            f"policy denied {source!r} -> {destination!r}: no shared export/import tag"
        )
