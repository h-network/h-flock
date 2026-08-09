# Build 29 — two clients

> A Telegram bot and a browser UI, both talking to a tenant over HTTP. They are
> also the exam for [`API.md`](API.md).
>
> **Base on `main`.** Branch `<lane>/build-29-<piece>`, push to origin.
> Everything lands under `clients/` — see [`clients/README.md`](../clients/README.md).

## 1. The rule, before anything else

⚠ **Build from `docs/API.md` and a token. Do not read `src/`, the LLDs, or
`CONTRACTS`.** That document claims a stranger can build against h-flock; nobody
has tested it. You are the stranger.

⚠ **When the docs are not enough, report it — do not look it up.** Every gap you
paper over by reading the source is a gap the next person hits with nobody to
ask. A list of "the docs did not say X" is worth as much as the code.

⚠ **Nothing under `clients/` may be imported by `flock.*`.** The import boundary
is real even though the directory is temporary.

## 2. What both need — `tmux` builds it once

`clients/common/` — a thin client, no framework:

```
  enrol(name)                  StartAgent with vab api, idempotent
  send(to, text, as_=name)     POST an envelope
  messages(after=cursor)       catch-up
  stream_messages(after)       SSE, resuming with Last-Event-ID
  stream_activity(agent)       SSE
  presence(agent)              GET /agents/{a}
  agents()                     the roster
```

⚠ **Persist the cursor to disk.** A bot that restarts and replays its whole
mailbox is worse than one that misses a message. `API.md` documents the cursor —
use it properly, and say so if the document does not make that possible.

⚠ **Reconnect is the client's job.** SSE drops. Resume from the last cursor,
back off, and never silently stop — a client that quietly dies looks exactly like
an agent with nothing to say.

⚠ **Build for silence.** A reply may never come. No timeouts that surface as
errors, no "the agent failed to respond".

## 3. Telegram — `api`

`clients/telegram/`. One chat, one agent: **the architect**.

**The shape, learned from h-cli's bot** — one message, edited in place, not a
stream of new ones:

```
  you:  can you check the auth change?

  ⏳ architect is working
     1. ⚙ Read   auth.py
     2. ⚙ Bash   pytest -q
     3. ⚙ Edit   auth.py
                                    ← ONE message, edited as events arrive

  architect:  Fixed — the token check was inverted. 12 tests pass.
                                    ← the answer, as its own message
```

- **typing** — Telegram's indicator expires after ~5s, so refresh it on a timer
  while presence is `working`. That is why presence is polled and not pushed
- **tool calls** — `/activity/stream`, rendered into the single activity message.
  Names only; there are no arguments in the feed and there should not be
- **the answer** — from `/messages/stream`, posted as its own message
- **`/status`** — presence and the open ticket, from `GET /agents/architect`

⚠ **Rate limits are real.** Telegram will not accept an edit per event. Coalesce:
edit at most once every ~1.5s, and always render the latest state rather than
queueing edits.

⚠ **`blocked` must be visible.** If the architect is `blocked`, say so plainly —
*"architect is not accepting messages right now"* — rather than showing a typing
indicator forever. That is the whole point of the state existing.

## 4. Web — `bus`

`clients/web/`. A small server plus a page. **The server exists to avoid CORS**:
h-flock sends no CORS headers, so a browser on another origin is refused. Serve
the page and proxy the api from one origin and the problem does not arise.

⚠ **Say that in the README.** It is the first thing anyone building a browser
client will hit, and the reason is not their fault.

The page, one screen:

```
  ┌─ office ─────────────┬─ architect ───────────────────────┐
  │ ● architect  working │  you: check the auth change       │
  │ ○ sme-2      idle    │  ⚙ Read auth.py                   │
  │ ⊘ sme-3      blocked │  ⚙ Bash pytest -q                 │
  │ ? lab        unknown │  architect: Fixed — the token …   │
  ├─ alerts ─────────────┤  ┌──────────────────────────────┐ │
  │ sme-2 stalled 14m    │  │ type here…                   │ │
  └──────────────────────┴──┴──────────────────────────────┴─┘
```

- the roster with **live presence**, including `blocked` as its own mark
- click an agent → talk to it; activity streams inline as it works
- **alerts** from `/alerts/stream`, which nothing else surfaces to a human
- boards from `/board` if there is room

⚠ **No build step, no framework.** One HTML file, one JS file, one small server.
It has to still run in a year, and a toolchain is the thing that rots first.

⚠ **Never touch `:8081`.** The terminal door is for rendering a terminal to a
person; it is not where answers come from. If the UI wants a terminal view later,
that is a deliberate separate feature.

## 5. Done when

- the bot holds a real conversation with the architect on the lab tenant
- tool calls appear **while** it works, in one edited message
- typing shows while `working` and stops when it stops
- a `blocked` architect is reported as such, not as a permanent typing indicator
- the web page shows the roster with live presence and one working chat
- both survive an SSE drop and resume without replaying
- both restart without replaying their mailbox
- **a list of everything `API.md` did not tell you**

## 6. Reporting

`jira done`, then message `architect` with what you built, how to run it, and
**the documentation gaps**. ⚠ The gaps are not a footnote — they are half the
point of the build.
