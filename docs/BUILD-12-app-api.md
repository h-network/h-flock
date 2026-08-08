# Build 12 — the return path, so an app can hear back

> Closes the deferral in [`LLD-api.md`](LLD-api.md) §7. The api has had an
> address since build 01 and agents can already reply to it; what has never
> existed is the far end — the thing that hands that reply to a client.
>
> **Base on `main`.** Branch `<lane>/build-12-app-api`, push to origin.

## 1. What is actually missing

The api is **half duplex**, and only the second half is missing:

```
  app ──POST /agents/alice/envelopes──► bus ──► alice's window      ✓ works
  app ◄──────────  ?  ──────────────── bus ◄── office send -a api   ✗ discarded
```

`deliver_api` (`src/flock/adapter/runner.py:19`) pops the envelope and its opener
is `pass`. That was the right placeholder — the addressing was designed, the
delivery routine was left for when there was a client to deliver *to*. There is
now.

⚠ **This is one delivery routine, not a new subsystem.** The routing, the
address, the roster row and the kick all already work and are not touched. VAB
`api` is a port on the switch that currently drops frames; build 12 gives it
somewhere to put them.

## 2. Scope — what belongs on REST

The line, so it does not get argued twice:

| | where | why |
|---|---|---|
| discovery, send, boards, lifecycle | **REST** — already built | request/response, no session |
| **an agent's reply, as data** | **REST** — build 12 | it is a message, not a terminal |
| live terminal output, keystrokes | **session WS `:8081`** — already built | bytes, not messages; a different transport on purpose |

⚠ **An app must never have to parse a terminal to get an answer.** That is the
whole point of this build. `flock.session` streams a TUI for *watching* an agent
work; it is not a data format and a wrapper must not scrape it. A chat view in a
web, phone or Telegram client is built from §3, never from `:8081`.

Out of scope, deliberately: per-client addressing (§6), webhooks, TLS, CORS.

## 3. The surface

**One mailbox and two ways to read it.**

```
GET /messages?after=<cursor>&limit=100    catch-up — returns what you missed
GET /messages/stream                      live — SSE, same objects, as they land
```

Both return envelopes as stored, so an app sees `producer` (who replied), `kind`,
`payload`, `stream_id`, `correlation_id` and the timestamp. **A per-agent chat
view is a filter on `producer`** — no per-agent endpoint, because the mailbox is
one stream of everything addressed to the api.

`after` is the cursor from the last message the client processed; omitting it
means "from the beginning of what is retained". The response carries the cursor
to use next, so a client that crashes resumes without a gap and without
re-reading.

⚠ **SSE, not a WebSocket.** Replies flow one way, and this is a REST door — SSE
is a `GET` that stays open, works through proxies, reconnects on its own with
`Last-Event-ID`, and needs no client library. A second WebSocket would duplicate
`:8081`'s transport for a stream that never needs to send anything back.

⚠ **Streaming is an optimisation over polling, not a separate feature.** Both
read the same mailbox with the same cursor. A Telegram wrapper on a phone network
should poll; a desktop app should stream. Neither is the "real" one, and if the
SSE route is hard, ship `GET /messages` alone and follow with the stream.

## 4. The mailbox

A **Redis Stream**, not a LIST:

```
  <prefix>:agent:api:inbox     XADD on delivery, MAXLEN ~ 1000
```

⚠ **This is the one place a Stream earns its keep, and the reason is the
cursor.** Everything else here is a LIST because a queue is a queue. A mailbox is
not consumed — several clients read the same messages, each at its own position,
and a disconnected client must be able to say "I had up to here". `XRANGE` gives
catch-up from an id and `XREAD BLOCK` gives the SSE loop its wait, both built in.
Rolling that over a LIST means inventing sequence numbers and re-implementing
`XRANGE` by hand. If it turns out a LIST is enough, say so before writing the
sequence counter.

`MAXLEN ~ 1000` caps it. A mailbox nobody drains must not grow forever, and an
app that has been away longer than a thousand messages has lost its place
regardless — say so with a cursor error rather than pretending.

⚠ **Every kind goes in, not only `Message`.** The api does not decide which kinds
are interesting; that is the same rule that stops the router reading payloads.
The client filters on `kind`.

## 5. `deliver_api` stops discarding

Replace the `pass` opener with one that `XADD`s the envelope to the mailbox. That
is the whole change to the adapter — same kick, same `receive`, same log records
(`received`, `opened`).

⚠ Keep the catch-all. Every kind is delivered and stored; nothing dead-letters
for being uninteresting.

## 6. One address now, per-client later

Every app shares the single `api` address, so **every client sees every reply**.
That is fine at this stage and it is the deferral from `LLD-api` §7 — filtering
by client is a later decision, and `StartAgent` hardcoding VAB `tmux`
(`src/flock/control/openers.py:34`) is what would have to change first.

⚠ **Do not solve it here.** The shape it will take is already written down:
ephemeral named agents, so the bus does the demultiplexing and no table exists.
Adding a client-id filter now would build the table shape by accident and make
the real one harder.

What an agent needs to know is unchanged: reply to `api`, the same way it replies
to anyone.

## 7. Done when

- an agent running `office send -a api hello` puts a message in the mailbox
- `GET /messages` returns it with `producer` naming that agent
- `GET /messages?after=<cursor>` returns only what followed, and the same cursor
  twice returns the same thing
- `GET /messages/stream` delivers a message sent while the connection is open
- two clients reading concurrently both see every message
- a non-`Message` kind addressed to `api` is stored, not dropped
- the mailbox stops growing at `MAXLEN`
- both routes require the bearer token and appear in `/restdoc`

## 8. Reporting

`jira done`, then message `architect` with paths, the two routes with their query
parameters and response shape, and status. **The response shape is the contract
the app docs are written against**, so state it exactly.
