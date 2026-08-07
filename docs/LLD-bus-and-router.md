# LLD — the bus and the router

> **Status: design, not code.** This describes the nervous system h-flock is
> built around — the message bus and the envelope router. Decisions taken are
> stated as such; what is still open is listed in §7. Nothing here is
> implemented yet.

## 1. Purpose & layer

An office is a set of agents that need to talk to each other. The bus carries
what they say; the router decides where it goes. Everything else — what an
agent is, how a message reaches its screen, what work it is doing — sits above
and is out of scope here.

Three layers, and the point of the split is that each is ignorant of the layer
above it.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  L1  BUS          Vab · envelope · queue primitives          │
  │                   a pure library. no daemon, no loop,        │
  │                   no task lifecycle, no opinion about        │
  │                   what a message means                       │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  ROUTER       subscribe set · tenant from the queue key  │
  │                   forward by kind + source · dead-letter     │
  │                   no knowledge of how a module is hosted     │
  ├──────────────────────────────────────────────────────────────┤
  │  EDGE  ADAPTERS   agents · api · gateway                     │
  │                   produce onto out.<module>                  │
  │                   consume from in.<module>                   │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the router must be able to forward an
envelope to a module in another office without knowing how any module is
hosted.** If routing and delivery live in one component, the bus can only ever
talk to whatever that component knows how to drive. Keeping them apart is the
reason this document exists.

## 2. The model, in one picture

Devices generate frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌────────────────────────── office hq ───────────────────────────────┐
  │                                                                    │
  │   EDGE                     L3 ROUTER                    EDGE       │
  │  ┌─────────┐                                        ┌─────────┐    │
  │  │ alice   │                                        │  bob    │    │
  │  └────┬────┘                                        └────▲────┘    │
  │       │ emit                                    deliver  │         │
  │       ▼                                                  │         │
  │  ┌──────────┐                                     ┌──────────┐     │
  │  │out.alice │──┐                               ┌─►│ in.bob   │     │
  │  └──────────┘  │  BLPOP          RPUSH         │  └──────────┘     │
  │                ├──────►┌──────────────┐────────┤                   │
  │  ┌──────────┐  │       │   router     │        │  ┌──────────┐     │
  │  │ out.bob  │──┘       │              │        └─►│ in.alice │     │
  │  └──────────┘          │ from_key →   │           └──────────┘     │
  │                        │   tenant     │                            │
  │  ┌──────────┐          │ kind+source →│           ┌──────────┐     │
  │  │ out.api  │─────────►│   target     │──────────►│ in.api   │     │
  │  └──────────┘          └──────┬───────┘           └──────────┘     │
  │                               │                                    │
  │                               ▼  won't forward                     │
  │                        ┌─────────────┐                             │
  │                        │ dead        │                             │
  │                        └─────────────┘                             │
  └────────────────────────────────────────────────────────────────────┘
```

A module never writes to another module's mailbox. It writes to **its own**
out-queue, and the router decides what happens next. Two things follow: routing
decisions happen in exactly one place, and a sender can only ever write inside
its own prefix — so the tenancy boundary is enforced on the way in, not just on
the way out.

## 3. Addressing

### 3.1 The VAB

```
  flock:office:<flock>:<office>
  e.g. flock:office:acme:hq
