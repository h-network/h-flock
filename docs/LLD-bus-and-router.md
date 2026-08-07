# LLD — the bus and the router

> **Status: design, not code.** Decisions taken are stated as such; what is
> deferred is listed in §7. Nothing here is implemented yet.

## 1. Purpose & layer

An **agent** is anything that talks on the bus. Every agent is a producer on its
own egress queue and a consumer of its own ingress queue. The bus carries
envelopes; the router forwards them between agents. What an agent *is* — a
process, a session, a daemon, an HTTP handler — is not the bus's concern and is
deliberately absent from this document.

Three layers, and the point of the split is that each is ignorant of the layer
above it.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  L1  BUS       tenancy prefix · envelope · queue primitives  │
  │                a pure library. no daemon, no loop, no        │
  │                lifecycle, no opinion about what a message    │
  │                means                                         │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  ROUTER    subscribe set · sender from the queue key     │
  │                resolve recipient → queue · dead-letter       │
  ├──────────────────────────────────────────────────────────────┤
  │  EDGE          agents: produce onto <prefix>:egress          │
  │                        consume from <prefix>:ingress         │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the router must forward an envelope
without knowing anything about how the receiving agent is implemented or
hosted.** If routing and delivery live in one component, the bus can only ever
reach the kind of agent that component knows how to drive.

**Why a router exists at all.** A producer could write straight into its
recipient's queue, and then no router would be needed. The cost is that every
producer must then know the topology — which agents exist, what their queues
are called, which tenant they sit in — and that knowledge has to be correct in
every agent and updated in all of them at once. With a router, a producer knows
two things: its own name, and the name of whoever it is addressing. It names a
**recipient**, never a route. Working out where that recipient currently is —
local, another tenant, or gone — is the router's job, and it is the only
component that has to change when the answer does.

## 2. The model, in one picture

Producers emit frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌───────────── tenant — pod:tenant:agent:acme:hq:* ──────────────────┐
  │                                                                    │
  │  EDGE                                          L3 ROUTER           │
  │                                                                    │
  │  ┌───────┐  produce  ┌────────────────┐ BLPOP  ┌────────────────┐  │
  │  │       │──────────►│ …:alice:egress │───────►│                │  │
  │  │ alice │           └────────────────┘        │     router     │  │
  │  │       │  consume  ┌────────────────┐ RPUSH  │                │  │
  │  │       │◄──────────│ …:alice:ingress│◄───────│  recipient →   │  │
  │  └───────┘           └────────────────┘        │     queue      │  │
  │                                                │                │  │
  │  ┌───────┐  produce  ┌────────────────┐ BLPOP  │  from_key →    │  │
  │  │       │──────────►│ …:bob:egress   │───────►│     sender     │  │
  │  │  bob  │           └────────────────┘        │                │  │
  │  │       │  consume  ┌────────────────┐ RPUSH  │                │  │
  │  │       │◄──────────│ …:bob:ingress  │◄───────│                │  │
  │  └───────┘           └────────────────┘        └───────┬────────┘  │
  │                                                        │ won't     │
  │   api and gateway are agents too —                     ▼ forward   │
  │   same prefix shape, same pair                 ┌────────────────┐  │
  │                                                │ …:<from>:dead  │  │
  │                                                └────────────────┘  │
  └────────────────────────────────────────────────────────────────────┘
```

An agent never writes to another agent's ingress queue. It writes to **its own**
egress, and the router decides what happens next. Two things follow: routing
decisions happen in exactly one place, and a producer can only write inside its
own prefix — so the tenancy boundary is enforced on entry, not only on exit.

## 3. Addressing

### 3.1 The prefix

```
  pod:tenant:agent:<pod>:<tenant>:<agent>

  e.g. pod:tenant:agent:acme:hq:alice
```

Three literal tags, then three values. The tags never change; they make a key
self-describing and let a parser reject a key belonging to some other scheme
sharing the same Redis.

| Level | Holds | Who cares |
|---|---|---|
| `pod` | tenants | a gateway, when routing between tenants |
| `tenant` | agents | one router serves exactly one tenant |
| `agent` | queues | the agent itself |

Putting the agent in the prefix rather than in the queue name is what makes
per-agent isolation structural: a credential can be scoped to
`~pod:tenant:agent:acme:hq:alice:*` and reach that agent's keys and nothing
else. Scoping at the tenant level could not express that.

Segment rule: `^[a-z0-9][a-z0-9-]{0,62}$` — lowercase alnum and dash. No glob
metacharacters, so a prefix is safe to drop into a Redis `SCAN MATCH`. No
underscore, so that per-agent filesystem directories named `<a>_<b>` stay
unambiguous to split.

**Every key goes through `prefix()`.** There is no API that yields a flat key.
This is what makes many tenants on one Redis safe, and it is the invariant that
must survive every change.

### 3.2 Agents

Everything addressable is an agent. There is no second concept:

| Agent | Kind | Notes |
|---|---|---|
| named agents | dynamic | enrolled from a roster. Appear and disappear while running. |
| `api` | fixed | serves an HTTP client |
| `gateway` | fixed | cross-tenant traffic (deferred — §7) |

Named agents come from a roster that changes while the router is running, so the
subscribe set is **derived from the roster and rebuilt when it changes**, not
read from a constant. Adding a kind of agent is adding a name, not altering the
addressing scheme — that is what makes the scheme scale.

### 3.3 Queues

Direction is relative to the **agent**, as it is on a network device: egress is
traffic leaving the agent, ingress is traffic arriving at it. The router sits on
the opposite end of both.

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<prefix>:egress` | LIST | the agent | the router |
| `<prefix>:ingress` | LIST | the router | the agent |
| `<prefix>:dead` | LIST | the router | nothing yet — read by hand or by `api` |

