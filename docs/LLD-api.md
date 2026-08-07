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
envelope and reading keys.

```
  HTTP ──► api ──► envelope on the bus ──► router ──► agent
             │
             └──► Redis reads (boards, roster, depths)
```

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

`GET /board` walks the roster and pipelines the reads — one round trip, no
keyspace scan, and agents holding nothing still appear.

## 3. Sending

Build a `v=1` envelope with the `recipient` from the path, put it on the bus,
return `202` and the `stream_id`.

It does not report delivery, because it cannot observe it. A client that wants
to know what became of an envelope reads the log by `stream_id`.

## 4. Reading

Straight from Redis, every key built through `prefix()`. A request never names a
key or a queue — the path selects a fixed shape and the agent name fills one
segment.

Reads are point-in-time. No subscriptions, no long-polling.

## 5. Transport & auth

TCP, FastAPI — the clients are browsers and scripts, so a real HTTP surface with
a generated schema is worth having.

A bearer token, checked on every request including reads.

⚠ The token is the only thing between a request and a tenant's bus, so binding
is the security posture. Default to loopback and publish deliberately; a
non-loopback bind with no token set should refuse to start rather than warn.

## 6. Deferred

**Session endpoints.** Exposing a live agent window is streaming, not REST, so it
is a separate transport question and probably a separate module. Named here only
so the REST surface is not designed around it.

**Per-client identity.** One shared token now.

**TLS.** Not needed on a loopback bind; terminating it outside this process is
likely simpler than inside.

## 7. What this is not

Not the router — it forwards nothing. Not an agent runtime — it does not start,
stop, watch or drive anything. Not a query interface over Redis — every endpoint
is a fixed shape, and a request can never name a key.
