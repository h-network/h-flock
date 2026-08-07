# LLD — the api

> **Status: design, not code.** Decisions taken are stated as such; what is
> deferred is listed in §7. Nothing here is implemented yet.
>
> Depends on [`LLD-bus-and-router.md`](LLD-bus-and-router.md) for the address
> scheme, the envelope, and the invariants it inherits.

## 1. Purpose & layer

The api is how something that is not on the bus — a browser, a script, an
operator — reaches a tenant. It speaks HTTP on one side and the bus on the
other.

It is **an agent**, with an address like any other:

```
  pod:acme:tenant:hq:agent:api
```

That is not a formality. It means the api emits onto its own egress and the
router forwards, exactly as every other agent does — so the api cannot write
into anyone's ingress, and a request cannot name a queue. It gets the same
confinement the bus gives everything else, for free.

**It runs in its own process.** Every part of this project is a module that can
be changed, restarted and deployed without disturbing the others; the api is one
of them. It does not share a process with the router, and a crash or a redeploy
of one does not take the other with it.

```
  ┌──────────────── api module — its own process ───────────────────┐
  │                                                                 │
  │   HTTP client                                                   │
  │        │  Authorization: Bearer <token>                         │
  │        ▼                                                        │
  │   ┌─────────┐  emit   ┌────────────────────┐                    │
  │   │         │────────►│ …:agent:api:egress │───► router         │
  │   │   api   │         └────────────────────┘                    │
  │   │         │  read   ┌────────────────────┐                    │
  │   │         │◄────────│ redis, via prefix()│                    │
  │   └─────────┘         └────────────────────┘                    │
  └─────────────────────────────────────────────────────────────────┘
```

## 2. Two kinds of operation

They have different backends and different truthfulness, and conflating them is
the main way this component goes wrong.

**Sending** goes through the bus. The api emits an envelope onto its own egress
with a `recipient`, and the router does the rest. The api learns nothing about
what happened next, so it answers `202` with the `stream_id` and no more. It
must not report delivery, because it does not know.

**Reading** does not. State — the roster, a board, who is enrolled — is read
directly from Redis through `prefix()`. Routing a query as an envelope and
waiting for a reply would be the wrong shape entirely: a read needs a key, not a
route.

## 3. Operations

The starting surface. Everything here is either an emit or a keyed read;
anything that is neither does not belong in this module.

| Method | Path | Backend | Returns |
|---|---|---|---|
| `GET` | `/health` | — | liveness |
| `GET` | `/agents` | roster | enrolled agents in the tenant |
| `GET` | `/agents/{agent}` | Redis | one agent's queue depths |
| `POST` | `/agents/{agent}/messages` | egress → router | `202` + `stream_id` |
| `GET` | `/agents/{agent}/board` | Redis | that agent's board |
| `GET` | `/board` | roster + pipelined reads | every agent's board |

`GET /board` walks the roster and pipelines the reads — one round trip, no
keyspace scan, and agents holding nothing still appear. It does not maintain an
index.

## 4. Semantics

**Sends are asynchronous and say so.** `202`, a `stream_id`, nothing about
delivery. A client that wants to know what became of an envelope reads the log
by `stream_id`.

**Reads are point-in-time.** No subscriptions, no long-polling, no consistency
guarantee across two calls.

**The api never impersonates.** The sender of an envelope is derived from the
queue it was popped from, so everything the api emits has `api` as its sender —
whoever asked for it. If "on behalf of X" is ever needed it is a field of its
own, never the sender, because trusting request content for identity is exactly
what the queue-derived rule prevents.

**One tenant per process.** The api is addressed inside a tenant and serves that
tenant only. Reaching another one is the router's job via cross-tenant routing,
not something the api reaches around the side to do.

## 5. Transport & auth

**TCP, FastAPI.** A real HTTP surface with generated schema, since the clients
are browsers and scripts rather than local processes.

**A bearer token**, checked on every request including reads. Held in
configuration, never in the address scheme and never in an envelope. There is
one token per api instance; per-client identity is deferred (§7).

⚠ **Binding is the whole security posture.** The token is the only thing between
a request and a tenant's bus. Bind loopback and publish deliberately; a
non-loopback bind with no token set must refuse to start rather than warn,
because there is no safe default for that combination.

## 6. Invariants

1. **The api emits only to its own egress.** It never writes another agent's
   ingress, and no request may name a queue.
2. **Every key it reads is built through `prefix()`.** No flat keys, no
   request-supplied key fragments.
3. **It never reports delivery**, because it cannot observe it.
4. **It knows nothing about how agents are implemented.** No tmux, no process
   management, no agent lifecycle — those live in other modules and are out of
   scope here.
5. **Auth is checked before anything else**, reads included.

## 7. Deferred

**None of these block the first build.**

**Session endpoints.** Attaching to a live agent session — the terminal-facing
surface — is a separate module with its own transport question, since streaming
is a websocket concern rather than a REST one. It is named here only so nobody
designs the REST surface around it.

**Per-client identity.** One shared token now. Per-client tokens matter when
"who asked" needs to reach the envelope as an on-behalf-of field, and that field
does not exist yet.

**TLS.** A loopback bind does not need it. A published one does, and terminating
it outside this process is likely simpler than terminating it inside.

## 8. What this is not

Not the router — it emits like any agent and forwards nothing. Not an agent
runtime — it does not start, stop, watch or drive anything. Not a query language
over Redis — every endpoint is a fixed key or a roster walk, and a request can
never name a key.
