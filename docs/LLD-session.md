# LLD — the session

> **Status: built and running.** Published on its own port beside the api.
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
a terminal. So this module has no queue pair, no roster row, no port_type, and nothing
on the bus knows it exists. It never calls `send` or `receive`.

The cleanest way to think about it: **it is the port for a human.** The tmux
port takes an envelope off a queue and pastes it into a window; this takes a
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
  pane id → agent name              from list-panes -s, refreshed on %window-add / %window-close / %window-renamed
        │
        ▼
  fan out to subscribers of that agent
```

This is where control mode finally earns its place. `LLD-port-tmux` §6
rejected it for *delivery* and said its real advantage — streaming a window
somewhere — *"belongs to whatever eventually renders agent windows in an app —
weigh it there, with that requirement in hand."* The requirement is now in hand,
and delivery keeps using subprocess calls. Both choices stand; they were always
about different jobs.

⚠ `refresh_panes()` runs `list-panes -s -t <session>` to map all panes across all
windows in the session (the `-s` flag is essential e.g. for multiple windows), and
refreshes on `%window-add`, `%window-close`, and `%window-renamed` events as well as
on demand during subscription updates.

⚠ `%output` data is octal-escaped by tmux control mode: non-printable characters arrive as a backslash and three octal digits (e.g. ESC as `\033` and `\` as `\\`). This module unescapes octal sequences back into raw bytes (`_unescape_control`) before publishing to subscribers, so terminals interpret ANSI escape sequences rather than rendering them as prose text.

## 3. Subscriptions

**One socket per app, with a subscribe list.** The app connects once and says
which agents it wants; it can change that without reconnecting.

```json
  → {"subscribe": ["backend", "frontend"]}
  ← {"agent": "backend", "data": "<text>"}
