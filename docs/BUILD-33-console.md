# Build 33 — the console

> One web UI for running an office: **who is here, what they are doing, what is
> wrong, what work is open, and a way in.** Three lanes, one page.
>
> **Base on `main`.** Branch `<lane>/build-33-<piece>`, push to origin.
> Everything lands under `clients/web/`.

## 1. It needs no new backend, and that is the point

Every endpoint already exists. **If you find yourself wanting a new one, say so
before building it** — the answer is usually that the data is already there under
another name.

```
  GET  /agents                        roster + presence, everyone
  GET  /agents/{a}                    presence, blocked, queue depths, open ticket
  GET  /agents/{a}/activity/stream    SSE — input / output / tool
  GET  /agents/{a}/messages/stream    SSE — replies
  POST /agents/{a}/envelopes          send (202)
  GET  /board                         every agent's board
  GET  /alerts  ·  /alerts/stream     the watchdog's output
  ws   :8081/session                  terminal bytes, both directions
```

⚠ **`clients/web/` already has a working server and page** — 139 lines of
same-origin proxy, 163 of JS. **Extend it. Do not start again.** It exists
because h-flock sends no CORS headers and browser `EventSource` cannot attach a
bearer token; that reasoning still holds and is in `clients/web/README.md`.

## 2. What it is for

A person opens this to answer, in order:

1. **Is the office healthy?** — alerts, and anyone `blocked`
2. **Who is here and what are they doing?** — presence, live tool calls
3. **What work is open?** — the boards, all agents at once
4. **Let me look / let me in** — the terminal, for one agent

⚠ **Answers are messages, terminals are for watching.** An app must never parse a
terminal to obtain an answer (`HLD` §7). The terminal panel exists so a **person**
can watch and, deliberately, type. Nothing in the UI may read the terminal to
populate the other panels.

## 3. The split

| lane | owns |
|---|---|
| `api` | `server.py` — the WebSocket proxy to `:8081`, auth, and any endpoint gap |
| `bus` | the data panels — agents overview, alerts, boards; polling, SSE, resume |
| `tmux` | the terminal panel — xterm.js, geometry, read-only, and the safety rules |

⚠ **One page, three panels, no framework.** `clients/web/README.md` says why:
no build step, one HTML file, one JS file, a small server. It has to still run in
a year, and a toolchain rots first. Vendor xterm.js as a file; do not add npm.

## 4. `api` — the way in

`server.py` proxies HTTP today. It must also proxy **`:8081/session`**, because a
browser WebSocket cannot attach an `Authorization` header any more than
`EventSource` can, and the token must stay server-side.

- one origin serves page, api and terminal socket
- ⚠ **the token never reaches browser JavaScript.** It is the tenant's api token;
  anything holding it can send `Command` envelopes, which execute
- pass through both directions faithfully — terminal bytes are not JSON and must
  not be re-encoded
- ⚠ **`read-only` is enforced server-side by the session door already**
  (`session/app.py`). The proxy must not weaken it — do not let a client's
  claimed mode override what it subscribed with

## 5. `bus` — the panels that answer questions

**Agents overview.** Every roster row: presence (`working` / `idle` / `unknown` /
`blocked`), VAB, open ticket and its age, last activity. ⚠ **`blocked` must be
visually distinct** — it is the state a person must act on, and `unknown` must
not render as ready.

**Alerts.** `/alerts` for catch-up then `/alerts/stream`. Nothing else surfaces
these to a human. ⚠ **An alert is not an error to be dismissed** — it clears when
the condition clears, so do not build a "mark as read".

**Boards.** `/board` — every agent's four columns. ⚠ Entries may be bare strings
as well as objects (`API.md`); handle both or the panel dies on old data.

⚠ **Reconnect is yours.** SSE drops. Resume from the last cursor, back off, and
never silently stop — a dead stream looks exactly like a quiet office.

## 6. `tmux` — the terminal panel

xterm.js against the proxied session socket, one agent at a time.

- **`read-only` by default.** Typing requires a deliberate switch, and the UI must
  make the current mode obvious
- geometry is **120x32** (`LLD-session`); match it or the render will not line up
- ⚠ **A terminal is a rendering, not a data source.** Do not scrape it for
  presence, replies or anything else. That is invariant 7 and it is the one rule
  in this build that is not negotiable
- two uses worth supporting well: watching an agent work, and **completing an
  interactive login** — device-code OAuth is terminal bytes both ways, which is
  the one path that fixes a `Not logged in` tenant without a shell on the host

## 7. Done when

- one page shows alerts, every agent with live presence, and every board
- clicking an agent streams its activity, and opens its terminal
- a `blocked` agent is unmistakable; an `unknown` one is not shown as ready
- the terminal is read-only until deliberately switched, and works for a login
- the token is not in browser JavaScript — check the page source and say so
- SSE drops and reconnects without losing or replaying
- ⚠ **run it against the lab tenant and paste what you saw.** Unit tests are not
  evidence for a UI

## 8. Reporting

`jira done`, then message `architect` with the paths, what you ran it against,
and anything `API.md` did not tell you — that document is still the contract for
client builders and gaps in it are findings.
