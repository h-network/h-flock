# LLD — the bus and the router

> **Status: design, not code.** Decisions taken are stated as such; what is
> still open is listed in §7. Nothing here is implemented yet.

## 1. Purpose & layer

A **module** is anything that talks on the bus. Every module is a producer on
its own egress queue and a consumer of its own ingress queue. The bus carries
envelopes; the router forwards them between modules. What a module *is* — a
process, a session, a daemon — is not the bus's concern and is deliberately
absent from this document.

Three layers, and the point of the split is that each is ignorant of the layer
above it.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  L1  BUS       tenancy prefix · envelope · queue primitives  │
  │                a pure library. no daemon, no loop, no        │
  │                lifecycle, no opinion about what a message    │
  │                means                                         │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  ROUTER    subscribe set · tenant from the queue key     │
  │                forward by kind + source · dead-letter        │
  ├──────────────────────────────────────────────────────────────┤
  │  EDGE          modules: produce onto egress.<module>         │
  │                         consume from ingress.<module>        │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the router must forward an envelope
without knowing anything about how the target module is implemented or
hosted.** If routing and delivery live in one component, the bus can only ever
reach the kind of module that component knows how to drive.

## 2. The model, in one picture

Producers emit frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌───────────────────────────── tenant ───────────────────────────────┐
  │                                                                    │
  │  EDGE                                          L3 ROUTER           │
  │                                                                    │
  │  ┌───────┐  produce  ┌───────────────┐ BLPOP  ┌────────────────┐   │
  │  │       │──────────►│ egress.mod-a  │───────►│                │   │
  │  │ mod-a │           └───────────────┘        │     router     │   │
  │  │       │  consume  ┌───────────────┐ RPUSH  │                │   │
  │  │       │◄──────────│ ingress.mod-a │◄───────│  from_key →    │   │
  │  └───────┘           └───────────────┘        │     tenant     │   │
  │                                               │                │   │
  │  ┌───────┐  produce  ┌───────────────┐ BLPOP  │  kind+source → │   │
  │  │       │──────────►│ egress.mod-b  │───────►│     target     │   │
  │  │ mod-b │           └───────────────┘        │                │   │
  │  │       │  consume  ┌───────────────┐ RPUSH  │                │   │
  │  │       │◄──────────│ ingress.mod-b │◄───────│                │   │
  │  └───────┘           └───────────────┘        └───────┬────────┘   │
  │                                                       │ won't      │
  │   every module has the same pair —                    ▼ forward    │
  │   api and gateway included                      ┌───────────┐      │
  │                                                 │   dead    │      │
  │                                                 └───────────┘      │
  └────────────────────────────────────────────────────────────────────┘
```

A module never writes to another module's ingress queue. It writes to **its
own** egress, and the router decides what happens next. Two things follow: routing
decisions happen in exactly one place, and a producer can only write inside its
own prefix — so the tenancy boundary is enforced on entry, not only on exit.

## 3. Addressing

### 3.1 The tenancy prefix

```
  <scope>:<tenant>:<scope-id>:<tenant-id>
```

Two segments, because tenancy has two levels: the group a tenant belongs to,
and the tenant itself. The second is what a router serves; the first is what a
gateway routes on. One segment would work today and cost a migration the day
tenants federate. The literal tags are a deployment choice and are not fixed
here (§7).

Segment rule: `^[a-z0-9][a-z0-9-]{0,62}$` — lowercase alnum and dash. No glob
metacharacters, so a prefix is safe to drop into a Redis `SCAN MATCH`. No
underscore, so that per-tenant filesystem directories named `<a>_<b>` stay
unambiguous to split.

**Every key goes through `prefix()`.** There is no API that yields a flat key.
This is what makes many tenants on one Redis safe, and it is the invariant that
must survive every change.

### 3.2 Modules

The tenant is the isolation boundary. Every module lives underneath one:

| Module | Kind | Notes |
|---|---|---|
| dynamic modules | dynamic | enrolled from a roster. Appear and disappear while running. |
| `api` | fixed | the local daemon, acting for a client |
| `gateway` | fixed | cross-tenant traffic (not yet designed — §7) |

Dynamic modules come from a roster that changes while the router is running, so
the subscribe set is **derived from the roster and rebuilt when it changes**,
not read from a constant. Adding a module type is adding a name, not altering
the addressing scheme — that is what makes the scheme scale.

Consequence worth stating: credential scoping is **per tenant**, not per module.
Credentials cannot be provisioned for a module that does not exist yet.

### 3.3 Queues

Direction is relative to the **module**, as it is on a network device:
`egress.<module>` is traffic leaving that module, `ingress.<module>` is traffic
arriving at it. The router sits on the opposite end of both.

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<prefix>:egress.<module>` | LIST | the module | the router |
| `<prefix>:ingress.<module>` | LIST | the router | the module |
| `<prefix>:dead` | LIST | the router | nothing yet — read by hand or by `api` |

