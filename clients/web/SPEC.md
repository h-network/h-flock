# The console — product specification

> The web UI for running an office. Judge it as a product someone pays for, not
> as a demo. this file is the bar. The build spec it was written against has been
> retired. ⚠ **`clients/` is no longer closed to development** — `TODO.md:19` and
> `SPRINTS.md:299-304` record the reversal (2026-08-29, by the operator): clients are
> in active use as the primary user interface and ordinary in-scope work.

⚠ **Status: Parts I–V have all shipped.** Every numbered requirement below —
design tokens, command palette, global search, keyboard shortcuts, density
modes, persisted preferences, desktop notifications, the composer, the audit
trail, `/healthz`/`/readyz`, structured logging, graceful shutdown, a config
file, scrollback search, multi-terminal split/grid, session recording and
replay, the sidebar/hash-routed application shell, and the conversation-first
agent page (§24–26) — is built and present in `clients/web/ui/*.js`,
`clients/web/style.css` and `clients/web/server.py`. This reads like an open
work order because that is what it originally was, written across several
rounds as each prior round shipped; the imperative "build X"/"must" language
below is preserved as the record of what was asked for and why, corrected in
place rather than silently rewritten (`docs/TEST-SIGNOFF.md`'s rule for a
living document). Two specific claims this left behind are corrected below,
at §13 and §27, where they had gone furthest from stating the truth.

⚠ **Treat `src/flock/` as frozen, but not sealed.** The framework is finished for
this build. If the console needs something the api does not offer, **say so
first** — a gap is a finding. Small, reviewed additions are allowed when the
alternative is the client rediscovering what the api already knows.

⚠ **One such change is already in:** `GET /agents/{agent}` returns `port_type`. Use it.
An earlier draft of this rule was absolute, and cost a lane an afternoon nearly
building a probe-every-agent workaround for a field the api now states.

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
  can type it in the terminal, where they can see what they are doing.
  (`clients/telegram` carries one narrow, deliberate exception to this —
  `/run`, a fixed allowlist of native CLI slash commands, not full
  passthrough. See `clients/telegram/README.md` §2h for why that's judged
  different from what this note objects to. No equivalent exists here.)
- one origin for page, api and socket

## 6a. Lifecycle — hiring and retiring, from the UI

An operator should be able to staff an office without a shell.

| action | envelope to `POST /agents/host/envelopes` |
|---|---|
| **hire** | `{"kind":"StartAgent","payload":{"agent":"<name>","port_type":"tmux","cli":"claude","profile":"<optional>"}}` |
| **retire** | `{"kind":"StopAgent","payload":{"agent":"<name>"}}` |
| **pause / resume** | `PauseAgent` / `ResumeAgent`, same shape |

⚠ **Retiring is destructive and must be confirmed** — type the agent's name to
confirm, the way a repository deletion works. `StopAgent` removes the roster row
and purges identity state. It keeps queues and boards, and the UI should say so
in the confirmation, because "will I lose their tickets?" is the first question
anyone asks.

⚠ **Pause is not retire.** Offer both, and make the difference legible: pause
stops the CLI and keeps everything, envelopes queue up and are drained on resume.

⚠ **Validate the name before sending** — lowercase, digits and hyphens, and **not
all digits** (tmux reads `s:2` as window index 2). The api will reject a bad name
but the user deserves to know before the round trip.

⚠ **Hiring is not instant.** The roster row appears immediately; the window,
guide and CLI follow within the reconcile interval. Show the agent as pending
until it appears in `/agents`, and do not present a spinner that implies failure
if it takes a few seconds.

## 6b. The console has no access control, and that is the biggest hole

⚠ **CORRECTED — this is built, all four items below.** `clients/web/server.py`
refuses a non-loopback `--listen` without `HFLOCK_SECRET` configured (item 1),
the shared operator secret sets an opaque `Secure`/`HttpOnly`/`SameSite=Strict`
session cookie (item 2), secret and session-token comparisons are constant-time
with no credential ever in a query string (item 3), and the terminal
WebSocket upgrade is refused without a valid session cookie the same as any
other authenticated route (item 4). `clients/web/README.md`'s "Security
model" section describes the shipped shape; §6b below is the requirement it
was built against, kept for that reason.

