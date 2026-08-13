# LLD — the api

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-router.md`](LLD-bus-and-router.md) for the address
> scheme and the envelope.

## 1. Purpose

An HTTP front door to a running tenant. A user can already reach an agent by
typing into its window; the api is the other way in — it puts a correctly formed
envelope on the bus, and the router does what it always does.

It also reads state that already exists in Redis: boards, rosters, queue depths, presence, activity feeds, and watchdog alerts.
Terminal output and live driving are handled by the separate `flock.session`
service on port 8081.

That is the whole of it. It has no logic of its own beyond building a valid
envelope, reading keys, and handing back what comes the other way.

```
  HTTP ──► api ──send (with 'as')──► bus ──► router ──► agent
    ▲        │                                             │
    │        └──► Redis reads (boards, roster, depths,     │
    │                         presence, activity, alerts)  │
    │                                                      │
    └──── receive ◄── client inbox ◄── deliver_api ◄─ router ◄─┘  agent replies to client name
```

**It has addresses**, so agents can reply to clients by name. A reply is addressed to
a named client (e.g. `telegram`, or default `api`), the router delivers it to the
VAB `api` adapter, and `deliver_api` writes it to that client's inbox stream. That is the
only reason clients have roster rows — not to be terminal peers, but to be reachable.

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
| `GET` | `/agents/{agent}` | queue depths, presence state (`working`, `idle`, `unknown`, `blocked`), and VAB status (`vab`) |
| `POST` | `/agents/{agent}/envelopes` | put an envelope on the bus, of any kind (optional `as`) |
| `GET` | `/agents/{agent}/messages` | get stored inbox messages for an api client (`?after=<cursor>&limit=100`) |
| `GET` | `/agents/{agent}/messages/stream` | live SSE stream of inbox messages (`?after=<cursor>`) |
| `GET` | `/agents/{agent}/activity` | get stored activity feed events for an agent (`?after=<cursor>&limit=100`) |
| `GET` | `/agents/{agent}/activity/stream` | live SSE stream of activity events (`?after=<cursor>`) |
| `GET` | `/agents/{agent}/board` | that agent's board (`todo`, `doing`, `hold`, `done`) |
| `GET` | `/board` | every agent's board (`todo`, `doing`, `hold`, `done`) |
| `GET` | `/alerts` | get stored watchdog alert events across the tenant (`?after=<cursor>&limit=100`) |
| `GET` | `/alerts/stream` | live SSE stream of watchdog alert events (`?after=<cursor>`) |
| `GET` | `/restdoc` | self-contained API documentation page |
| `GET` | `/docs` | OpenAPI Swagger UI documentation |
| `GET` | `/redoc` | OpenAPI ReDoc documentation |
| `GET` | `/openapi.json` | OpenAPI 3.0 schema specification |

`GET /board` walks the roster and pipelines the reads — one round trip, no
keyspace scan, and agents holding nothing still appear.

## 3. Sending

Build a `v=1` envelope with the `recipient` from the path, `send` it, return
`202` with the `stream_id` and the `correlation_id`.

**The body carries `kind` and `payload`, and the api validates neither.**

```json
POST /agents/host/envelopes    {"kind": "StartAgent", "payload": {"agent": "networking"}}
POST /agents/frontend/envelopes     {"kind": "Message",    "payload": {"text": "hi"}}
POST /agents/frontend/envelopes     {"text": "hi"}          sugar — means kind Message
POST /agents/frontend/envelopes     {"text": "hi", "as": "telegram"}   sending as an enrolled api client
```

The endpoint is `/envelopes`, not `/messages`, because a message is one kind
among several and naming the resource after it made the whole HTTP surface
Message-shaped: the one thing the bus was built to make cheap — adding a kind —
could not be reached over HTTP at all.

A POST request can specify `"as": "<client>"` to declare its producer identity.
`as` is validated against the roster — it must name an enrolled agent with VAB `api`.
When omitted, `producer` defaults to `"api"`.

⚠ **Payload size limit:** Envelopes submitted to `POST /agents/{agent}/envelopes` are bounded at **1 MB (1,048,576 bytes)**. Envelopes exceeding 1 MB are rejected immediately with HTTP `422 Unprocessable Content`.

⚠ **The api must not know what kinds exist.** It builds an envelope and writes
its own egress; which kinds are openable is a fact about adapters, discovered at
the far edge. An api that rejects an unknown `kind` becomes a second place to
update every time one is added, and `LLD-bus-and-router` §5 keeps that knowledge
at exactly one end. An unopenable kind is a dead-letter with a reason, which is
a better answer than a `400` from something that cannot actually know.

It does not report delivery, because it cannot observe it. A client that wants
to know what became of an envelope reads the log by `stream_id`.

## 4. Receiving

**The api does not consume its own ingress, and holds no loop of its own.** It is
an agent with a VAB of `api` (`LLD-bus-and-router` §3.2), so when the router
writes its ingress it kicks the adapter exactly as it would for any window
agent. The adapter reads the VAB, dispatches to the api delivery routine
(`deliver_api`), which pops the envelope, logs `received` and `opened`, and
writes the verbatim JSON envelope into the recipient client's Redis Stream inbox
(`pod:<pod>:tenant:<tenant>:agent:<client>:inbox`, capped at `MAXLEN ~ 1000`) under
the `envelope` field.

⚠ A reply may never come. Nothing on the bus guarantees delivery, the agent may
be wedged, and the api must not hold a request open forever waiting — polling
`GET /messages` or streaming `GET /messages/stream` with a cursor is the correct pattern.

## 5. Reading

Straight from Redis, every key built through `prefix()`. A request never names a
key or a queue — the path selects a fixed shape and the agent name fills one
segment.

- **Board reads** (`GET /agents/{agent}/board` and `GET /board`): Return four columns
  (`todo`, `doing`, `hold`, `done`). Entries are JSON-decoded ticket objects (or raw
  strings for backwards compatibility).
- **Presence & Blocked Status** (`GET /agents/{agent}`): Reads queue depths and VAB (`vab`), alongside presence status hash
  `<prefix>:agent:<name>:presence` (`state`: `working` | `idle` | `unknown`, `since`, `last_activity`).
  Folded over by the router's `blocked` hash `<prefix>:agent:<name>:blocked` when set, so `presence.state` returns `"blocked"`
  when a delivery is judged unverified. An agent that has never produced activity (presence `"unknown"`) has its first delivery
  left **unjudged** (`delivery_unjudged`), so it will never report `"blocked"` until it has spoken at least once.
  Enrolled agents holding no presence hash return `200 OK` with state `"unknown"`.
- **Activity Feed** (`GET /agents/{agent}/activity` and `GET /agents/{agent}/activity/stream`):
  Served from stream key `<prefix>:agent:<name>:activity`, populated by the router tailing CLI session log files.
  Structured events carry `{ "v": 1, "agent": "<name>", "ts": "<ISO>", "kind": "input" | "output" | "tool" [, "tool": "<Name>"] }`.
- **Watchdog Alerts Feed** (`GET /alerts` and `GET /alerts/stream`): Served from tenant stream key
  `<prefix>:alerts`, populated by `flock.watchdog`. Alerts notify human operators (never agents) of stalled
  tickets, wedged processes, or expiring credentials (`{ "v": 1, "ts": "<ISO>", "kind": "stalled"|..., ... }`).
- **Enrolled Membership & 404 Behavior**: Endpoint paths targeting `{agent}` check roster membership (`is_member`).
  An unenrolled agent returns `404 Not Found`. All `{agent}` segment parameters are validated via `keys.prefix()`
  (which rejects reserved names `"pod"`, `"tenant"`, `"agent"`, `"all"`, all-digit names such as `"2"`, and invalid characters).
  An enrolled agent holding no tasks, mailbox messages, activity, or presence returns `200 OK` with empty structures.
  `POST /agents/all/envelopes` is explicitly exempt from roster membership checks because `all` is the reserved broadcast address.

Reads are point-in-time — no subscriptions, no watches. That applies to *state* (boards, roster, queue depths, presence);
replies, activity feeds, and watchdog alerts offer catch-up polling or SSE streams (`GET /messages/stream`, `GET /activity/stream`, `GET /alerts/stream`).

## 6. Transport & auth

TCP, FastAPI — the clients are browsers and scripts, so a real HTTP surface with
a generated schema is worth having.

A bearer token, checked on every request including reads and documentation routes
(`/restdoc`, `/docs`, `/redoc`, `/openapi.json`).

⚠ The token is the only thing between a request and a tenant's bus, so binding
is the security posture. Default to loopback and publish deliberately; a
non-loopback bind with no token set should refuse to start rather than warn.

⚠ **TLS**: `API_TLS_CERT` and `API_TLS_KEY` configure TLS for `flock.api`
(passed as `ssl_certfile` and `ssl_keyfile` to `uvicorn.run`). A non-loopback
`API_BIND` without TLS raises `RuntimeError` on startup — **unless
`FLOCK_ALLOW_PLAINTEXT=1` says something better informed has already judged the
exposure.**

⚠ **Why the escape exists, and why it is not a weakening.** A bind is not an
exposure. In a container this door binds `0.0.0.0` by design and the port
mapping decides whether anything can reach it; the process cannot see that
mapping. Enforcing on the bind alone therefore refuses *every* container — which
is precisely what shipped, and the tenant crash-looped until the judgement moved
to `entrypoint.sh`, which is told the published host. Outside a container
nothing sets the variable and the bind is the exposure. See `LLD-container` §3.

⚠ **Operator Action Log vs Direct API Token Traffic**: The web console server maintains `audit.jsonl` as an **Operator Action Log** recording operations performed through the web proxy. Requests hitting `flock.api` directly using an `API_TOKEN` bypass the web proxy and do not appear in `audit.jsonl`; direct API envelope submissions are tracked in bus/adapter stdout logs and agent activity streams (`GET /agents/{agent}/activity`).

## 7. Return path & deferred items

**Handing a reply back to the client that caused it — resolved in Build 12.** Of the
two shapes originally considered (a correlation table vs. named clients), **named
clients with per-client stream mailboxes** was chosen and built.

The reason: every participant on the bus is a named agent, so an app client
enrolling as a named agent (`StartAgent` with `vab: api`) stays consistent with
the switch design (`LLD-bus-and-router` §1).

- **Mailbox:** `deliver_api` writes incoming envelopes into a per-client Redis Stream
  (`pod:<pod>:tenant:<tenant>:agent:<client>:inbox`, capped at `MAXLEN ~ 1000`) under the
  pinned `envelope` field. The stream entry ID acts directly as the cursor (`cursor`).
- **Reading & Streaming:** Clients retrieve messages via `GET /agents/{client}/messages?after=<cursor>`
  for catch-up, or `GET /agents/{client}/messages/stream?after=<cursor>` for a live
  Server-Sent Events (SSE) stream.
- **Isolation:** `api` clients appear in the roster, but are filtered out of terminal
  agent CLI operations (`office peers` and `office broadcast` select `vab == "tmux"`),
  so terminal agents stay unaware of app clients while allowing replies by name
  (`office send -a telegram ...`).

**Session endpoints.** Answered — it is a separate module, and it is
[`LLD-session.md`](LLD-session.md). The api carries envelopes and state reads;
terminal output and keystrokes are a different transport on a different port,
and nothing about the REST surface is designed around them.

**Per-client identity.** One shared token now (with `as` validated against the roster).

**TLS — resolved in Build 36.** Configured via `API_TLS_CERT` and `API_TLS_KEY`. A non-loopback `API_BIND` without TLS configured refuses to serve.

## 8. What this is not

Not the router — it forwards nothing. Not an agent runtime — it does not start,
stop, watch or drive anything. Not a query interface over Redis — every endpoint
is a fixed shape, and a request can never name a key.

