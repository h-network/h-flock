# h-flock — High Level Design

> How the pieces fit. The five LLDs each describe one module in depth and
> [`CONTRACTS.md`](CONTRACTS.md) pins what more than one of them depends on —
> this is the layer in between, which nothing else covered.
>
> Read this before an LLD. Read `CONTRACTS` before changing one.

---

## 1. The one idea

**h-flock is a switch.** Producers emit envelopes; a router forwards them by
`recipient` and never opens one. Everything else follows from that, and the L2
analogy is load-bearing rather than decorative:

| L2 switch | h-flock |
|---|---|
| destination MAC | `recipient` — the only thing forwarding depends on |
| source MAC | `producer` — derived from the queue it was popped from, never from content |
| MAC table | the **roster** — `name → VAB` |
| port config | the **VAB** — a property of the port, not of the frame |
| ethertype | `kind` — the router ignores it; an opener at the far edge reads it |
| L3 and above | `payload` — invisible to everything in the middle |

A switch never learns what is plugged into a port. That ignorance is the whole
design: **adding a kind of participant is writing one delivery routine** — not
changing the router, the bus, or any command. It is why an app became a
first-class participant in one build rather than a subsystem.

## 2. Participants

Everything addressable is a name in the roster. What is *behind* the name is its
**VAB** — the virtual agent base it runs on:

| VAB | is | gets an envelope by |
|---|---|---|
| `tmux` | an AI CLI in a terminal window | having it pasted into the window |
| `api` | an app — web, phone, Telegram bot | having it stored in a mailbox it reads |
| `control` | the tenant's own lifecycle endpoint (`host`) | acting on it |

⚠ **The router cannot see this column.** It reads roster *fields*, never values
(the *roster fields, never values* invariant) — so it forwards to a name and something at the far edge decides
what that means. This is structural rather than a convention: the router has no
code path that could dispatch on VAB even if someone wanted it to.

## 3. The parts

```
   agent window          agent window              app (web / phone / bot)
        │  office send        ▲                          ▲   GET /messages
        ▼                     │ paste                    │        │ POST
   ┌─────────┐                │                     ┌────┴────────▼───┐
   │ egress  │            ┌───┴────┐                │   api  :8080    │
   └────┬────┘            │adapter │                └────┬────────────┘
        │                 └───▲────┘                     │
        ▼                     │ kick                     ▼
   ╔═════════════════════════════════════════════════════════════════╗
   ║  ROUTER — pops every egress, resolves the name, writes ingress  ║
   ╚═════════════════════════════════════════════════════════════════╝
                              │
                       ┌──────┴───────┐
                  ingress          mailbox            board
                  (a queue)        (a stream)         (four lists)
```

| module | what it is | notes |
|---|---|---|
| `flock.bus` | library — keys, envelopes, `send`/`receive`, roster reads | shared |
| `flock.tmux` | library — windows, and the paste sequence | shared |
| `flock.router` | **the one daemon** | blocks on every egress; also runs the maintenance pass (§8b) |
| `flock.adapter` | invoked per delivery, dispatches on VAB, exits | not a daemon |
| `flock.control` | `StartAgent` / `StopAgent` / pause / resume openers | reached only via the bus |
| `flock.tmuxhost` | the tmux server, session, windows | |
| `flock.office` | the one agent-facing command | imports `flock.bus` only |
| `flock.api` | REST — `:8080` | |
| `flock.session` | WebSocket terminals — `:8081` | |

`flock.bus` and `flock.tmux` are the only shared libraries. Nothing else imports
anything else, which is what lets a lane own a module outright.

## 4. Why adapters are kicked, not running

**The router blocks on egress queues; nothing blocks on an ingress queue.**
Agents produce whenever they like, so something must wait on their output. But
the router *writes* ingress — it already knows an envelope arrived, so waiting on
it would be waiting to be told something it just did. Instead it `RPUSH`es and
spawns `flock.adapter <agent>` fire-and-forget. The adapter delivers **one
envelope** and exits.