⚠ **Anyone who can reach the port has full control of the office.** No login, no
session, nothing. Through this page a stranger can read every message, hire and
retire agents, and **type into a terminal that executes**. The api token being
server-side protects the token, not the office.

It is survivable today only because `--listen` defaults to `127.0.0.1`. That is
one flag away from being wrong, and "we bound it to localhost" is not an answer
anyone buying this will accept.

**What it needs, in order:**

1. **Refuse to serve on a non-loopback interface without authentication.** If
   `--listen` is anything but localhost and no auth is configured, exit with an
   explanation. Do not warn and continue — a warning in a log is how this ships
   by accident
2. **A single shared secret is enough to start.** Not user accounts, not roles —
   one operator credential, checked before anything is served, and a session
   cookie afterwards. `Secure`, `HttpOnly`, `SameSite=Strict`
3. **Constant-time comparison**, and no credential in a query string, ever — it
   lands in logs and history
4. **The terminal socket must be authenticated too.** It is the one that types.
   A cookie is sent on a WebSocket upgrade; use it

⚠ **Say plainly in the README what this is not:** no user identity, no audit of
who did what, no roles. An operator credential answers "may this person in", not
"which person was this". Selling it as more than that would be a lie, and the
gap is worth stating rather than hiding.

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
    mini.html        Telegram Mini App entry — read-only, reuses ui/*.js panels
    mini-app.js       (README's "Telegram Mini App" section)
    README.md        how to run it, and the decisions behind it
    SPEC.md          this
```


---

# Part II — the round that makes it a product

> The first build made it correct and safe. `style.css` is 57 lines and the
> panels are 46–115 each: that is a competent console, not something anyone would
> call polished. This part is explicitly **over-engineering, and it is wanted.**

⚠ **Zero build step still holds.** Everything below is reachable with modules,
custom properties and vendored files. If you think something needs a bundler, say
so and I will decide — do not add one.

⚠ **Nobody can see this.** There is no browser on any host we have. Everything
visual must therefore be *reasoned* and *described*, and anything you cannot
verify must be reported as unverified. Do not claim it looks good.

## 10. `bus` — the surface

**A design system, not ad-hoc CSS.** Custom properties for a spacing scale, a
type scale, elevation, radius and a full semantic colour set for both schemes.
Every panel consumes tokens; no literal colours outside the token block.

**A command palette.** `Ctrl/Cmd-K`: jump to an agent, run a lifecycle action,
open a board, filter alerts. This is how operators actually drive tools they use
daily, and it makes every feature reachable without hunting.

**Global search and filter.** One field that filters agents, alerts and board
tickets at once, with the result counts per panel. At 40 agents and 300 alerts
this is the difference between a tool and a wall.

**Keyboard shortcuts, with a `?` overlay** listing them. No hidden keystrokes:
if it is not in the overlay it does not exist.

**Density modes** — comfortable and compact, remembered. An operator on a laptop
and one on a wall display want different things.

**Preferences that persist** in `localStorage`: density, theme override, last
selected agent, panel sizes. ⚠ Never the secret, never a token.

**Desktop notifications** for new alerts, opt-in, with a mute control. ⚠ An alert
that clears itself must clear its notification — do not notify about something
already resolved.

**A better composer**: multi-line, send on `Ctrl-Enter`, history with up-arrow,
and a clear indication that a reply may never come.

## 11. `api` — the operational surface

**TLS.** `--tls-cert` / `--tls-key`. ⚠ Without it, the operator secret crosses
the network in clear text the moment anyone binds beyond loopback, which §6b
otherwise allows.

**An audit trail.** The README currently admits there is none. Every operator
action — login, logout, hire, retire, pause, resume, message sent, terminal
switched to read-write — appended as structured JSON with timestamp, session id
and source address. ⚠ It answers *what was done from this session*, still not
*which human*; keep saying so.

**`/healthz` and `/readyz`**, unauthenticated and cheap. Ready means the api
behind it answered.

**Structured request logging** as JSON lines, one per request, with a
`--log-format text|json`. The current output is `SimpleHTTPRequestHandler`
noise.

**Graceful shutdown** on `SIGTERM`: stop accepting, drain in-flight terminal
sockets with a close frame, exit within a bounded time.

**A config file** — `--config console.toml` — so nobody ships a systemd unit with
a secret in the command line, visible in `ps`.

## 12. `tmux` — the terminal, properly

**Scrollback search** with match highlighting and next/previous.

**Copy and paste** that behaves: selection copies, paste is blocked in read-only
mode and confirmed for multi-line in read-write, because a pasted newline is an
executed command.

**Font size and scrollback depth**, persisted.

**Multiple terminals at once** — two or four agents side by side. Watching a team
work is the thing a person actually wants from this panel.

**Session recording.** Capture the byte stream with timings and replay it. ⚠ This
is the audit feature that matters for a terminal that can execute, and it is the
one thing here that a customer will ask for by name. Store recordings on the
server, never in the browser.

## 13. What still cannot be claimed

⚠ No one has rendered this. Say "unverified — no browser available" for anything
visual, every time. A build that lies about what it has seen is worth less than
one that admits the gap.

⚠ **CORRECTED — this was rendered.** `clients/web/README.md`'s "Demo and
verification" section records the Part II visual harness run in Chromium,
light and dark, at three viewport sizes, with measured cumulative layout
shift (0.018–0.025) and screenshots inspected for the overview, activity
column and alert history. The caution above held at the time it was written
and stayed true through several rounds after — it stopped being true once
that harness ran, and nothing came back afterward to say so.


---

# Part III — it needs to be an application, not a dashboard

⚠ **This corrects a mistake in my own spec.** Part I said "one page, panels are
independent" and drew four quadrants. You built that faithfully and it is the
problem: four panels squeezed into one window, everything competing, nothing with
room. An operator's tool is an application with places you go, not a wall you
stare at.

## 14. An application shell

**A persistent left sidebar** with sections, and a **hash route per section** so
every view is linkable, bookmarkable and survives a refresh. No build step —
`location.hash` and a switch is enough.

```
  ┌────────────┬──────────────────────────────────────────────────────┐
  │ HF  office │  <the section fills everything, with room to breathe> │
  │            │                                                       │
  │ ▸ Overview │                                                       │
  │ ▸ Agents 6 │                                                       │
  │ ▸ Terminals│                                                       │
  │ ▸ Alerts 0 │                                                       │
  │ ▸ Boards   │                                                       │
  │ ▸ Recordings                                                       │
  │ ▸ Audit    │                                                       │
  │ ▸ Settings │                                                       │
  ├────────────┤                                                       │
  │ ● live     │                                                       │
  └────────────┴──────────────────────────────────────────────────────┘
```

⚠ **Counts and state live in the sidebar** — agents, unread alerts, a live dot.
That is how a person knows to switch section without leaving the one they are in.

## 15. The sections

| route | is |
|---|---|
| `#/overview` | the office at a glance: health, what needs attention, recent activity. The only place a summary belongs |
| `#/agents` | the roster, full width. Selecting one opens `#/agents/<name>` — a **full agent page** with its own tabs: Activity · Terminal · Messages · Board · Lifecycle |
| `#/terminals` | a terminal **workspace**: tabs per open agent, and split/grid as a layout of that workspace rather than a control crammed in a corner |
| `#/alerts` | full page. Filter by kind, severity, agent; group; expand a group to its events |
| `#/boards` | every agent's four columns with room to actually read a ticket |
| `#/recordings` | list recordings, open one, replay it with the transport controls |
| `#/audit` | the audit log, filterable by session, action and agent. It exists; nothing surfaces it |
| `#/settings` | density, theme, notifications, terminal font and scrollback, session info, logout |

⚠ **An agent page is the unit of work**, not a detail pane. When someone is
dealing with a wedged agent they want its activity, its terminal, its messages
and its board in one place, at full size.

## 16. Rules for the shell

⚠ **Every section is reachable by keyboard**, and the command palette jumps
straight to any of them.

⚠ **Deep links must work**: `#/agents/sme-3` opens that agent's page cold, after
a refresh, from a pasted URL. This is how an operator sends a colleague a link to
the thing that is broken.

⚠ **Terminals stay alive across navigation.** Switching to Alerts and back must
not drop the socket or lose scrollback — a terminal is a session, not a view.

⚠ **The typing control must be obvious.** An operator hit the terminal, could not
type, and had no idea why. Read-only is correct as a default; being unable to
discover the switch is not. Put the mode and its toggle where a person looks
first, and say what it does.

⚠ **Nothing shrinks to fit.** If a section needs the window, it takes the window.
The four-panel compromise is what we are removing.


---

# Part IV — the design language, which I never specified

⚠ **Read §1 again: it says "Not chrome."** That was wrong, and it is why this
looks like an internal admin page. I defined enterprise as correctness, safety
and accessibility, then measured only CLS, ARIA counts and console errors — so
that is what got built. Nothing in this document has ever asked for craft in how
it looks. This part does.

⚠ **Correctness is table stakes, not the product.** Everything in Parts I–III
stands. This adds the layer that makes someone believe the thing is finished.

## 17. A type system, not a font

- **one family, three weights** — a system stack is fine, but pick and declare it
- **a modular scale**, declared as tokens: `--text-xs` through `--text-2xl`. No
  literal `font-size` anywhere else
- ⚠ **hierarchy comes from weight and size, not colour.** A page title, a section
  heading and a row label must be distinguishable in greyscale
- **tabular numerals for all numbers** — counts, ages, ticket totals. Numbers
  that jitter as they update look broken
- **line length capped** for prose; nothing runs the full width of a wide screen

## 18. Space and rhythm

- **a spacing scale in tokens** — 4/8/12/16/24/32/48. Never an arbitrary pixel
- ⚠ **whitespace is the difference between cramped and considered.** The current
  build fills every pixel. Sections need generous outer padding and consistent
  gutters, and elements need room to be separate things
- **an 8px baseline grid**, so unrelated components still line up
- **alignment is deliberate**: labels left, numbers right, one axis per column

## 19. Colour with meaning

- **a semantic set**, not a palette: `--surface`, `--surface-raised`, `--border`,
  `--text`, `--text-muted`, `--accent`, and state colours for
  working / idle / unknown / blocked / warning / critical
- ⚠ **state colour is used once per state and nowhere else.** If blocked is red,
  nothing decorative may be red
- **both schemes derive from the same tokens** — no second palette
- **contrast meets WCAG AA**, and state is never carried by colour alone

## 20. Components, consistent everywhere

One implementation each, used everywhere: button (primary / secondary / danger /
ghost), input, select, badge, tag, card, table row, tab, modal, toast, empty
state, skeleton, tooltip.

⚠ **If two sections style the same thing differently, it is a bug.** That
inconsistency is what a person reads as unfinished, even when they cannot say
why.

## 21. Density and data display

- **tables for tabular data.** The roster is a table: sortable columns, aligned
  numbers, a stable row height
- **truncate with intent** — ellipsis plus a title, never a mid-word break
- **relative time at rest, absolute on hover**, everywhere, one implementation
- ⚠ **a number and its label are one unit.** "6" and "participants" must never
  wrap apart

## 22. The moments that carry the product

- **empty states**: an illustration or icon, one line saying what this is, one
  action. A fresh office should look like an invitation, not a failure
- **loading**: skeletons matching the final geometry. Never a spinner in a layout
- **errors**: what failed, what it means, what to do. Never a raw status code
- **destructive confirmations** that state the consequence in words
- **motion**: 120–200ms, ease-out, on state change only. ⚠ **Nothing animates on
  data arriving** — a busy office would never settle

## 23. The bar

⚠ **Would you put a screenshot of this on a pricing page?** That is the test.
Not "does it work" — it works. Whether it looks like something a company sells.

Look at the tools this competes with: Grafana, Datadog, Vercel, Linear, Sentry.
None of them is decorated. They are *composed* — restrained colour, real
typography, generous space, one consistent component set. That is the target.

⚠ **You may not use a CSS framework** (§2 still holds) — but everything above is
custom properties and care, not a dependency.


---

# Part V — we built a tmux viewer and forgot the product

⚠ **The owner's words: "we now have a glorified tmux web interface."** He is
right. The terminal got scrollback search, split panes, recording and replay. The
thing you actually do with an agent — **talk to it** — is a tab buried inside an
agent page.

⚠ **`HLD` §7 says it outright:** *an app must never parse a terminal to obtain an
answer. Answers are messages; the terminal is for watching.* We built the
watching and neglected the answering. The Telegram bot had this right months
before the console did: you typed, tool calls streamed as it worked, a reply
arrived.

## 24. Conversation is the primary surface

`#/agents/<name>` opens **the conversation**, not a dashboard of tabs. Terminal,
board and lifecycle are secondary to it.

```
  ┌─ sme-3 ────────────────────────── ⊘ blocked ── [watch] [board] [⋯] ─┐
  │                                                                     │
  │   you        14:02   can you check the auth change?                 │
  │                                                                     │
  │   sme-3      14:02   ⚙ Read  auth.py                                │
  │                      ⚙ Bash  pytest -q                              │
  │                      ⚙ Edit  auth.py                                │
  │                                                                     │
  │   sme-3      14:04   Fixed — the token check was inverted.          │
  │                                                                     │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │ message sme-3…                                    ⌃⏎ to send  │  │
  └──┴───────────────────────────────────────────────────────────────┴──┘
```

## 25. What the conversation must do

- **activity streams inline, in place** — `⚙ Bash`, `⚙ Read` appearing under the
  agent's turn as it works, collapsing runs (`⚙ Bash ×10`) the way the Telegram
  client already does. ⚠ **Tool names only, never arguments** — the feed has none
  and must not gain any
- **presence drives the composer.** `working` shows the agent is busy;
  `blocked` says plainly *not accepting messages* and why; `unknown` warns a
  reply may never come. ⚠ **Never a spinner implying a reply is due**
- **the reply is a message from `/messages/stream`**, never scraped from the
  terminal
- **history on open** — catch up by cursor, so opening a conversation shows what
  was said before, not an empty box
- ⚠ **who said it must be honest.** `source` is unverified (`HLD` invariant 2),
  so a message from an api client is *claimed* identity. Render agent messages
  and client messages differently, and do not present a source string as proof
  of anything

## 26. Everything else demotes

| was | becomes |
|---|---|
| Terminal, the centrepiece | **watch** — a panel beside the conversation, for seeing it work or completing a login |
| `#/terminals` workspace | stays, for watching several agents at once. Not the way you talk to one |
| Activity as its own tab | folded into the conversation, where it belongs |

⚠ **The overview should open a conversation, not a dashboard.** "Review blocked"
means *talk to the blocked agent*, which is what a person came to do.

## 27. The test

⚠ **Can a person hire an agent, ask it something, watch it work and read the
answer — without ever opening a terminal?** Today they cannot. That is the whole
product, and it is the one path we never built.

⚠ **CORRECTED — this path is built.** `ui/lifecycle.js`'s hire dialog, the
`#/agents/<name>` conversation view's composer (`ui/messages.js`), inline
activity streaming under the agent's turn (`ui/activity.js`, §25's own
requirement), and the reply arriving via `/messages/stream` are all present;
`ui/terminal.js`'s watch panel sits beside the conversation as §26 describes,
not in front of it. This line was the document's own final verdict and the
sharpest claim in it to leave uncorrected once the answer changed.