```

A dashboard showing every window opens one connection rather than one per agent,
and an app showing a single terminal is the same code with a list of one. The
alternative — a connection per agent — pushes N sockets onto the app to save us
a filter we have to write anyway, since one control-mode client already receives
everything.

**Wire Format & Bytes Encoding:**
- **Terminal Output (`server -> client`):** `{"agent": "<name>", "data": "<text>"}` where `data` is UTF-8 string content containing ANSI control sequences (e.g. `\x1b[2J\x1b[H` screen repaint snapshots or live stdout). Non-ASCII terminal bytes from tmux `%output` are decoded using `utf-8` (`errors="replace"`).
- **Keystrokes (`client -> server`):** `{"agent": "<name>", "data": "<keystrokes>"}` where `data` is raw UTF-8 string keystroke input. The server encodes this string to UTF-8 bytes and forwards it to tmux via `send-keys -H <hex_bytes>`.

**A subscriber gets a snapshot first, then the stream.** `capture-pane` (without `-S -`) captures the visible screen (not the full scrollback history), prefixed with clear-and-home (`\x1b[2J\x1b[H`), followed by the screen lines and cursor position restoration (`\x1b[{row};{col}H` queried via `display-message -p -t <pane> "#{cursor_y} #{cursor_x}"`), so row 1 of the client matches row 1 of the pane and live updates stay aligned without offset.

⚠ `capture-pane` is used exclusively by this module to render visible terminal screen snapshots to human operators over the session door. Observation modules outside the session door (watchdog, switch, adapters) never execute `capture-pane`.

## 4. Writing: keystrokes

The same socket carries input, issued as `send-keys` through the same
control-mode client.

**Keystrokes do not go through the bus.** A keypress is not a message. Arrow
keys, `Ctrl-C`, tab completion and escape sequences are not signals between
agents, and one envelope per keypress would be absurd — `LLD-bus-and-switch` §8
is explicit that the bus is not a general transport.

⚠ **Input is arbitrary code execution in an agent's window**, exactly like the
`Command` kind. So **read-only is a first-class subscription mode**, declared by
the client and enforced here, not a convention:

```json
  {"subscribe": ["backend"], "mode": "read-only"}
```

Watching the office is the common case and must not carry execution rights. This
is `tmux attach -r` semantics, enforced by us rather than by tmux, because a
control-mode client is privileged by construction.

## 5. Auth

**The same bearer token as the api.** Both are doors into one tenant and a second
scheme would be a second thing to get wrong. Checked once, on connect.

**Browser WebSocket Authentication:** Standard browser JavaScript `WebSocket` constructor does not permit setting custom `Authorization: Bearer` headers. Authentication supports both `Authorization: Bearer <API_TOKEN>` headers and `?token=<API_TOKEN>` query parameters (`ws://HOST:8081/session?token=<API_TOKEN>`). Browser applications should pass `?token=<API_TOKEN>` or proxy terminal connections server-side.

**WebSocket Close Codes:**
- `1000`: Normal closure when the client or server ends the socket connection cleanly.
- `4401`: Unauthorized (token missing or invalid). The server accepts the socket and closes with `code=4401, reason="unauthorized"` so client receives close frame.
- `1011`: Internal error (control mode client disconnect or unhandled internal exception).

**Browser WebSocket Authentication & Log Safety:** Standard browser `WebSocket` constructors cannot set custom `Authorization` headers. The session door supports both `Authorization: Bearer <API_TOKEN>` headers and `?token=<API_TOKEN>` query parameters. `uvicorn.run` is invoked with `access_log=False`. ⚠ **That is not sufficient and the claim that it is was wrong.** It silences the access logger only; the handshake line comes from `uvicorn/protocols/websockets/websockets_impl.py`, which logs the path *with* its query string on the error logger. Measured on a running tenant: `INFO: … - "WebSocket /session?token=<REDACTED-TOKEN>" [accepted]`. Until a short-lived ticket replaces the raw token, **a query-parameter connection puts the tenant token in the container log**. Connection logging is handled via structured `_connection_log` JSON records on close which exclude credentials. Server-side proxying (as implemented in `clients/web/server.py`) is the recommended architecture for browser clients.

⚠ There are now two write paths into a window — `Command` over the bus, and
keystrokes over this socket — and only the first produces envelope log records.
This module logs **one record per connection**, not per keystroke: who connected,
which agents, read-only or not, and when it closed. Enough to answer "who was
typing in frontend's window", without a log line per character.

⚠ **TLS**: configured via `SESSION_TLS_CERT` and `SESSION_TLS_KEY` (falling
back to `API_TLS_CERT` / `API_TLS_KEY`), passed as `ssl_certfile` and
`ssl_keyfile` to `uvicorn.run`. A non-loopback `SESSION_BIND` without TLS raises
`RuntimeError` on startup unless `FLOCK_ALLOW_PLAINTEXT=1` is set by the
entrypoint, which is the only component told the published host. Same rule and
same reasoning as the api door — see `LLD-api` §6 and `LLD-container` §3.

## 6. Lifecycle

The control-mode client dies when the tmux server does, which under
`LLD-tmux-host` §6 takes every pane with it. There is nothing to recover — the
windows are gone. Reconnect when a server exists again and tell subscribers the
stream broke rather than letting it silently stop.

Nothing here is durable. A dropped connection loses nothing that was not already
lost, because visible screen state lives in tmux and a reconnecting client gets a fresh
screen snapshot.

## 7. Deferred

**TLS — resolved in Build 36.** Supported via `SESSION_TLS_CERT` and `SESSION_TLS_KEY` (or `API_TLS_CERT` / `API_TLS_KEY`). A non-loopback `SESSION_BIND` without TLS configured refuses to serve.

**Per-client identity.** One shared token, as with the api. Which means the
per-connection log record identifies a connection, not a person.

**Resize — decided, and the answer is no.** Windows are a fixed 120×32
(`LLD-tmux-host` §3) and no client may change that. A resize would affect every
other viewer and the agent in the window, so there is no rule about who wins
because nobody gets to. An app renders the size it is given and scrolls or
scales to fit.

## 8. Not the same thing as the CLI transcripts

Every agent CLI writes its own conversation to disk as JSON — claude, codex and
agy all do, in three different shapes. Those are a
**different stream from this one, and neither replaces the other**:

| | `%output`, here | the CLI's transcript |
|---|---|---|
| carries | raw terminal bytes and escape sequences | structured events — messages, tool calls, results |
| timing | live, as the pane paints | seconds behind, one record at a time |
| shows | what a human sees, half-drawn spinners included | what happened, after it happened |

Measured: a transcript was appended 22 seconds before being read, and carried
tool usage directly (`Bash` 337, `Edit` 51, `Write` 23, `Read` 16).

So an app wanting both a live terminal *and* a readable account of what an agent
is doing needs both feeds. Reconstructing "it ran `Bash`, then `Edit`" from
terminal escape sequences is guesswork; watching a transcript tail is not live.

The Activity Feed is served by `flock.api` (`GET /agents/{agent}/activity` and `/stream`, Build 18), populated by the switch tailing CLI session log files into Redis stream `<prefix>:agent:<agent>:activity`. `flock.session` remains strictly focused on moving live terminal bytes.

## 9. What this is not

Not an agent. No address, no queues, no envelopes, in either direction.

Not the port. It never opens an envelope and never reads an ingress queue.

Not a terminal emulator. It moves bytes; rendering them is the app's job.
