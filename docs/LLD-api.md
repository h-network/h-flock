# LLD — the api

> **Status: design, not code.** Nothing here is implemented yet.
>
> Depends on [`LLD-bus-and-router.md`](LLD-bus-and-router.md) for the address
> scheme and the envelope.

## 1. Purpose

An HTTP front door to a running tenant. A user can already reach an agent by
typing into its window; the api is the other way in — it puts a correctly formed
envelope on the bus, and the router does what it always does.

It also reads state that already exists in Redis: boards, rosters, queue depths.
Later it exposes tmux windows.

That is the whole of it. It has no logic of its own beyond building a valid
envelope, reading keys, and handing back what comes the other way.

```
  HTTP ──► api ──send──► bus ──► router ──► agent
    ▲        │                                 │
    │        └──► Redis reads (boards, roster, depths)
    │                                          │
    └──── receive ◄── api ingress ◄── router ◄─┘   agent replies to "api"
```

**It has an address**, so an agent can reply to it. The reply is addressed to
`api` like any other recipient, the router puts it on the api's ingress, and the
api takes it off. That is the only reason it needs one — not to be a peer, but
to be reachable.

**It uses the same two doors as everything else** — `send` to put an envelope on
the bus, `receive` to take one off. It has no privileged path to Redis for
envelopes; only the state reads below bypass the bus, and those are reads.

**Its own process.** Every part of this project is a module that can be changed,
restarted and deployed without disturbing the others.

## 2. Operations

| Method | Path | Does |
|---|---|---|
| `GET` | `/health` | liveness |
| `GET` | `/agents` | enrolled agents, from the roster |
| `GET` | `/agents/{agent}` | queue depths |
| `POST` | `/agents/{agent}/messages` | put an envelope on the bus |
| `GET` | `/agents/{agent}/board` | that agent's board |
| `GET` | `/board` | every agent's board |
| `GET` | `/messages/{correlation_id}` | replies collected for that request, if any |

`GET /board` walks the roster and pipelines the reads — one round trip, no
keyspace scan, and agents holding nothing still appear.

## 3. Sending

Build a `v=1` envelope with the `recipient` from the path, `send` it, return
`202` with the `stream_id` and the `correlation_id`.

It does not report delivery, because it cannot observe it. A client that wants
to know what became of an envelope reads the log by `stream_id`.

## 4. Receiving

**The api does not consume its own ingress, and holds no loop of its own.** It is
an agent with a VAB of `api` (`LLD-bus-and-router` §3.2), so when the router
writes its ingress it kicks the adapter exactly as it would for any window
agent. The adapter reads the VAB, dispatches to the api delivery routine, and
exits. There is no receiver thread here — that is an adapter's job, and the api
is not an adapter.

⚠ A reply may never come. Nothing on the bus guarantees delivery, the agent may
be wedged, and the api must not hold a request open forever waiting — a timeout
that returns "nothing yet" is a correct answer.

**What the api adapter does with a reply is deferred — see §7.** Build 01 is
inject-only: `POST` puts an envelope on the bus and returns `202`, and nothing
comes back on that request.

The reason is worth stating, because it is not a gap in the transport. Every
other agent has a *name*, so the router demultiplexes replies for free — alice's
reply reaches alice because alice is an address. HTTP clients are anonymous and
all share the one name `api`, so the router cannot tell them apart and the
demultiplexing has to happen inside the adapter. That is flow state — a table,
keyed by `correlation_id`, with an expiry — and it is the one piece of this
design that has to remember anything.

## 5. Reading

Straight from Redis, every key built through `prefix()`. A request never names a
key or a queue — the path selects a fixed shape and the agent name fills one
segment.

Reads are point-in-time — no subscriptions, no watches. That applies to *state*;
replies are the separate path in §4 and are the only thing a client ever waits
on.

## 6. Transport & auth

TCP, FastAPI — the clients are browsers and scripts, so a real HTTP surface with
a generated schema is worth having.

A bearer token, checked on every request including reads.

⚠ The token is the only thing between a request and a tenant's bus, so binding
is the security posture. Default to loopback and publish deliberately; a
non-loopback bind with no token set should refuse to start rather than warn.

## 7. Deferred

**Handing a reply back to the client that caused it.** The api adapter's far end
— the opener that hands an envelope to a waiting HTTP request. Two shapes, and
they are genuinely different designs, not two implementations of one:

- **A table** keyed by `correlation_id` with a TTL, held in Redis where the rest
  of the state lives, read by the request handler. Flow state, expiring, visible.
- **Ephemeral agents** — a waiting client enrols as its own short-lived named
  agent, the reply routes to it, and no table exists anywhere. Consistent with
  everything else in the design; costs a roster write path, itself deferred in
  `LLD-bus-and-router` §7.

⚠ Whichever it is, it does not go in the api process's memory. That drains a
durable queue into RAM — invisible, lost on restart, nothing to inspect — which
is the failure `LLD-adapter-tmux` §2 exists to prevent.

**Session endpoints.** Exposing a live agent window is streaming, not REST, so it
is a separate transport question and probably a separate module. Named here only
so the REST surface is not designed around it.

**Per-client identity.** One shared token now.

**TLS.** Not needed on a loopback bind; terminating it outside this process is
likely simpler than inside.

## 8. What this is not

Not the router — it forwards nothing. Not an agent runtime — it does not start,
stop, watch or drive anything. Not a query interface over Redis — every endpoint
is a fixed shape, and a request can never name a key.
