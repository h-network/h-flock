# LLD — Port Delivery Framework

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address
> scheme, the envelope, and the ingress door. One transient process (`flock.port`)
> is invoked per kick from the switch to dispatch ingress work to the registered
> handler for the destination agent's `port_type`.

## 1. Purpose

The switch delivers envelopes to per-agent ingress queues (`<prefix>:agent:<name>:ingress`)
without knowing or caring how a destination agent is hosted. The port delivery
framework is the receiving framework that:

1. Serializes delivery per agent via an atomic Redis lock (`delivering`).
2. Checks whether delivery to the agent is paused.
3. Resolves the destination's `port_type` using a decoupled registry (`flock.port.registry`).
4. Dispatches ingress work to the registered delivery handler, or snapshot-drains and
   dead-letters it if unroutable.

```
                  ┌───────────────────────────────────────────────────────────┐
                  │                 flock.port.deliver                        │
                  │                                                           │
  switch ──kick──►│ 1. Acquire 'delivering' lock (HSETNX)                     │
                  │ 2. Check 'paused' marker                                  │
                  │ 3. Lookup port_type in flock.port.registry ───────────────┼──► Handler consumes ingress
                  │ 4. Release 'delivering' lock (HDEL) & exit                │    - tmux (LLD-port-tmux.md)
                  └───────────────────────────────────────────────────────────┘    - api (LLD-api.md)
                                                                                   - control (one envelope per kick)
                                                                                   - openshell (LLD-port-openshell.md)
```

## 2. Process Lifecycle & Concurrency

**The port is not a daemon.** It is invoked per delivery kick (or run on demand), executes
its delivery action, and exits immediately. Nothing sits polling in process memory,
and an office of idle agents consumes zero CPU or RAM.

**The backlog stays in Redis until a delivery attempt begins.** Delivering envelopes takes
real time (terminal pastes, mailbox writes, or external RPCs). A persistent process popping
eagerly would buffer unboundedly in process memory, invisible to monitoring and lost on
restart. Instead, queued envelopes remain inspectable in Redis until a transient port process
begins delivery. The tmux, API, OpenShell, and unroutable handlers snapshot-drain their work;
that snapshot then lives in the process while its handler runs, so a process crash after the
drain can lose the snapshot rather than replay it. Control instead consumes at most one
envelope per kick (§3). This is the deliberate at-most-once boundary, not a durable work queue.

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
    deliver_one(r, pod=pod, tenant=tenant, agent=agent)
finally:
    r.hdel(delivering_key, agent)
```

Deliveries for *different* agents execute completely independently in parallel.

The lock is a non-expiring busy tag, not a lease: it contains a start timestamp but has no TTL
or ownership token. If a port process exits without reaching its `finally` block, the stale tag
blocks later processes for that agent until operational cleanup removes it. A waiting process
does not time out or take the tag over.

## 3. Handler Ingress Consumption (`drain_ingress`)

After `deliver_one` resolves and invokes a handler, the tmux, API, OpenShell, and
unroutable handlers snapshot-drain whatever is currently queued in
`<prefix>:agent:<name>:ingress` using an atomic Lua script:

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

The control handler is intentionally different. `flock.control.runner.deliver_one` calls
`flock.bus.receive(..., blocking=False)` and consumes at most one lifecycle envelope per
kick instead of calling `drain_ingress`. The registry dispatch contract therefore hands a
handler access to ingress; it does not require every handler to consume a snapshot batch.

The atomic guarantee describes the normal Redis path. `drain_ingress` also supports clients
without a working `EVAL` command (principally test doubles) by repeatedly calling `LPOP`.
That compatibility fallback drains safely but is not an atomic snapshot; it is also used if
`EVAL` raises an exception.

If the agent has a `paused` marker (`<prefix>:agent:<name>:paused`), `deliver_one` returns
immediately without draining ingress, leaving messages safely queued until resumed.

## 4. Port Type Registry (`flock.port.registry`)

`deliver_one` contains **zero hardcoded port_type branches**. It looks up the destination's
`port_type` from the roster hash (`<prefix>:roster`), then asks `flock.port.registry` for
its handler:

```python
def deliver_one(r, pod: str, tenant: str, agent: str) -> None:
    if r.get(prefix(pod, tenant, agent=agent, resource="paused")):
        return

    raw_port_type = r.hget(prefix(pod, tenant, resource="roster"), agent)
    agent_port_type = raw_port_type.decode() if isinstance(raw_port_type, bytes) else raw_port_type

    handler = get_delivery_handler(agent_port_type) if agent_port_type else None
    if handler is None:
        deliver_unroutable(r, pod=pod, tenant=tenant, agent=agent, port_type_name=agent_port_type)
        return

    handler(r=r, pod=pod, tenant=tenant, agent=agent)
