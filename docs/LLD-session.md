# LLD — the session

> **Status: design, not code.** Nothing here is implemented yet.
>
> The live view of a tenant's terminals, and the way a human types into one.
> Depends on [`LLD-tmux-host.md`](LLD-tmux-host.md) for the windows it reads.
> It never touches an envelope.

## 1. Purpose

Every other module in this system moves envelopes. This one moves terminal
output. It gives an app the bytes a window is producing, and takes keystrokes
back the other way.

```
  app  ──WebSocket──►  flock.session  ──tmux -C──►  the tenant's tmux server
       ◄──%output────                 ◄────────────
```

**It is not an agent.** The api has an address because agents reply to it —
*"not to be a peer, but to be reachable"* (`LLD-api` §1). Nothing ever replies to
a terminal. So this module has no queue pair, no roster row, no VAB, and nothing
on the bus knows it exists. It never calls `send` or `receive`.

The cleanest way to think about it: **it is the adapter for a human.** The tmux
adapter takes an envelope off a queue and pastes it into a window; this takes a
person's keystrokes off a socket and does the same. Same mechanism, different
origin — one from the bus, one from a browser.

**Its own process and its own port.** Long-lived sockets and per-subscriber
state have nothing in common with the api's request handlers, and a tmux server
dying should not be able to take the api down with it. Separate ports also mean
publishing is one decision per door rather than one for both.

## 2. Reading: one control-mode client

**One `tmux -C` client per tenant, not per window.** Control mode emits
`%output %<pane> <data>` for every pane on the server, so a single connection
covers the whole tenant and the fan-out to subscribers is ours to do in memory.

```
  tmux -C attach                    one client, whole tenant
        │ %output %3 "..."
        ▼
  pane id → agent name              from list-panes, refreshed on %window-add
        │
        ▼
  fan out to subscribers of that agent
```

This is where control mode finally earns its place. `LLD-adapter-tmux` §6
rejected it for *delivery* and said its real advantage — streaming a window
somewhere — *"belongs to whatever eventually renders agent windows in an app —
weigh it there, with that requirement in hand."* The requirement is now in hand,
and delivery keeps using subprocess calls. Both choices stand; they were always
about different jobs.

⚠ `%output` data is escaped by tmux and carries raw terminal bytes including
escape sequences. It is passed through untouched — rendering is the app's
problem, and anything this module does to "clean up" a stream will be wrong for
some TUI.

## 3. Subscriptions

**One socket per app, with a subscribe list.** The app connects once and says
which agents it wants; it can change that without reconnecting.

```json
  → {"subscribe": ["alice", "bob"]}
  ← {"agent": "alice", "data": "<bytes>"}
```

A dashboard showing every window opens one connection rather than one per agent,
and an app showing a single terminal is the same code with a list of one. The
alternative — a connection per agent — pushes N sockets onto the app to save us
a filter we have to write anyway, since one control-mode client already receives
everything.

**A subscriber gets a snapshot first, then the stream.** `capture-pane` for the
current contents, then `%output` from that point, so a terminal opens with
scrollback rather than blank until the next keypress.

## 4. Writing: keystrokes

The same socket carries input, issued as `send-keys` through the same
control-mode client.

**Keystrokes do not go through the bus.** A keypress is not a message. Arrow
keys, `Ctrl-C`, tab completion and escape sequences are not signals between
agents, and one envelope per keypress would be absurd — `LLD-bus-and-router` §8
is explicit that the bus is not a general transport.

⚠ **Input is arbitrary code execution in an agent's window**, exactly like the
`Command` kind. So **read-only is a first-class subscription mode**, declared by
the client and enforced here, not a convention:

```json
  {"subscribe": ["alice"], "mode": "read-only"}
```

Watching the office is the common case and must not carry execution rights. This
is `tmux attach -r` semantics, enforced by us rather than by tmux, because a
control-mode client is privileged by construction.

## 5. Auth

**The same bearer token as the api.** Both are doors into one tenant and a second
scheme would be a second thing to get wrong. Checked once, on connect.

⚠ There are now two write paths into a window — `Command` over the bus, and
keystrokes over this socket — and only the first produces envelope log records.
This module logs **one record per connection**, not per keystroke: who connected,
which agents, read-only or not, and when it closed. Enough to answer "who was
typing in bob's window", without a log line per character.

## 6. Lifecycle

The control-mode client dies when the tmux server does, which under
`LLD-tmux-host` §6 takes every pane with it. There is nothing to recover — the
windows are gone. Reconnect when a server exists again and tell subscribers the
stream broke rather than letting it silently stop.

Nothing here is durable. A dropped connection loses nothing that was not already
lost, because scrollback lives in tmux and a reconnecting client gets a fresh
snapshot.

## 7. Deferred

**TLS.** Same answer as `LLD-api` §7 — terminate it outside this process.

**Per-client identity.** One shared token, as with the api. Which means the
per-connection log record identifies a connection, not a person.

**Resize — decided, and the answer is no.** Windows are a fixed 120×32
(`LLD-tmux-host` §3) and no client may change that. A resize would affect every
other viewer and the agent in the window, so there is no rule about who wins
because nobody gets to. An app renders the size it is given and scrolls or
scales to fit.

## 8. What this is not

Not an agent. No address, no queues, no envelopes, in either direction.

Not the adapter. It never opens an envelope and never reads an ingress queue.

Not a terminal emulator. It moves bytes; rendering them is the app's job.
