"""Atomic queue-admission primitives shared by transport services."""

from collections.abc import Sequence

from .keys import prefix


# Check every destination and append every copy in one Redis execution. This
# keeps unicast and broadcast admission all-or-none while ports concurrently
# consume ingress. Configuration and rejection policy belong to callers.
_ADMIT_INGRESS = """
-- flock ingress admission v1
local limit = tonumber(ARGV[1])
for index, key in ipairs(KEYS) do
    local depth = redis.call('LLEN', key)
    if depth >= limit then
        return {0, index, depth}
    end
end
local result = {1}
for _, key in ipairs(KEYS) do
    table.insert(result, redis.call('RPUSH', key, ARGV[2]))
end
return result
"""


def admit_ingress(
    r,
    *,
    pod: str,
    tenant: str,
    destinations: Sequence[str],
    raw: str | bytes,
    limit: int,
) -> tuple[bool, str | None, int | None]:
    """Atomically append to every ingress, or report the first full queue."""
    if not destinations:
        raise ValueError("destinations must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")

    destination_names = tuple(destinations)
    keys = [
        prefix(pod, tenant, destination, "ingress")
        for destination in destination_names
    ]
    result = r.eval(_ADMIT_INGRESS, len(keys), *keys, limit, raw)
    if bool(result[0]):
        return True, None, None

    rejected_index = int(result[1]) - 1
    return False, destination_names[rejected_index], int(result[2])
