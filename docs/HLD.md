# h-flock — High Level Design

> How the pieces fit. The five LLDs each describe one module in depth and
> [`CONTRACTS.md`](CONTRACTS.md) pins what more than one of them depends on —
> this is the layer in between, which nothing else covered.
>
> Read this before an LLD. Read `CONTRACTS` before changing one.

---

## 1. The one idea

**h-flock is a switch.** Producers emit envelopes; a switch forwards them by
`destination` and never opens one. Everything else follows from that, and the L2
analogy is load-bearing rather than decorative:

| L2 switch | h-flock |
|---|---|
| destination MAC | `destination` — the only thing forwarding depends on |
| source MAC | `source` — **stamped from the egress queue** by the switch before forwarding; a mismatch is corrected and logged |
| MAC table | the **roster** — `name → port_type` |
| port config | the **port_type** — a property of the port, not of the frame |
| ethertype | `kind` — the switch ignores it; an opener at the far edge reads it |
| L3 and above | `payload` — invisible to everything in the middle |

A switch never learns what is plugged into a port. That ignorance is the whole
design: **adding a kind of participant is writing one delivery routine** — not
changing the switch, the bus, or any command. It is why an app became a
first-class participant in one build rather than a subsystem.

## 2. Participants

Everything addressable is a name in the roster. What is *behind* the name is its
**port_type** — the virtual agent base it runs on:

| port_type | is | gets an envelope by |
|---|---|---|
| `tmux` | an AI CLI in a terminal window | having it pasted into the window |
| `api` | an app — web, phone, Telegram bot | having it stored in a mailbox it reads |
| `control` | the tenant's own lifecycle provider (`host`) | acting on it |

⚠ **The switch cannot see this column.** It reads roster *fields*, never values
(the *roster fields, never values* invariant) — so it forwards to a name and something at the far edge decides
what that means. This is structural rather than a convention: the switch has no
code path that could dispatch on port_type even if someone wanted it to.

## 3. The parts

⚠ **Diagram corrected 2026-08-15.** The build-56 rename turned `adapter` into
`port` inside the box and left the borders the old width, so it had been drawn
wrong since. It also predated the v4 wire.

```
  agent window                agent window            app (web / phone / bot)
       │ office send               ▲                    ▲  GET /messages
       │                           │ paste              │  POST /envelopes
       ▼                           │                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  flock.bus.doors.send()   —   builds the v4 frame                       │
  │      256 header bytes  +  opaque JSON body                              │
  └───────────────────────────────────┬─────────────────────────────────────┘
                                      │  ① sent
                                      ▼
                        pod:…:agent:<source>:egress          (list)
                                      │
                                      │  BLPOP across every egress
                                      ▼
  ╔═════════════════════════════════════════════════════════════════════════╗
  ║  SWITCH — reads bytes 0‥255 ONLY.  Never decodes the body.              ║
  ║                                                                         ║
  ║    ② popped         header_record_fields(raw)  — header only            ║
  ║       ttl − 1, hops + 1                        — a splice, body intact  ║
  ║    ③ forwarded      RPUSH ingress                                       ║
  ║    ④ kick_started   Popen flock.port — fire and forget, never waits     ║
  ╚═══════════════════════════════════╤═════════════════════════════════════╝
                                      ▼
                        pod:…:agent:<dest>:ingress           (list)
                                      │  LPOP
                                      ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  flock.port — the FIRST component that parses the body                  │
  │                                                                         │
  │    ⑤ received       HSETNX delivering   ← the ownership tag             │
  │       opener dispatched on port_type                                    │
  │    ⑥ opened         HDEL   delivering                                   │
  └───────────────────────────────┬─────────────────────────────────────────┘
                                  │
                    ┌─────────────┼──────────────┐
                 tmux pane      mailbox        board
                 (paste)        (a stream)     (four lists)
```

**The v4 frame on the wire** — `bus/envelope.py:9‥17`:

```
 byte  0    1              33              65        128     191 194 197      256
       ┌────┬───────────────┬───────────────┬─────────┬───────┬───┬───┬────────┬──────────
       │ v  │ stream_id     │ correlation_id│ source  │ dest  │ttl│hop│reserved│ body …
       │"4" │ 32 hex        │ 32 hex        │ 63 sp   │ 63 sp │ 3 │ 3 │ 59 sp  │ JSON
       └────┴───────────────┴───────────────┴─────────┴───────┴───┴───┴────────┴──────────
       └──────────────── the switch reads ONLY this ────────────────────────┘
                                                                            └── opaque ──
```

⚠ **`reserved` is why the next L2 field is free** — it consumes reserved space,
so `HEADER_WIDTH` stays 256, the body offset does not move, and older readers
still parse the fields they know. Build 73.

