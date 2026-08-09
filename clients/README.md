# clients

Two things that talk to an h-flock tenant over HTTP. **Neither is part of the
framework** — they are participants, the same as any app someone else writes.

```
  telegram/   a bot: talk to the architect from your phone
  web/        a browser UI: the office, live
  common/     the thin client both use
```

## The rule these are built under

⚠ **Built from [`docs/API.md`](../docs/API.md) and a token. Nothing else.**

Not from `src/`, not from the LLDs, not by asking someone who knows. That
document claims a stranger can build against h-flock, and until something is
built that way the claim is untested.

⚠ **Every time the docs are not enough, that is a finding — report it, do not
work around it.** A gap silently patched by reading the source is a gap the next
person hits alone.

⚠ **They live here only because there is no shared remote for them yet.** They
are consumers and belong in their own repository; the import boundary is the real
one. Nothing here may be imported by `flock.*`, ever.

## What they demonstrate

| | |
|---|---|
| an app is a **participant** | it enrols, gets a name, and agents reply to it by name |
| answers are **messages**, not screen scrapes | `/messages/stream`, never `:8081` |
| the framework says **what it is doing** | `/activity/stream` — `tool: Bash`, live |
| and **whether it can** | presence: `working` / `idle` / `unknown` / `blocked` |
| a reply **may never come** | every client is built for silence |

## Why the web client includes a server

h-flock sends no CORS headers, so a browser page hosted on another origin is
refused. Browser `EventSource` also cannot attach the Bearer header required by
the SSE endpoints. `web/server.py` serves the page and proxies authenticated API
requests from the same origin, solving both without exposing the token to
browser JavaScript. It is a standard-library server, not another framework
service.
