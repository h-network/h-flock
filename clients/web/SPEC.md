# The console — product specification

> The web UI for running an office. Judge it as a product someone pays for, not
> as a demo. [`BUILD-33`](../../docs/BUILD-33-console.md) has the lane split and
> the endpoints; this file is the bar.

⚠ **Nothing in `src/flock/` may change.** The framework is finished for this
build. If the console needs something the api does not offer, **say so and work
around it** — a gap is a finding, not a licence to edit h-flock.

## 1. What "enterprise" means here

Not chrome. These, in order:

| | |
|---|---|
| **it never lies** | a stale panel that looks live is worse than an error. Every panel shows its own freshness |
| **it survives the network** | drops, reconnects, resumes. Never silently stops |
| **it degrades honestly** | one dead panel does not take the page down |
| **it is legible under load** | 40 agents, 300 alerts, a board with 200 tickets |
| **it is operable by someone who did not build it** | no folklore, no hidden keystrokes |
| **it is safe** | the token never reaches the browser; write access is deliberate |

## 2. Zero build step — a decision, not a limitation

⚠ **No npm, no bundler, no framework.** Vendor what you need as files.

This is defensible commercially and you should be able to defend it: no supply
chain to audit, no lockfile to rot, no toolchain to reinstall in three years, it
runs offline in an air-gapped tenant, and a customer can read every line shipped.
Modern browsers have modules, `fetch`, `EventSource`, `WebSocket`, CSS grid and
custom properties. That is enough.

**You may** split into ES modules, vendor xterm.js, and write as much CSS as the
job needs. **You may not** add a step between the source and the browser.

## 3. The screen

One page. Panels are independent — each fetches, refreshes and fails alone.

```
┌─ office ──────────────────────────────┬─ detail ─────────────────────────────┐
│ ● architect  working   #a3f 12m       │  [ activity | terminal | messages ]  │
│ ○ sme-2      idle                     │                                      │
│ ⊘ sme-3      blocked   ← act on this  │  ⚙ Bash · 12:04:11                   │
│ ? lab        unknown                  │  ⚙ Read · 12:04:13                   │
│                                       │                                      │
├─ alerts ──────────────────────────────┤                                      │
│ ⚠ credential  claude  absent          │  ┌────────────────────────────────┐  │
│ ⚠ stalled     sme-2   14m             │  │ message…                  send │  │
├─ board ───────────────────────────────┴──┴────────────────────────────────┴──┤
│ todo 4   doing 2   done 51   hold 1      ▸ per agent, expandable             │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 4. States every panel must have

⚠ **These are the difference between a demo and a product.** A panel with only a
success state is not done.

- **loading** — first fetch, distinguishable from empty
- **empty** — "no alerts" is a *good* state and should read as calm, not broken
- **error** — what failed, when, and a way to retry. Never a blank box
- **stale** — connected but not receiving. Show the age of the last update
- **disconnected** — reconnecting, with attempt count and backoff visible

## 5. Correctness rules that are not style

⚠ **`blocked` is the state a person must act on.** It must be unmistakable
without colour alone — colour-blind users and monochrome screenshots both.

⚠ **`unknown` is not `idle`.** Never render it as ready. An agent with no
readable feed may never reply, and the UI saying "ready" makes a user wait for
something that cannot come.

⚠ **A reply may never come.** No spinner that implies one is due; no timeout
presented as an error.

⚠ **Board entries may be bare strings or objects.** Handle both.

⚠ **The terminal is a rendering for a person.** Nothing in the UI may read it to
populate another panel. Answers come from `/messages`, presence from `/agents`.

⚠ **Never poll where a stream exists**, and never stream where one `GET` will do.
`/alerts/stream` and `/activity/stream` are streams. Presence is a poll —
Telegram's own indicator expiring is why.

## 6. Safety

- the api token stays server-side. **Check the served page for it and report what
  you found** — that token can send `Command` envelopes, which execute
- the terminal is **read-only until deliberately switched**, and the current mode
  is always visible
- `Command` is not exposed in the UI at all. If a user wants to run something they
  can type it in the terminal, where they can see what they are doing
- one origin for page, api and socket

## 7. Quality bar

- **keyboard operable** — every action reachable, focus visible, escape closes
- **a screen reader can use it** — labels, roles, live regions for alerts
- **responsive to 1280×720 minimum**, laid out with grid rather than fixed pixels
- **dark and light**, following `prefers-color-scheme`
- **no layout shift** when data arrives — reserve space
- **60fps with 300 alerts** — virtualise or cap, and say which
- **every timestamp is absolute on hover, relative at rest**

## 8. Testing, and what counts as evidence

- a `--demo` mode serving fixtures, so the UI can be exercised without a tenant.
  This is also how you test the states in §4
- **run it against the lab tenant and paste what you saw.** Unit tests are not
  evidence for a UI
- ⚠ the lab tenant currently has **no credentials** — agents read `Not logged in`
  and presence will be honest about it. Everything except a live agent reply is
  testable there
- kill the api mid-stream and show the panel reconnecting. That is the test that
  matters most and the one nobody runs

## 9. What ships

```
  clients/web/
    server.py        same-origin proxy: http + ws, token stays here
    index.html
    app.js           entry; ES modules from here
    ui/*.js          panels, one file each
    vendor/          xterm.js and anything else, as files
    style.css
    README.md        how to run it, and the decisions behind it
    SPEC.md          this
```