⚠ **The six circled records are the whole custody chain**, joined on
`(stream_id, recipient)`. A crash shows up as a stage present with no successor.
⚠ **Broadcast is the exception:** ③ is emitted **once** with `count=N` and
`destination:"all"`, so ③→④ cannot be joined per recipient.

| module | what it is | notes |
|---|---|---|
| `flock.bus` | library — keys, envelopes, `send`/`receive`, roster reads | shared |
| `flock.tmux` | library — windows, and the paste sequence | shared |
| `flock.switch` | **the one daemon** | blocks on every egress; also runs the maintenance pass (§8b) |
| `flock.port` | invoked per delivery, dispatches on port_type, exits | not a daemon |
| `flock.control` | `StartAgent` / `StopAgent` / pause / resume openers | reached only via the bus |
| `flock.tmuxhost` | the tmux server, session, windows | |
| `flock.office` | the one agent-facing command | imports `flock.bus` only |
| `flock.api` | REST — `:8080` | |
| `flock.session` | WebSocket terminals — `:8081` | |

`flock.bus` and `flock.tmux` are the only shared libraries. Nothing else imports
anything else, which is what lets a lane own a module outright. ⚠ **One named
exception:** the port lazily imports `flock.control` to open control kinds —
recorded in `CONTRACTS` §5 rather than left as a rule everybody quietly breaks.

## 4. Why adapters are kicked, not running

**The switch blocks on egress queues; nothing blocks on an ingress queue.**
Agents produce whenever they like, so something must wait on their output. But
the switch *writes* ingress — it already knows an envelope arrived, so waiting on
it would be waiting to be told something it just did. Instead it `RPUSH`es and
spawns `flock.port <agent>` fire-and-forget. The port delivers **one
envelope** and exits.

⚠ **The alternative moves the backlog into RAM.** A long-running consumer per
agent, popping eagerly, drains the Redis backlog into process memory: delivery
takes hundreds of milliseconds, arrivals are not rate-limited, and nothing is
inspectable when it goes wrong. Keeping the backlog in Redis is the point. ⚠ **Durable across port
lifetimes, not across a tenant restart** — Redis runs without persistence by
design (`LLD-container` §7), so a restart empties it.

Consequences worth knowing: an office of idle agents costs nothing, because there
are no processes between deliveries; and a **busy tag** in Redis serialises
delivery per agent, since two adapters pasting into one window would interleave.

### 4a. An agent is addressed by window *name*

The name in `destination` is the tmux window name, which is why two facts that look
like implementation detail are architectural:

⚠ **Window creation is idempotent by name.** A duplicate name makes the target
ambiguous, tmux refuses it, and **every delivery to that agent fails** — the
agent is not slow or blocked, it is unaddressable. The property that matters is
converging on one window with that name, not creating it only once.

⚠ **All-digit names are rejected.** tmux reads `s:2` as window *index* 2, so an
agent named `2` addresses whatever window happens to occupy that slot — and
indices shift as windows are retired.

## 5. How an envelope travels

```
office send -a frontend …        the agent's own command, its only surface
   → …:backend:egress         it writes its OWN queue, never frontend's
   → switch                 pops, resolves frontend in the roster, RPUSHes
   → …:frontend:ingress          and kicks a port
   → port                reads frontend's port_type, dispatches, exits
   → opener                 tmux → paste · api → mailbox · control → act
```

Five log records mark the path — `sent`, `popped`, `forwarded`, `received`,
`opened` — so a lost envelope is locatable rather than merely absent. `sent` from
an agent's own command reaches the log via a file the switch tails, because
`office` runs in a window and its stdout is a pane.

⚠ **No *agent* writes another agent's keys.** Not a queue, not a board, not a
mailbox — it sends an envelope and the far edge writes its own. Build 12
generalised this from queues to every per-agent key, and it is what keeps "who
did this" answerable.

