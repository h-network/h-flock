"""Name derivation for OpenShell resources.

Both sandbox names and workspace names are capped at 19 characters by the
real gateway — confirmed directly (`INVALID_ARGUMENT: name exceeds maximum
length (20 > 19)` for a sandbox, `(24 > 19)` for a workspace), not assumed
from documentation. Flock agent names allow up to 63
(`SEGMENT_REGEX` in `src/flock/bus/keys.py`), and a `pod:tenant` pair can
easily exceed 19 too, so anything derived from either needs shortening.

The real (untruncated) name always belongs in a sandbox's `labels`
(`SandboxRef.labels`, which has no length limit observed) — this module
only produces the value OpenShell requires *as* `name`.
"""

from __future__ import annotations

import hashlib

MAX_NAME_LENGTH = 19


def short_name(value: str, *, max_length: int = MAX_NAME_LENGTH) -> str:
    """Deterministically shorten `value` to fit `max_length`.

    Pure function of `value` alone, so callers never need to persist the
    result to reconstruct it later — recompute it wherever it's needed.
    Values already within the limit pass through unchanged.
    """
    if len(value) <= max_length:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]
    prefix_length = max_length - len(digest) - 1
    return f"{value[:prefix_length]}-{digest}"


def sandbox_name(agent: str) -> str:
    return short_name(agent)


def workspace_name(pod: str, tenant: str) -> str:
    return short_name(f"{pod}-{tenant}")