Lists, not pub/sub, so a backlog survives a consumer restart.

A dead-lettered envelope is parked under the **sender's** prefix, not the
recipient's — an envelope that failed because its recipient could not be
resolved has no recipient prefix to be parked under, and the sender is the party
that needs to see it.

## 4. Semantics

**Fire-and-forget, like UDP.** The producer gets no acknowledgement, there is no
retransmit, and nothing at the bus layer promises delivery. An agent wanting a
reply gets one by convention on top, the way DNS does over UDP — never from the
transport.

**Order is preserved per queue**, because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is tenant-scoped.** A broadcast fans out to the agents of one tenant
and stops there, the way a broadcast domain ends at a router. Reaching another
tenant is explicit addressing, never implicit fan-out.

**Nothing disappears silently.** Two records per envelope, not one: the router
logs at **pop**, before doing anything, and again at the outcome. A crash in
between then leaves a "received, no outcome" line carrying the `stream_id`,
which is detectable. This is deliberately cheaper than a reserve/ack/heartbeat
reliability layer — it does not recover a lost envelope, it only guarantees the
loss is visible. That trade is the decision; revisit it if losses turn out to be
common rather than theoretical.

**The router does not read payloads.** It forwards on the header — `recipient`,
`kind`, and the queue the envelope was popped from. The moment routing depends
on payload contents it stops being a switch and becomes a middlebox, and every
change to what a message means becomes a change to the router.

## 5. The envelope

```json
{
  "v": 1,
  "kind": "Message",
  "stream_id": "<hex>",
  "correlation_id": "<hex>",
  "ts": "2026-08-07T18:00:00.000Z",
  "producer": "<agent>",
  "recipient": "<agent>",
  "payload": { }
}
```

Outer fields are structural and always present. Everything kind-specific lives
inside `payload`, and validating it is the consumer's job, never the bus's.
Unknown top-level fields are ignored, so a newer producer cannot break an older
router.

`recipient` is an **agent name, not a queue name**. A producer writes
`"recipient": "bob"`; it never constructs `…:bob:ingress` and never names a
tenant. Resolving the name to a queue is the router's only real decision, and
keeping it there is what stops topology knowledge spreading into every agent. An
unresolvable name is a dead-letter, not a crash.

A bare name means "in my tenant", which is the only case the first build
handles. Qualified names for reaching another tenant or pod arrive with the
gateway (§7) — until then, an unqualified name that does not resolve inside the
sender's own tenant is dead-lettered.

Both `producer` and `recipient` are header fields, so reading them is not
reading the payload — §6.7 holds.

## 6. Invariants

1. **`prefix()` on every key.** No flat keys, anywhere, ever.
2. **The sender comes from the queue the envelope was popped from**, never from
   its contents. Cross-tenant leakage is therefore structural, not a runtime
   check.
3. **An agent may only write to its own `egress` queue.** The router is the only
   writer of `ingress` queues. This is what makes the router load-bearing rather
   than a naming convention.
4. **The bus is lifecycle-agnostic.** It moves opaque strings. Task state,
   correlation and session context live above it.
5. **Lists, not pub/sub.**
6. **One bad envelope never stops the loop.** Malformed JSON, an unparseable
   queue name, an unresolvable recipient: log and skip or dead-letter, per
   envelope.
7. **The router knows nothing about how an agent is implemented.**

## 7. Deferred

**None of these block the first build**, which is a skeleton that forwards
envelopes. None of them change its shape. Do not solve them pre-emptively.

| Item | Why it can wait |
|---|---|
| **Gateway** | Cross-tenant routing arrives as another agent with the same ingress/egress pair, plus qualified recipient names. Nothing in the skeleton changes to accommodate it later. |
| **Subscribe-set fairness** | A fixed queue order can starve later queues under sustained load. With a handful of agents it cannot happen. Rotate when it does. |
| **Roster durability** | Read the roster at boot; a restart re-reads it. Durable storage is needed only once something writes it at runtime. |
| **Kind taxonomy** | One kind until a second is needed. Dispatch keyed on `kind` alone; `(kind, sender)` is a change to make when two senders need different handling of the same kind. |
| **Client library** | A hand-rolled RESP client keeps dependencies at zero; a maintained one brings async and TLS. Decide at the import, not before. |

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. Anything an agent does with an envelope after consuming
it is out of scope — the bus carries signals, the router forwards them, and
neither decides what is done with them.
