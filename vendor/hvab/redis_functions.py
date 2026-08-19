"""Admin-loaded Redis Functions used by the data-plane principals.

Every accessed key is supplied in ``KEYS``. No function constructs a key from
``ARGV``: Redis 7.4.2 enforces the caller's ACL for dynamic ``redis.call`` too,
but declaring every key lets ACL reject a forbidden call at the engine gate.
"""


LIBRARY = r"""#!lua name=hvab
local function number(value)
    local parsed = tonumber(value)
    if parsed == nil then
        error('invalid integer argument')
    end
    return parsed
end

redis.register_function('hvab_admit', function(keys, args)
    local ingress = keys[1]
    local bytes_key = keys[2]
    local meta = keys[3]
    local packet = args[1]
    local port = args[2]
    local expected_generation = args[3]
    local limit = number(args[4])
    local hint_channel = args[5]

    if redis.call('HGET', meta, 'state') ~= 'active' or
       redis.call('HGET', meta, 'generation') ~= expected_generation then
        return {'DETACHED'}
    end
    local used = number(redis.call('GET', bytes_key) or '0')
    if used + string.len(packet) > limit then
        return {'FULL', tostring(used)}
    end
    redis.call('RPUSH', ingress, packet)
    redis.call('INCRBY', bytes_key, string.len(packet))
    -- The channel attests the port. The body is deliberately content-free so
    -- no consumer can mistake a caller-supplied claim for provenance.
    local subscribers = redis.call('PUBLISH', hint_channel, '1')
    return {'OK', tostring(used + string.len(packet)), tostring(subscribers)}
end)

redis.register_function('hvab_pop_ingress', function(keys, args)
    local ingress = keys[1]
    local bytes_key = keys[2]
    local packet = redis.call('LPOP', ingress)
    if not packet then
        return {false, '0'}
    end
    local remaining_bytes = redis.call('DECRBY', bytes_key, string.len(packet))
    if remaining_bytes < 0 then
        redis.call('SET', bytes_key, '0')
        remaining_bytes = 0
    end
    return {packet, tostring(remaining_bytes)}
end)

redis.register_function('hvab_enqueue_egress', function(keys, args)
    local egress = keys[1]
    local bytes_key = keys[2]
    local meta = keys[3]
    local packet = args[1]
    local expected_generation = args[2]
    local limit = number(args[3])

    if redis.call('HGET', meta, 'state') ~= 'active' or
       redis.call('HGET', meta, 'generation') ~= expected_generation then
        return {'DETACHED'}
    end
    local used = number(redis.call('GET', bytes_key) or '0')
    if used + string.len(packet) > limit then
        return {'FULL', tostring(used)}
    end
    redis.call('RPUSH', egress, packet)
    redis.call('INCRBY', bytes_key, string.len(packet))
    return {'OK', tostring(used + string.len(packet))}
end)

redis.register_function('hvab_account_egress_pop', function(keys, args)
    local remaining = redis.call('DECRBY', keys[1], number(args[1]))
    if remaining < 0 then
        redis.call('SET', keys[1], '0')
        remaining = 0
    end
    return remaining
end)

redis.register_function('hvab_detach', function(keys, args)
    if redis.call('HGET', keys[1], 'generation') ~= args[1] then
        return 0
    end
    redis.call('HSET', keys[1], 'state', 'closing')
    return 1
end)
"""


def load_functions(r) -> None:
    """Install/replace functions using an administrative connection."""
    r.function_load(LIBRARY, replace=True)
