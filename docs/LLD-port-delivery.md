# LLD — Port Delivery Framework

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address
> scheme, the envelope, and the ingress door. One transient process (`flock.port`)
> is invoked per kick from the switch to drain queued envelopes and dispatch to
> the registered handler for the destination agent's `port_type`.

## 1. Purpose

The switch delivers envelopes to per-agent ingress queues (`<prefix>:agent:<name>:ingress`)
without knowing or caring how a destination agent is hosted. The port delivery
framework is the receiving framework that:

1. Serializes delivery per agent via an atomic Redis lock (`delivering`).
2. Atomically drains the agent's queued ingress envelopes.
3. Resolves the destination's `port_type` using a decoupled registry (`flock.port.registry`).
4. Dispatches the batch to the registered delivery handler, or dead-letters cleanly if unroutable.

```
                  ┌───────────────────────────────────────────────────────────┐
                  │                 flock.port.deliver                        │
                  │                                                           │
  switch ──kick──►│ 1. Acquire 'delivering' lock (HSETNX)                     │
                  │ 2. Check 'paused' marker                                  │
                  │ 3. Atomic snapshot-drain (drain_ingress Lua)              │
                  │ 4. Lookup port_type in flock.port.registry ───────────────┼──► Handler dispatch
                  │ 5. Release 'delivering' lock (HDEL) & exit                │    - tmux (LLD-port-tmux.md)
                  └───────────────────────────────────────────────────────────┘    - api (LLD-api.md)
                                                                                   - control (LLD-control.md)
                                                                                   - openshell (LLD-port-openshell.md)
```

## 2. Process Lifecycle & Concurrency

**The port is not a daemon.** It is invoked per delivery kick (or run on demand), executes
its delivery action, and exits immediately. Nothing sits polling in process memory,
and an office of idle agents consumes zero CPU or RAM.

**The backlog stays in Redis.** Delivering envelopes takes real time (terminal pastes,
mailbox writes, or external RPCs). A persistent process popping eagerly would buffer
unboundedly in process memory, invisible to monitoring and lost on restart. By leaving
queued envelopes in Redis, queue depth is always inspectable.

**Mutual exclusion per agent (`delivering` lock).** Concurrent delivery processes for the
same agent are serialized using an atomic `HSETNX` loop against `<prefix>:delivering`:

```python
# Acquire busy tag
while True:
    now_iso = datetime.now(timezone.utc).isoformat()
    if r.hsetnx(delivering_key, agent, now_iso):
        break
    time.sleep(0.05)

try:
    deliver_one(r, pod=pod, tenant=tenant, agent=agent, session_name=session_name, socket=socket)
finally:
    r.hdel(delivering_key, agent)
```

Deliveries for *different* agents execute completely independently in parallel.

## 3. Atomic Snapshot Draining (`drain_ingress`)

Upon acquiring the `delivering` lock, the port snapshot-drains whatever is currently
queued in `<prefix>:agent:<name>:ingress` using an atomic Lua script:

```lua
-- flock ingress drain all v1
local key = KEYS[1]
local items = redis.call('LRANGE', key, 0, -1)
if #items > 0 then
    redis.call('DEL', key)
end
return items
```

This ensures zero race conditions with incoming switch deliveries: envelopes arriving
after the snapshot remain safely queued in Redis and trigger a subsequent delivery run.

If the agent has a `paused` marker (`<prefix>:agent:<name>:paused`), `deliver_one` returns
immediately without draining ingress, leaving messages safely queued until resumed.

## 4. Port Type Registry (`flock.port.registry`)

`deliver_one` contains **zero hardcoded port_type branches**. It looks up the destination's
`port_type` from the roster hash (`<prefix>:roster`) in `flock.port.registry`:

```python
def deliver_one(r, pod: str, tenant: str, agent: str, session_name: str, socket: str | None = None) -> None:
    if r.get(prefix(pod, tenant, agent=agent, resource="paused")):
        return

    raw_port_type = r.hget(prefix(pod, tenant, resource="roster"), agent)
    agent_port_type = raw_port_type.decode() if isinstance(raw_port_type, bytes) else raw_port_type

    handler = get_delivery_handler(agent_port_type) if agent_port_type else None
    if handler is None:
        deliver_unroutable(r, pod=pod, tenant=tenant, agent=agent, port_type_name=agent_port_type)
        return

    handler(r=r, pod=pod, tenant=tenant, agent=agent, session_name=session_name, socket=socket)
```

### Handler Specification and Lazy Imports

Handlers are registered as either direct callables or lazy-import `(module_path, attribute_name)` tuples:

| `port_type` | Handler Spec | Owner | Documentation |
|---|---|---|---|
| `tmux` | `("flock.port.deliver", "deliver_tmux")` | `tmux` lane | [`LLD-port-tmux.md`](LLD-port-tmux.md) |
| `api` | `("flock.port.deliver", "deliver_api")` | `api` lane | [`LLD-api.md`](LLD-api.md) |
| `control` | `("flock.control.runner", "deliver_one")` | `bus` lane | [`LLD-control.md`](LLD-control.md) |
| `openshell` | `("flock.port.openshell", "deliver_openshell")` | `openshell` lane | [`LLD-port-openshell.md`](LLD-port-openshell.md) |

**Lazy-import property:** Handlers registered as tuple specs are only imported on-demand when an
envelope for that specific `port_type` is actively being delivered. A port delivery for `tmux`
never imports `flock.control`, `openshell`, or external dependencies like gRPC.

### Registry API

- `register_port_type(port_type_name: str, handler: HandlerSpec) -> None`: Register or override a delivery handler.
- `unregister_port_type(port_type_name: str) -> None`: Remove a registration.
- `reset_registry() -> None`: Reset registry to built-in default mappings.
- `get_delivery_handler(port_type_name: str) -> Optional[Callable]`: Look up and resolve the handler callable.

## 5. Unroutable & Dead-Letter Handling (`deliver_unroutable`)

If an envelope's destination `port_type` is unlisted in the roster or has no registered handler,
`deliver_unroutable` drains the ingress snapshot, emits `received`, pushes each envelope to
`<prefix>:agent:<name>:dead`, and emits a `dead_lettered` record with `reason="unroutable port_type: <name>"`:

```
  ingress ──drain──► [ parse ] ──► emit 'received'
                           │
                           └──► push to :dead queue ──► emit 'dead_lettered' (unroutable)
```

Malformed envelopes that fail schema parsing are dead-lettered immediately before dispatch.
