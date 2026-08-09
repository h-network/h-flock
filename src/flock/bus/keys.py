"""The only constructor for Redis keys."""

import re

SEGMENT_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# "all" is the broadcast recipient (LLD-bus-and-router §3.1), so no agent may
# carry that name — it would be unaddressable.
RESERVED = {"pod", "tenant", "agent", "all"}

# ⚠ An all-digit name is unaddressable in tmux and is rejected for the same
# reason "all" is: it cannot be routed unambiguously.
#
# tmux resolves `session:2` as window *index* 2, not the window named "2".
# Measured: with windows [1:first, 2:second, 3:"2"], both `s:2` and the
# exact-name form `s:=2` resolve to `second`. So a message for an agent named
# "2" is pasted into whichever agent happens to sit at index 2 — silent
# delivery to the wrong recipient, with an honest `opened` record.
#
# Hyphens and digits are fine; `sme-2` resolves correctly. Only an all-digit
# name collides.
ALL_DIGITS = re.compile(r"^[0-9]+$")

_SEGMENT = SEGMENT_REGEX
_RESERVED = RESERVED


def _validate(value: str | None) -> str:
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value) or value in _RESERVED:
        raise KeyError(value)
    if ALL_DIGITS.fullmatch(value):
        raise KeyError(value)
    return value


def _validate_resource(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise KeyError(value)
    # Build 19 pins this underscore spelling as an inter-module contract. Keep
    # the one narrow exception here so callers still use the sole key
    # constructor rather than assembling it.
    if value == "pending_verify":
        return value
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