Lists, not pub/sub, so a backlog survives a consumer restart.

## 4. Semantics

**Fire-and-forget, like UDP.** The producer gets no acknowledgement, there is no
retransmit, and nothing at the bus layer promises delivery. A module wanting a
reply gets one by convention on top, the way DNS does over UDP — never from the
transport.

**Order is preserved per queue**, because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is tenant-scoped.** A broadcast fans out to the modules of one
tenant and stops there, the way a broadcast domain ends at a router. Reaching
another tenant is explicit addressing, never implicit fan-out.

**Nothing disappears silently.** Two records per envelope, not one: the router
logs at **pop**, before doing anything, and again at the outcome. A crash in
between then leaves a "received, no outcome" line carrying the `stream_id`,
which is detectable. This is deliberately cheaper than a reserve/ack/heartbeat
reliability layer — it does not recover a lost envelope, it only guarantees the
loss is visible. That trade is the decision; revisit it if losses turn out to be
common rather than theoretical.

**The router does not read payloads.** It forwards on `kind` and the source
queue name. The moment routing depends on payload contents it stops being a
switch and becomes a middlebox, and every change to what a message means
becomes a change to the router.

## 5. The envelope

```json
{
  "v": 1,
  "kind": "Message",
  "stream_id": "<hex>",
  "correlation_id": "<hex>",
  "ts": "2026-08-07T18:00:00.000Z",
  "producer": "<module>",
  "payload": { }
}
```

Outer fields are structural and always present. Everything kind-specific lives
inside `payload`, and validating it is the consumer's job, never the bus's.
Unknown top-level fields are ignored, so a newer producer cannot break an older
router.

`correlation_id` is carried but unused for now. When request/reply arrives it
becomes the join key, under the rule: propagate an inbound non-empty cid end to
end, mint a fresh one when it is missing or empty.

## 6. Invariants

1. **`prefix()` on every key.** No flat keys, anywhere, ever.
2. **Tenancy comes from the queue the envelope was popped from**, never from its
   contents. Cross-tenant leakage is therefore structural, not a runtime check.
3. **A module may only write to its own `egress.` queue.** The router is the
   only writer of `ingress.` queues. This is what makes the router load-bearing rather
   than a naming convention.
4. **The bus is lifecycle-agnostic.** It moves opaque strings. Task state,
   correlation and session context live above it.
5. **Lists, not pub/sub.**
6. **One bad envelope never stops the loop.** Malformed JSON, an unparseable
   queue name, an unknown module: log and skip, per envelope.
7. **The router knows nothing about how a module is implemented.**

## 7. Open items

- **The gateway.** Cross-tenant routing is agreed in shape only: each tenant
  keeps its own local Redis and dials *out*, a registry of enrolled tenants
  lives in a shared Redis, and no separate service is deployed. The routing
  table, the enrolment handshake, and what happens to an envelope for a
  known-but-offline tenant are all undesigned.
- **The literal segment tags.** The two-level prefix is agreed; what the levels
  are called is not. Must be settled before the first key is written.
- **Subscribe-set fairness.** A fixed queue order starves later queues under
  sustained load. The router should rotate.
- **Roster durability.** Enrolment has to live somewhere that survives a restart
  before `api` can manage it.
- **Kind taxonomy.** Whether dispatch is keyed on `kind` alone or on
  `(kind, source)`, and what kinds exist beyond a plain message.
- **Client library.** A minimal hand-rolled RESP client keeps the dependency
  count at zero; a maintained client brings async and TLS, which federation
  makes real.

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. Anything a module does with an envelope after consuming
it is out of scope — the bus carries signals, the router forwards them, and
neither decides what is done with them.
