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

Out of scope, deliberately: webhooks, TLS, CORS, per-client *authentication* (§6).

## 3. The surface

**A client is a named participant with its own mailbox**, read two ways:

```
POST /agents/host/envelopes   {"kind":"StartAgent",
                               "payload":{"agent":"telegram","vab":"api"}}

GET /agents/telegram/messages?after=<cursor>&limit=100   catch-up
GET /agents/telegram/messages/stream                     live — SSE
```

Sending as yourself rather than as "the api":

```
POST /agents/alice/envelopes  {"text":"…", "as":"telegram"}
```

`as` names an **enrolled** client and is validated against the roster — VAB `api`
only. Omitted, it stays `api`, so everything built before this still works.

⚠ **`as` is a declaration, not an authentication.** One shared token means any
holder can claim any enrolled name. That is no weaker than today — `producer` is
already forgeable ([`TODO.md`](TODO.md)) — and checking it against the roster at
least stops names being invented. Per-client tokens stay deferred (§6).

Messages come back as stored: `producer` (who replied), `kind`, `payload`,
`stream_id`, `correlation_id`, timestamp. **A per-agent chat view is a filter on
`producer`.**

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

A **Redis Stream** per client, not a LIST:

```
  <prefix>:agent:<client>:inbox     XADD on delivery, MAXLEN ~ 1000
```

One per participant, exactly like `ingress` — an `api` client is an address on
the switch like any other, so its mailbox is a resource on its own key, not a
shared bucket everyone sifts.

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

## 6. `StartAgent` takes a `vab`

One line today: `r.hset(roster_key, agent, "tmux")`
(`src/flock/control/openers.py:34`). It becomes `payload.get("vab", "tmux")`,
accepting `tmux` or `api`, rejecting anything else.

⚠ **A VAB `api` enrolment creates no window and starts no CLI.** `StartAgent`
means "enrol, make a home, start the CLI" for a tmux agent; for an `api` client
it is the roster row and nothing else. `StopAgent` likewise removes the row and
the mailbox. Getting this wrong tries to `tmux new-window` for a phone app.

**This is why per-client addressing is cheap rather than expensive**, and it is
the piece I had wrong when scoping: agent-facing views already filter on VAB.
`office peers` and `office broadcast` both select `vab == "tmux"`
(`cli.py:124,137,280`), so enrolled clients are invisible to agents — they do not
appear in anyone's peer list and never receive a broadcast. The isolation this
needs was built two builds ago for a different reason.

It also makes the reply mechanism identical for apps and agents. An agent sees
`[message from telegram]` and replies with `office send -a telegram` — reply by
name, the same rule as everyone. Nothing about an app is special from the window
side, which is the whole L2 idea: the switch does not know what is plugged into a
port.

**Still deferred:** per-client tokens. One shared token, and `as` is checked
against the roster rather than proven.

## 7. Done when

- `StartAgent` with `vab: api` adds a roster row and **creates no window**
- `office peers` in an agent's window does not list that client
- `office broadcast` does not reach it
- an agent running `office send -a telegram hello` puts a message in telegram's
  mailbox and **not** in another client's
- `GET /agents/telegram/messages` returns it with `producer` naming that agent
- `?after=<cursor>` returns only what followed, and the same cursor twice returns
  the same thing
- `/messages/stream` delivers a message sent while the connection is open
- `POST … {"as":"telegram"}` makes alice's window show `[message from telegram]`
- `as` naming a non-enrolled or tmux-VAB agent is rejected
- a non-`Message` kind addressed to a client is stored, not dropped
- `StopAgent` removes the roster row and the mailbox
- the mailbox stops growing at `MAXLEN`
- both routes require the bearer token and appear in `/restdoc`

## 8. Reporting

`jira done`, then message `architect` with paths, the two routes with their query
parameters and response shape, and status. **The response shape is the contract
the app docs are written against**, so state it exactly.