⚠ **The alternative moves the backlog into RAM.** A long-running consumer per
agent, popping eagerly, drains a durable queue into process memory: delivery
takes hundreds of milliseconds, arrivals are not rate-limited, and nothing is
inspectable when it goes wrong. Keeping the backlog in Redis is the point.

Consequences worth knowing: an office of idle agents costs nothing, because there
are no processes between deliveries; and a **busy tag** in Redis serialises
delivery per agent, since two adapters pasting into one window would interleave.

## 5. How an envelope travels

```
office send -a frontend …        the agent's own command, its only surface
   → …:backend:egress         it writes its OWN queue, never frontend's
   → router                 pops, resolves frontend in the roster, RPUSHes
   → …:frontend:ingress          and kicks an adapter
   → adapter                reads frontend's VAB, dispatches, exits
   → opener                 tmux → paste · api → mailbox · control → act
```

Five log records mark the path — `sent`, `popped`, `forwarded`, `received`,
`opened` — so a lost envelope is locatable rather than merely absent. `sent` from
an agent's own command reaches the log via a file the router tails, because
`office` runs in a window and its stdout is a pane.

⚠ **Nothing writes another agent's keys.** Not a queue, not a board, not a
mailbox — it sends an envelope and the far edge writes its own. Build 12
generalised this from queues to every per-agent key, and it is what keeps "who
did this" answerable.

## 6. Kinds — the capability list

`kind` says what sort of thing an envelope is. The router ignores it; an opener
at the far edge reads it. **Adding a capability is adding an opener**, which is
the same sentence as §1 from a different angle.

| kind | opened by | does |
|---|---|---|
| `Message` | `tmux` | `[message from …] <text>` into the window |
| `Command` | `tmux` | pasted bare — **it executes** |
| `AddTicket` | `tmux` | writes a ticket to that agent's board, and **pastes nothing** |
| `StartAgent` | `control` | enrols: roster row, and for a tmux agent a home, window and CLI |
| `StopAgent` | `control` | reverses whatever `StartAgent` created for that VAB |
| `PauseAgent` | `control` | stops the CLI, keeps the agent, its queues and its board |
| `ResumeAgent` | `control` | starts the CLI again and drains what queued while it was paused |

⚠ **An app client's mailbox takes every kind**, not just `Message`. The api does
not decide which kinds are interesting — the same rule that stops the router
reading payloads. A client filters on `kind` itself.

⚠ **Pause is not retire.** `PauseAgent` leaves the roster row, the queues and the
board intact; envelopes keep arriving and wait. `StopAgent` removes the agent.
Confusing the two loses work.

### Broadcast: two different things with one word

| | reaches | filtered by |
|---|---|---|
| `office broadcast …` | **tmux agents only**, minus you | the command, client-side, on `vab == "tmux"` |
| an envelope to `recipient: "all"` | **every roster row** — agents *and* app clients | nothing |

```bash
office broadcast standup in five                    # colleagues
POST /agents/all/envelopes  {"text":"…"}            # everyone, clients included
```

⚠ **The router cannot filter a broadcast by VAB and never will.** It fans out
over roster *fields*, and by that same invariant it cannot read a value — so `all` means
all. `office broadcast` selects tmux agents *before* sending, which is why the
two differ. If you want colleagues, use the command; if you address `all`, expect
an app to receive it.

## 7. Two doors, and what each is for

| | | |
|---|---|---|
| **api** | `:8080` | envelopes in, messages and state out — REST, bearer token |
| **session** | `:8081` | terminal output and keystrokes — WebSocket |

Separate processes and separate ports, so publishing one is a decision that does
not drag the other with it.

**The split is by consumer, not by transport:**

| | for | shape |
|---|---|---|
| **api** `:8080` | **programs** | deterministic, data-driven — envelopes in, structured messages and state out |
| **session** `:8081` | **people** | a window onto a terminal, rendered for a human to read and type into |

⚠ **An app must never parse a terminal to obtain an answer.** `:8081` is not a
data format. Answers are messages and they come from the mailbox. That line is
why an app is a participant rather than a spectator, and it is the single most
important rule for anyone building a client.

