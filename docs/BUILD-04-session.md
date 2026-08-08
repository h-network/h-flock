# Build 04 — flock.session

> The design is [`LLD-session.md`](LLD-session.md). This file is the lane split
> and what "done" means.
>
> **Base on `main`.** Branch `api/build-04-session`, push to origin. Done means
> pushed.

## ⚠ Before you touch tmux

**You are an agent living in a tmux window. Bare `tmux` reaches the server you
are running inside**, and a control-mode client is privileged by construction —
it can drive every pane on that server.

```bash
export TMUX_TMPDIR=$(mktemp -d)     # a scratch server, not the office's
```

Develop against a scratch tmux server or against the tenant on the lab host.
See [`BUILD-01-skeleton.md`](BUILD-01-skeleton.md) §2 for what happened the once
this was skipped.

## 1. One lane

**`api` owns this end to end** — `src/flock/session/`, its own process, its own
port. It is a network service with a long-lived transport, which is the shape
that lane already builds.

Nothing else changes. `flock.session` imports `flock.bus` only for `prefix` if
it needs a key at all, and **never** `send` or `receive`: it is not an agent, has
no queue pair and no roster row (`LLD-session` §1).

## 2. What to build

**Read.** One `tmux -C` client per tenant, not per agent. It receives
`%output %<pane> <data>` for every pane on the server; map pane id → agent name
from `list-panes`, refresh on `%window-add` / `%window-close`, and fan out in
memory to whoever subscribed.

**Subscribe.** One WebSocket per app, carrying a subscribe list it can change
without reconnecting:

```json
  → {"subscribe": ["alice","bob"], "mode": "read-only"}
  ← {"agent": "alice", "data": "<bytes>"}
```

New subscriber gets a `capture-pane` snapshot first, then the stream, so a
terminal opens with scrollback rather than blank.

**Write.** Keystrokes on the same socket, issued as `send-keys` through the same
control-mode client. **Not** through the bus — a keypress is not a message
(`LLD-session` §4).

⚠ `mode: "read-only"` is enforced **server side**, not by the client asking
nicely. Input is arbitrary code execution in an agent's window, same as the
`Command` kind.

**Auth.** The same bearer token as the api, checked once on connect.

**Log** one record per connection — who connected, which agents, read-only or
not, when it closed. Not per keystroke.

## 3. Decided already — do not re-litigate

- **120×32, fixed.** No client may resize; it would affect every other viewer and
  the agent in the window (`LLD-tmux-host` §3).
- `%output` bytes are **passed through untouched.** Rendering is the app's job,
  and anything that "cleans up" a stream will be wrong for some TUI.
- Its **own port**, so publishing stays one decision per door. The compose
  mapping is already written and commented out.

## 4. Done when

- an app opens one socket, subscribes to two agents, and sees output from both
- a `Command` sent through the api shows up in the stream within a second
- typing into the socket appears in that agent's window
- a `read-only` subscriber's keystrokes are refused
- killing the tmux server does not take the api down, and the socket reports the
  stream broke rather than silently stopping
- `curl -N` against an SSE endpoint, if you add one, is a nice-to-have not a
  requirement — WebSocket is the contract

## 5. Reporting

`jira done`, then message `architect` with **file paths**, the **contract**
(endpoint, message shapes), and **status**. Verify it is pushed.

⚠ Do not edit another lane's files. If you need something in `flock.tmux` or
`flock.bus`, say so and I will get it frozen first — that gap has cost us twice.