```

The generic handler contract carries only Redis and destination-address context. A handler
resolves configuration specific to its own transport at that transport's edge; for example,
`deliver_tmux` reads `TMUX_SESSION` and `TMUX_SOCKET` rather than requiring every API,
control, OpenShell, or extension handler to accept tmux-specific arguments.

### Handler Specification and Lazy Imports

Handlers are registered as either direct callables or lazy-import `(module_path, attribute_name)` tuples:

| `port_type` | Handler Spec | Owner | Documentation |
|---|---|---|---|
| `tmux` | `("flock.tmux.deliver", "deliver_tmux")` | `tmux` lane | [`LLD-port-tmux.md`](LLD-port-tmux.md) |
| `api` | `("flock.port.deliver", "deliver_api")` | `api` lane | [`LLD-api.md`](LLD-api.md) |
| `control` | `("flock.control.runner", "deliver_one")` | `ports` lane | this document, §"The control handler" above |
| `openshell` | `("flock.port.openshell", "deliver_openshell")` | `openshell` lane | [`LLD-port-openshell.md`](LLD-port-openshell.md) |

**Lazy-import property:** The four built-in tuple specs are resolved on demand when an envelope
for that specific `port_type` is actively being delivered. A custom tuple passed to
`register_port_type` is eagerly resolved once for validation at registration time. In both
cases the registry retains the tuple rather than replacing it with the resolved callable, so
subsequent lookups perform `import_module` and `getattr` again (Python's module cache normally
makes repeat imports cheap). A port delivery for `tmux` never imports `flock.control`,
`openshell`, or external dependencies like gRPC.

The inverse boundary holds too: importing `flock.port` or
`flock.port.registry` does not import `flock.tmux`. Tmux ingress delivery and
terminal openers live in `flock.tmux.deliver` and `flock.tmux.openers`; the only
shared delivery action left in `flock.port.openers` is the storage-only AddTicket
board mutation, alongside attachment schema constants shared with OpenShell.
Legacy top-level tmux attributes on `flock.port` resolve lazily for
compatibility and therefore do not weaken this import boundary.

### Registry API

- `register_port_type(port_type_name: str, handler: HandlerSpec) -> None`: Register or override a delivery handler. Direct handlers must be callable; lazy specs are eagerly resolved and checked once at registration, then retained as tuples so later delivery lookups remain lazy. Invalid custom registrations raise `ValueError`. The four built-in defaults do not pass through this function. The transport-specific tmux, control, and OpenShell modules remain unimported until selected for delivery; API delivery lives in the generic `flock.port.deliver` module already imported by `flock.port`.
- `unregister_port_type(port_type_name: str) -> None`: Remove a registration.
- `reset_registry() -> None`: Reset registry to built-in default mappings.
- `get_delivery_handler(port_type_name: str) -> Optional[Callable]`: Look up and resolve the handler callable. A missing import, missing attribute, or resolved non-callable is logged and returns `None`, which routes delivery through the unroutable dead-letter path.

## 5. Unroutable & Dead-Letter Handling (`deliver_unroutable`)

If an envelope's destination `port_type` is unlisted in the roster or has no registered handler,
`deliver_unroutable` drains the ingress snapshot, emits `received`, pushes each envelope to
`<prefix>:agent:<name>:dead`, and emits a `dead_lettered` record with a reason such as
`unroutable port_type: 'unknown_type'` (or `unroutable port_type: None` when the roster entry
is absent):

```
  ingress ──drain──► [ parse ] ──► emit 'received'
                           │
                           └──► push to :dead queue ──► emit 'dead_lettered' (unroutable)
```

Parsing belongs to the selected handler and therefore happens after registry dispatch. The
tmux, API, OpenShell, and unroutable handlers dead-letter malformed envelopes while processing
their drained snapshots. Because a malformed envelope has no validated envelope to receive,
it gets a `dead_lettered` record but no `received` record.