⚠ **But `:8081` is not off-limits to an app** — it is how an app shows a *person*
what an agent is doing. Two legitimate uses: watching an agent work, and
completing an interactive login. Device-code OAuth is exactly terminal bytes in
both directions, so an agent whose credential has died can be re-authenticated
from a web or desktop client with no shell on the host at all.

⚠ **This sits inside invariant 7, not outside it.** The rule is *nothing in the
**data path** reads a terminal; observation may look, and may only report* — and
rendering a terminal for a person is neither. A human reading a login prompt and
typing a code is the case where somebody *should* be looking at the pane.

⚠ Both doors can execute code in an agent's window — the api through the
`Command` kind, the session through keystrokes. Neither is the safe one.

## 8. Observation — what the system knows about itself

Delivery is one half. The other is **being able to say what happened**, and it is
built from files the CLIs write themselves rather than from anything rendered.

| | source | answers |
|---|---|---|
| **activity** | the CLI's own session JSONL, tailed | what is this agent doing — `input`, `output`, `tool` |
| **presence** | recency of activity | `working` / `idle` / `unknown` |
| **verify** | a delivery marker vs a later `input` | did that message land |
| **the window log** | a file `office` writes, tailed | `sent`, which otherwise dies in a pane |

⚠ **All four read files, never screens.** A session JSONL is the CLI's own data
format and survives its releases; a rendered pane does not. That is invariant 7
and it is why this exists at all.

⚠ **`unknown` is not `idle`.** An agy agent and a bare shell write no session
file, so nothing can be said about them — and saying `idle` would be a lie a
client renders as "ready".

⚠ **Activity carries tool *names*, never arguments.** The feed is designed to
leave the tenant over HTTP; a `Bash` argument is a command line and a `Write`
argument is file content. There is no field they could occupy.

⚠ **Verify reports and never retries.** Measured: no false positives across six
landed deliveries, and it catches a paste whose `Enter` was swallowed. It does
**not** catch a message eaten by an open modal — the CLI writes an `input` record
anyway. That hole is known and open.

### 8a. `blocked` — the delivery verdict, kept

The router judges every delivery against a later `input` event. It used to log
that and throw it away; it now retains it as `<prefix>:agent:<n>:blocked` —
**set on unverified, deleted on verified.**

⚠ **`blocked` means: we delivered and it was not consumed.** Not "stuck", not
"unhealthy". It catches a trust picker and a wedged process, and **misses a CLI
that records input it does not act on** — a login prompt or a modal picker.
Measured twice, and the only gap a screen read would ever be for.

⚠ **No screen is read to produce it.** An earlier design scraped for our own
pasted marker and was abandoned: a consumed message stays visible in the
transcript, so it marked *healthy* agents blocked, and telling transcript from
input box needs the CLI-render knowledge invariant 7 refuses.

### 8b. The router's maintenance pass

The one daemon does more than forward. On a timer, for the whole tenant in one
pass: tail session files into activity, sample presence, judge verify markers,
tail the window log to stdout, and trim what would otherwise grow.

⚠ **Cheap bounded reads only.** Anything that needs to *look* at a terminal is
observation and belongs beside the system, not in it — the router is the data
path, and a `capture-pane` that hangs would stall forwarding for everyone.

### 8c. The watchdog, and who it tells

Its own process, beside the router — not a step in the router's pass, because a
`capture-pane` that hangs would stall forwarding, and the router is the data
path. It reads the board, presence, window activity and the credential files.

**It speaks only when a ticket is old *and* presence is not working *and* the
window is silent.** Any one alone fires identically for a long build and a wedge,
which is how a lead learns to ignore alerts and then ignores a real one.

```
  <prefix>:alerts   →   GET /alerts, /alerts/stream, and the log
```

⚠ **It alerts a human, and never an agent.** "Reports, never repairs" constrains
the watchdog and says nothing about what an agent does next — and an agent told
something is wrong will try to fix it. Worse, a lead messaging a stalled agent
produces the activity that resets the silence timer, so **the alert would clear
its own symptom** with nothing fixed.