```

Two segments, because tenancy has two levels: the federation an office belongs
to, and the office itself. The second is what a router serves; the first is
what a gateway routes on. One segment would work today and cost a migration the
day offices federate.

Segment rule: `^[a-z0-9][a-z0-9-]{0,62}$` — lowercase alnum and dash. No glob
metacharacters, so a prefix is safe to drop into a Redis `SCAN MATCH`. No
underscore, so that per-tenant filesystem directories named `<a>_<b>` stay
unambiguous to split.

**Every key goes through `prefix()`.** There is no API that yields a flat key.
This is what makes many offices on one Redis safe, and it is the invariant that
must survive every change.

### 3.2 Modules

The office is the tenant. Everything that talks on the bus is a **module**
underneath it:

| Module | Kind | Notes |
|---|---|---|
| `<agent>` — `alice`, `bob` | dynamic | one per roster entry. Appears and disappears while running. |
| `api` | fixed | the local daemon, acting for a UI or an operator |
| `gateway` | fixed | cross-office traffic (not yet designed — §7) |

Agent modules come from the roster, which changes while the router is running.
So the subscribe set is **derived from the roster and rebuilt when it changes**,
not read from a constant. Adding a module type is adding a name, not altering
the addressing scheme — that is what makes the scheme scale.

Consequence worth stating: any credential scoping is **per office**, not per
module. Credentials cannot be provisioned for a module that does not exist yet.

### 3.3 Queues

Named from the module's point of view — `out.alice` is "envelopes alice
emits", not "envelopes going to alice".

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<vab>:out.<module>` | LIST | the module | the router |
| `<vab>:in.<module>` | LIST | the router | the module |
| `<vab>:dead` | LIST | the router | nothing yet — read by hand or by the api |

Lists, not pub/sub, so a backlog survives a consumer restart.

## 4. Semantics

**Fire-and-forget, like UDP.** The sender gets no acknowledgement, there is no
retransmit, and nothing at the bus layer promises delivery. A module wanting a
reply gets one by convention on top, the way DNS does over UDP — never from the
transport.

**Order is preserved per queue**, because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is office-scoped.** A broadcast fans out within one office and stops
there, the way a broadcast domain ends at a router. Reaching another office is
explicit addressing, never implicit fan-out.

**Nothing disappears silently.** Two records per envelope, not one: the router
logs at **pop**, before doing anything, and again at the outcome. A crash in
between then leaves a "received, no outcome" line carrying the `stream_id`,
which is detectable. This is deliberately cheaper than a reserve/ack/heartbeat
reliability layer — it does not recover a lost envelope, it only guarantees the
loss is visible. That trade is the decision; revisit it if losses turn out to be
common rather than theoretical.

**The router does not read payloads.** It forwards on `kind` and the source
queue name. The moment routing depends on payload contents it stops being a
switch and becomes a middlebox, and every future change to a message's meaning
becomes a change to the router.

## 5. The envelope

```json
{
  "v": 1,
  "kind": "Message",
  "stream_id": "<hex>",
  "correlation_id": "<hex>",
  "ts": "2026-08-07T18:00:00.000Z",
  "producer": "alice",
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
3. **A module may only write to its own `out.` queue.** The router is the only
   writer of `in.` queues. This is what makes the router load-bearing rather
   than a naming convention.
4. **The bus is lifecycle-agnostic.** It moves opaque strings. Task state,
   correlation and session context live above it.
5. **Lists, not pub/sub.**
6. **One bad envelope never stops the loop.** Malformed JSON, an unparseable
   queue name, an unknown module: log and skip, per envelope.
7. **The router does not know how any module is hosted.**

## 7. Open items

- **The gateway.** Cross-office routing is agreed in shape only: offices keep
  their own local Redis and dial *out*, a registry of enrolled offices lives in
  a shared Redis, and no separate service is deployed. The routing table, the
  enrolment handshake, and what happens to an envelope for a known-but-offline
  office are all undesigned.
- **The `flock` segment.** Proposed, not confirmed. Dead weight if federation is
  abandoned; must be settled before the first key is written.
- **Subscribe-set fairness.** A fixed queue order starves later queues under
  sustained load. The router should rotate.
- **Roster durability.** Membership has to live somewhere that survives a
  restart before the api can manage it.
- **Kind taxonomy.** Whether dispatch is keyed on `kind` alone or on
  `(kind, source)`, and what kinds exist beyond a plain message.
- **Client library.** A minimal hand-rolled RESP client keeps the dependency
  count at zero; a maintained client brings async and TLS, which federation
  makes real.

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. Boards, presence, delivery mechanics and the agent
processes themselves all sit at the edge and are out of scope — the nervous
system carries signals; it does not decide what the body does with them.
