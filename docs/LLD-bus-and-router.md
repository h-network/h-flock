# LLD — the bus and the router

> **Status: design, not code.** This describes the nervous system h-flock is
> being built around — the message bus and the envelope router. It records
> decisions taken in discussion, and marks the ones still open in §7. Nothing
> here is implemented yet.
>
> Lineage: the envelope, the VAB tenancy primitive and the `in.`/`out.` queue
> pair come from `h-network/h-cli-dev` (`modules/h-bus/`,
> `services/orchestrator/`). The office model, the roster and the delivery
> mechanics come from `h-network/h-office`. This document is where the two
> meet.

## 1. Purpose & layer

Three layers, and the whole point of the split is that each one is ignorant of
the layer above it.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  L1  BUS          Vab · envelope · queue primitives          │
  │                   a pure library. no daemon, no loop,        │
  │                   no task lifecycle, no opinion about        │
  │                   what a message means                       │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  ROUTER       subscribe set · tenant from the queue key  │
  │                   forward by kind + source · dead-letter     │
  │                   knows nothing about tmux                   │
  ├──────────────────────────────────────────────────────────────┤
  │  EDGE  ADAPTERS   agents (tmux) · api · gateway              │
  │                   produce onto out.<module>                  │
  │                   consume from in.<module>                   │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the router must be able to forward an
envelope to an agent in another office without knowing that local agents live
in tmux.** h-office fails this test — its courier is both the router and the
tmux deliverer in one class, which is why its bus can only ever talk to tmux.
Separating them is the reason this document exists.

## 2. The model, in one picture

Devices generate frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌────────────────────────── office hq ───────────────────────────────┐
  │                                                                    │
  │   EDGE                     L3 ROUTER                    EDGE       │
  │  ┌─────────┐                                        ┌─────────┐    │
  │  │ alice   │                                        │  bob    │    │
  │  │ (tmux)  │                                        │ (tmux)  │    │
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

An agent never writes to another agent's mailbox. It writes to **its own**
out-queue, and the router decides what happens next. This is the difference
from h-office, where `sendMessage` RPUSHes straight onto the recipient's inbox
and nothing sits in between.

## 3. Addressing

### 3.1 The VAB

```
  flock:office:<flock>:<office>
  e.g. flock:office:acme:hq
```

Two segments, because tenancy has two levels: the federation an office belongs
to, and the office itself. The second is what a courier serves; the first is
what a gateway routes on. Collapsing to one segment would work today and cost a
migration the day offices federate.

Segment rule, carried over unchanged: `^[a-z0-9][a-z0-9-]{0,62}$`. Lowercase
alnum and dash. No glob metacharacters, so a prefix is safe to drop into a
Redis `SCAN MATCH`. No underscore, because per-tenant filesystem directories
are named `<a>_<b>` and would be ambiguous to split.

**Every key goes through `prefix()`.** There is no API that yields a flat key.
This is the invariant that makes single-Redis multi-tenancy work, and it is the
one that must survive every change.

### 3.2 Modules

The office is the tenant. Everything that talks on the bus is a **module**
underneath it:

| Module | Kind | Notes |
|---|---|---|
| `<agent>` — `alice`, `bob` | dynamic | one per roster entry. Appears and disappears while running. |
| `api` | fixed | the local daemon, on behalf of a UI or an operator |
| `gateway` | fixed | cross-office traffic (not yet designed — §7) |

This is the one place h-flock departs from h-cli-dev, whose module set
(`telegram`, `claude`, `codex`) is known at build time. Here the agent modules
come from the roster, so the subscribe set is **built from the roster and
rebuilt when it changes**, rather than read from a constant. h-office's courier
already does exactly this, so the mechanism carries over.

Consequence worth stating: ACL scoping, when it arrives, is **per office** and
not per agent. Credentials cannot be provisioned for a module that does not
exist yet.

### 3.3 Queues

Named from the module's point of view — `out.alice` is "envelopes alice
emits", not "envelopes going to alice".

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<vab>:out.<module>` | LIST | the module | the router |
| `<vab>:in.<module>` | LIST | the router | the module |
| `<vab>:dead` | LIST | the router | nothing yet (read by hand / by the API) |

Lists, not pub/sub, so a backlog survives a consumer restart.

## 4. Semantics

**UDP at the edges.** Emitting is fire-and-forget. The sender gets no
acknowledgement, there is no retransmit, and nothing at the bus layer promises
delivery. An agent that wants a reply gets one the same way DNS does — by
convention on top, not by the transport.

**Order is preserved per queue** because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is office-scoped.** `-a all` fans out within one office and stops
there. A broadcast domain ends at the router, as it does in a network. Crossing
offices is explicit addressing, never implicit fan-out.

**Nothing disappears silently.** Two records per envelope, not one: the router
logs at **pop**, before it does anything, and again at the outcome. A crash in
between then leaves a "received, no outcome" line carrying the `stream_id`,
which is detectable. This is deliberately cheaper than a reserve/ack/heartbeat
reliability layer — it does not recover the lost envelope, it only guarantees
the loss is visible. That trade is the decision; revisit it if losses turn out
to be common rather than theoretical.

**The router does not read payloads.** It forwards on `kind` and the source
queue name. The moment routing depends on payload contents it stops being a
switch and becomes a middlebox. h-cli-dev learned this the expensive way and
retired its `TaskBus` and eight task-lifecycle key builders to undo it.

## 5. The envelope

Carried over from h-cli-dev / h-office unchanged:

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
becomes the join key, and the rule is already settled by precedent: propagate
an inbound non-empty cid end to end, mint a fresh one when it is missing or
empty.

## 6. Invariants

1. **`prefix()` on every key.** No flat keys, anywhere, ever.
2. **Tenancy comes from the queue the envelope was popped from**, never from
   its contents. Cross-tenant leakage is therefore structural, not a runtime
   check.
3. **A module may only write to its own `out.` queue.** The router is the only
   writer of `in.` queues. This is what makes the router load-bearing rather
   than a naming convention.
4. **The bus is lifecycle-agnostic.** It moves opaque strings. Task state,
   correlation and session context live above it.
5. **Lists, not pub/sub.**
6. **One bad envelope never stops the loop.** Malformed JSON, an unparseable
   queue name, an unknown module: log and skip, per envelope.
7. **The router knows nothing about tmux.**

## 7. Open items

- **The gateway.** Cross-office routing is agreed in shape only: offices keep
  their own local Redis and dial *out*, a registry of enrolled offices lives in
  a shared Redis, and no separate service is deployed. The routing table, the
  enrolment handshake and what happens to an envelope for a known-but-offline
  office are all undesigned.
- **The `flock` segment.** Proposed here, not yet confirmed. If federation is
  abandoned it is dead weight; if it is kept, it must be decided before the
  first key is written.
- **Subscribe-set fairness.** A fixed queue order starves later queues under
  sustained load. Both h-office and h-cli-dev have this defect today. The
  router should rotate.
- **Roster durability.** h-office regenerates its roster from env on every
  container start, so nothing written by an API survives a restart. h-flock
  needs membership to live somewhere durable before the API can manage it.
- **Kind taxonomy.** `Message` and `Alert` exist. Whether h-flock needs more,
  and whether the router's dispatch table is keyed on `kind` alone or on
  `(kind, source)`, is undecided.
- **Client library.** h-office hand-rolls RESP in 131 dependency-free lines;
  h-cli-dev takes `redis-py`. Federation makes TLS real, which argues for the
  dependency.

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. The board, presence, delivery mechanics and the agent
CLIs all sit at the edge and are out of scope for this document — the nervous
system carries signals; it does not decide what the body does with them.