The lead has the other half: `office status`, a **pull**, and a guide telling it
to check before assigning and hold work rather than repair.

## 9. Two things that are pulled, not pushed

**Boards.** A ticket waits until an agent asks. Nothing notifies, nothing
pastes — so an agent holds only what it pulled, which is *why* it has at most one
ticket in `doing` rather than a rule imposed on it. The board carries *what*; a
message carries *now*.

**Mailboxes.** An app reads its own, by cursor. `POST` returns `202`; a reply, if
one ever comes, arrives later.

⚠ **A reply may never come.** An agent can be busy, stopped, or simply not
answer. Every client must be built for silence, and nothing in the system
promises otherwise.

## 10. One container is one tenant

Redis, the router, the tmux server, both doors, and one window per agent — in one
image that converges when brought up twice. Redis is internal and unpublished.

⚠ **The container is the boundary, and nothing inside it is.** Agents run with
`sudo` deliberately. Tools and a clean environment remove the *reason* to go
looking, not the ability — an agent that never encounters a queue, a token or a
roster has no reason to hunt for one.

## 11. The invariants

The short list that everything else assumes:

1. **The router forwards on `recipient` alone** — never on content.
2. **`producer` is derived from the queue**, never taken from the envelope.
3. **Nothing writes another agent's keys** — it sends an envelope.
4. **The router reads roster fields, never values.** It cannot know a VAB.
5. **Adapters do not exist between deliveries.**
6. **The api does not validate `kind`** — which kinds are openable is a fact
   about adapters, discovered at the far edge.
7. **Nothing in the data path reads a terminal.** Delivery is `paste → Enter`,
   with no branching on what a pane says. **Observation may look, and may only
   report** — out-of-band, on its own schedule, never in the path an envelope
   travels.

⚠ **The split in 7 is the philosophy, not a caveat.** Communication and data
processing stay deterministic: same inputs, same result, no dependence on how a
CLI happens to render. Anything that needs to *look* — is the message sitting
unsubmitted, is a modal open, is this agent stuck — runs beside the system and
hands back a report. It can be as ugly as it needs to be, because nothing
depends on it being right for a message to be delivered.

That is what makes a screen scraper acceptable in a watchdog and unacceptable in
an adapter. Not the technique — the position.

⚠ **Cite these by name, never by number.** `LLD-bus-and-router` keeps its own,
longer list — *roster fields, never values* is its **8** and this document's
**4**. Two lists with two numberings drift the moment either gains an entry, and
a stale citation reads as authoritative.

⚠ **Breaking any of these is a design change, not a patch**, and they decay
quietly rather than loudly. `CONTRACTS` promised board transitions were an atomic
`LMOVE`; build 11 gave tickets a `status` and a `started_ts`, so the value pushed
stopped being the value popped and `LMOVE` became impossible. Nothing failed —
the code was correct, the contract was not — and nobody noticed until a
documentation audit went looking for exactly this kind of claim.

## 12. Where to go next

| | |
|---|---|
| [`API.md`](API.md) | building an app against it — no repository needed |
| [`CONTRACTS.md`](CONTRACTS.md) | what more than one module depends on |
| [`LLD-bus-and-router.md`](LLD-bus-and-router.md) | addressing, the envelope, the invariants in full |
| [`LLD-adapter-tmux.md`](LLD-adapter-tmux.md) | how text actually gets into a terminal |
| [`LLD-tmux-host.md`](LLD-tmux-host.md) · [`LLD-container.md`](LLD-container.md) | windows, and the tenant |
| [`LLD-api.md`](LLD-api.md) · [`LLD-session.md`](LLD-session.md) | the two doors |
| [`PLAN-boards.md`](PLAN-boards.md) | the board, and why it is pulled |
| [`TODO.md`](TODO.md) · [`SPRINTS-next.md`](SPRINTS-next.md) | what is parked, and why |