⚠ **The switch does, and that is its job** (`switch/service.py:83`, `:93` push
into a destination's ingress), as does a port writing the board of the agent it
is delivering for. The rule constrains *participants*, not the switch — an
earlier wording said "nothing", which the code contradicts.

## 6. Kinds — the capability list

`kind` says what sort of thing an envelope is. The switch ignores it; an opener
at the far edge reads it. **Adding a capability is adding an opener**, which is
the same sentence as §1 from a different angle.

| kind | opened by | does |
|---|---|---|
| `Message` | `tmux` | `[message from …] <text>` into the window |
| `Command` | `tmux` | pasted bare — **it executes** |
| `AddTicket` | `tmux` | writes a ticket to that agent's board, and **pastes nothing** |
| `StartAgent` | `control` | enrols: roster row, and for a tmux agent a home, window and CLI |
| `StopAgent` | `control` | reverses whatever `StartAgent` created for that port_type |
| `PauseAgent` | `control` | stops the CLI, keeps the agent, its queues and its board |
| `ResumeAgent` | `control` | starts the CLI again and drains what queued while it was paused |

⚠ **An app client's mailbox takes every kind**, not just `Message`. The api does
not decide which kinds are interesting — the same rule that stops the switch
reading payloads. A client filters on `kind` itself.

⚠ **Pause is not retire.** `PauseAgent` leaves the roster row, the queues and the
board intact; envelopes keep arriving and wait. `StopAgent` removes the agent.
Confusing the two loses work.

### Broadcast: two different things with one word

| | reaches | filtered by |
|---|---|---|
| `office broadcast …` | **tmux agents only**, minus you | the command, client-side, on `port_type == "tmux"` |
| an envelope to `destination: "all"` | **every roster row** — agents *and* app clients | nothing |

```bash
office broadcast standup in five                    # colleagues
POST /agents/all/envelopes  {"text":"…"}            # everyone, clients included
```

⚠ **The switch cannot filter a broadcast by port_type and never will.** It fans out
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
landed deliveries, and it catches a paste whose `Enter` was swallowed.

### 8a. `blocked` — the delivery verdict, kept

The switch judges every delivery against a later `input` event. It used to log
that and throw it away; it now retains it as `<prefix>:agent:<n>:blocked` —
**set on unverified, deleted on verified.**

⚠ **`blocked` means: we delivered and it was not consumed.** Not "stuck", not
"unhealthy". Measured on a live tenant, each precondition proved on screen before
delivering: it catches a wedged CLI, and it catches **both** claude and codex
sitting at a login prompt.

⚠ **A delivery is judged only for an agent that has produced activity before.**
An agent that has never spoken is `unknown`, and its delivery is **unjudged** —
neither verified nor blocked, logged as `delivery_unjudged`. Nothing observable
exists at that moment, so a verdict would be invention. The cost is real and
deliberate: **the first delivery to a new agent is never judged.**

⚠ **This paragraph used to describe a gap that does not exist** — that a CLI
records input it never acts on, so a login prompt verifies and `blocked` misses
it. That came from a test asserting an *absence*, which passed whenever the
switch had not yet judged. Waiting for the verdict deterministically, both CLIs
are caught. It was never a property of the system, and it was the only thing that
ever argued for reading a screen.

⚠ **No screen is read to produce it.** An earlier design scraped for our own
pasted marker and was abandoned: a consumed message stays visible in the
transcript, so it marked *healthy* agents blocked, and telling transcript from
input box needs the CLI-render knowledge invariant 7 refuses.

⚠ **The marker is written before the paste, and only for CLIs we can tail.**
Both were bugs. Marking *after* lost a sub-second race — the reply beat the
marker and healthy deliveries read unverified. And the skip rule was a denylist
("not agy"), which marked bare shells that could never confirm anything: a CLI
whose activity cannot be tailed is skipped **by default**, not by having been
remembered.

### 8b. The switch's maintenance pass

The one daemon does more than forward. On a timer, for the whole tenant in one
pass: tail session files into activity, sample presence, judge verify markers,
tail the window log to stdout, and trim what would otherwise grow.

⚠ **Cheap bounded reads only.** Anything that needs to *look* at a terminal is
observation and belongs beside the system, not in it — the switch is the data
path, and a `capture-pane` that hangs would stall forwarding for everyone.

### 8c. The watchdog, and who it tells

Its own process, beside the switch — not a step in the switch's pass, because a
`capture-pane` that hangs would stall forwarding, and the switch is the data
path. It reads the board, presence, window activity and the credential files.

**It speaks only when a ticket is old *and* presence is not working *and* the
window is silent.** Any one alone fires identically for a long build and a wedge,
which is how a lead learns to ignore alerts and then ignores a real one.

⚠ **A missing window counts as silent.** Requiring evidence of silence meant an
agent whose window had gone was never reported at all — the strongest possible
signal read as no signal, because there was nothing left to observe. The alert
now carries `window_missing: true` with a null `no_output_s`. An agent that
cannot be observed is not an agent that is fine.

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
pastes — so an agent holds only what it pulled. ⚠ **One ticket in `doing` is
enforced, not emergent:** the `office take` path refuses when that list is
non-empty (*"you already have one open task"*), so it is an explicit command
rule. The board carries *what*; a message carries *now*.

⚠ **And it is not a Redis-level invariant.** The length check and the later push
are separate commands, so two concurrent `office take` processes could both pass
it. Nothing in the api, control or ticket delivery provides a second layer —
they write `tasks.todo` or only read `doing`.

**Mailboxes.** An app reads its own, by cursor. `POST` returns `202`; a reply, if
one ever comes, arrives later.

⚠ **A reply may never come.** An agent can be busy, stopped, or simply not
answer. Every client must be built for silence, and nothing in the system
promises otherwise.

## 10. One container is one tenant

Redis, the switch, the tmux server, both doors, and one window per **`port_type: tmux`**
agent — in one image that converges when brought up twice. ⚠ **`api` clients and
`host` have no window**, which is the point of the port_type. Redis is internal and
unpublished.

⚠ **The container is the boundary, and nothing inside it is.** Agents run with
`sudo` deliberately. Tools and a clean environment remove the *reason* to go
looking, not the ability — an agent that never encounters a queue, a token or a
roster has no reason to hunt for one.

### 10a. An agent audited us, and the reason was still there

A claude agent was asked who had sent it a message, found no answer at the CLI
layer, and went looking. Its trail, in its own order:

1. **`office send` printed a bus record into its pane** —
   `{"module":"port","event":"sent","stream_id":…,"correlation_id":…}`. Its
   reasoning: envelope ids and a named delivery module are not what a CLI that
   appends to a file emits; they imply a broker with persistent streams
2. its environment named the log — `FLOCK_LOG_FILE`, `POD`, `TENANT`,
   `VIRTUAL_ENV=/opt/flock`
3. `/opt/flock/bin/office` is a four-line console script, so the tool is an
   importable package whose source is on the box
4. it searched for the one internal word we had handed it — `port`
5. `port/runner.py`: `import redis`, and the url — ⚠ **the trail is kept as it
   happened; that file is `port/deliver.py` today**, renamed with `port/cli.py`
   → `port/send.py` so the two adapters say which direction they carry
6. `ps` confirmed `redis-server` independently

⚠ **Step 1 was a reason, and it was ours.** Fixed: `office` sets
`FLOCK_LOG_QUIET` for its own run, so the record reaches the window log the
switch tails (§5) and not the agent's screen. It was redundant output as well as
a signpost.

⚠ **Steps 2 to 6 are the ability, and they are accepted.** An agent in this
container can read `POD`, `TENANT`, `FLOCK_LOG_FILE`, `VIRTUAL_ENV`, the
world-readable framework source, and the process table. We do not hide these and
should not pretend otherwise. The claim in this section is about *reasons*, and
it is only true while nothing hands an agent a thread to pull.

## 11. The invariants

The short list that everything else assumes:

1. **The switch forwards on `destination` alone** — never on content.
2. **`source` is stamped from the queue the envelope was popped from.**
   `send()` writes the header and picks the egress from the same argument, so an
   honest sender always agrees. The switch compares them and, on a mismatch,
   overwrites the claim and logs `source_stamped` with what was claimed.

   ⚠ **This is attribution, not authentication.** It guarantees the name matches
   the queue; it says nothing about which process wrote that queue. Inside one
   container that is the strongest claim available — and the right one, because
   the failure it fixes is *wrong information*: an operator's terminal once
   showed `[message from telegram]` from a client that did not exist.

   ⚠ **Corrected, never dropped.** Dead-lettering a mismatch would let anything
   able to write a queue destroy another agent's traffic.

3. **No AGENT writes another agent's keys** — it sends an envelope. ⚠ The
   switch writes a destination's ingress and `AddTicket` writes a destination's
   board: that is the delivery mechanism, and it is what the rule exists to
   route work *through*.
4. **The switch reads roster fields, never values.** It cannot know a port_type.
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

That is what would make a screen scraper acceptable in a watchdog and
unacceptable in a port. Not the technique — the position.

⚠ **And in the end nothing scrapes.** A scraping `blocked` was designed, built and
abandoned: a consumed message stays visible in the transcript, so it marked
*healthy* agents blocked. The verdict the switch already computed turned out to
be the answer. The rule stands as a rule; it is not describing anything we do.

⚠ **Cite these by name, never by number.** `LLD-bus-and-switch` keeps its own,
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
| [`../clients/`](../clients) | a Telegram bot and a browser UI, built from `API.md` alone |
| [`CONTRACTS.md`](CONTRACTS.md) | what more than one module depends on |
| [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) | addressing, the envelope, the invariants in full |
| [`LLD-port-tmux.md`](LLD-port-tmux.md) | how text actually gets into a terminal |
| [`LLD-tmux-host.md`](LLD-tmux-host.md) · [`LLD-container.md`](LLD-container.md) | windows, and the tenant |
| [`LLD-api.md`](LLD-api.md) · [`LLD-session.md`](LLD-session.md) | the two doors |
| [`TODO.md`](TODO.md) | what is parked, and why |
