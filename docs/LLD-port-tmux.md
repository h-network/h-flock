# LLD — the tmux port

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address
> scheme, the envelope, and the two doors. One port binary (`flock.port`) per
> delivery; handles agents in tmux windows (`port_type: tmux`) and enrolled REST clients (`port_type: api`).
> Bringing tmux up — the server, the windows, sizing — is a separate module and out of scope here.

## 1. Purpose

An agent in a tmux window is a program at a terminal. It cannot pop a queue, and
nothing can hand it an object — it reads bytes on a screen and writes bytes to a
prompt. This port is what makes such a thing addressable on the bus.

It implements the receiving edge for tmux agents and enrolled REST clients. The
agent-side `office` command is shown for context, but it calls the shared bus
library directly and is not part of `flock.port`:

```
  ┌──────────────────── agent and receiving edge ─────────────────┐
  │                                                               │
  │  send      office command → bus library → own egress          │
  │                                                               │
  │  receive   blocks on ingress, woken by Redis on arrival       │
  │            for port_type=tmux: pops it, opens it, pastes into window │
  │            for port_type=api:  pops it, writes to client mailbox    │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘
```

**Send is a tool, not a loop.** The agent emits by invoking a command (`office
send`, `office broadcast`, `office add`, etc.), the way it invokes anything
else. The tmux host makes that command available in the window and configures it
with the agent's own identity (`AGENT_NAME`), so the shared bus library writes
the right egress without being told. The port is not involved on this side.

**Receive runs outside the window**, because the agent has no way to know an
envelope arrived. Something else has to be waiting on its behalf and deliver it.

## 2. Receiving

**The switch triggers the port. There is no polling loop, and nothing is held
open.** The switch is the only thing that writes an ingress queue, so it is the
only thing that knows an envelope just landed on one. Having written it, it
kicks off delivery for that agent.

```
  switch  ──RPUSH──►  …:backend:ingress
     │
     └──kick──►  port for backend ──► pop ──► open ──► paste into window (port_type=tmux)
                 (runs, delivers, exits)              or write mailbox Stream (port_type=api)

  backend's delivery already in flight?  the envelope stays in the queue
```

The agent is not involved and its state is irrelevant — an idle agent is the
normal case, and it has no way to know anything arrived.

**The port is not a daemon.** It is invoked, atomically snapshot-drains
whatever is currently queued on that destination's ingress queue (via a Redis
Lua script), batches consecutive `Message` envelopes into a single bracketed
paste, and exits. Nothing sits blocked on a queue, no connection is held per
agent, and an office of idle agents costs nothing at all. The alternative — a
long-running consumer per agent, popping eagerly — **moves the backlog into
process memory**: delivery takes hundreds of milliseconds, arrivals are not rate
limited, so a loop draining as fast as it can buffers unboundedly in RAM,
invisible, lost on restart, and with nothing to inspect when it goes wrong.

Triggering on arrival keeps the backlog in Redis, which is the place it should
be. It survives port processes and is visible there, and depth per agent is a
number anything can read. This deployment deliberately disables Redis
persistence, so the backlog does not survive a tenant restart
(`LLD-container` §7).

**One delivery per agent at a time, with opportunistic burst batching.** When the
port runs for an agent, it acquires a busy tag in Redis (`delivering`) via `HSETNX`
to serialize concurrent delivery processes. Upon acquiring the lock, it performs an
**atomic snapshot-drain** of the agent's ingress queue (`LRANGE 0 -1` and `DEL` in
a single Lua script).

- **No fixed time window**: This is an opportunistic snapshot-drain (whatever is
  in the queue at the exact moment the port reads it), not a "collect for N ms"
  buffer. A normal sequential pair of messages with any real gap between them will
  not batch; only genuine near-simultaneous bursts (envelopes arriving while a
  previous delivery held the lock or during port initialization) batch into one
  paste.
- **Message batching**: Consecutive `Message`-kind envelopes are concatenated
  into ONE combined bracketed paste (`[message from X] text\n` per block, in
  arrival order), requiring only a single lock-acquire/paste/lock-release cycle.
- **Commands and Tickets**: Executable `Command` envelopes and `AddTicket`
  mutations are never batched into message blocks; they are executed individually
  in strict arrival order.
- **Per-envelope custody**: Batching is purely a terminal-layer optimization and
  is invisible to the custody chain. Every drained envelope emits its own
  `received` record, writes its own `pending.verify` and `delivery.markers`
  stream entries, and emits its own `opened` record upon successful paste.

Deliveries for *different* agents are independent and overlap freely. A wedged
window blocks only its own agent.

**Agents come and go, and this module does not care.** There is no set of
consumers to keep in step with the roster, because there are no consumers
between deliveries. An agent that joins is deliverable the first time the switch
kicks for it; one that leaves simply stops being kicked. The roster polling that
the switch and the tmux host need (`LLD-bus-and-switch` §3.2) has no equivalent
here.

## 3. Opening & Delivery Routines

`flock.port` checks the destination's port_type in the roster:

- **`port_type: "tmux"` (`deliver_one`)**: dispatches on `kind` to select an opener (`Message`, `Command`, `AddTicket`) and pastes into the agent's window (or mutates the board for `AddTicket`).
- **`port_type: "api"` (`deliver_api`)**: pops the envelope from `ingress`, logs `received` and `opened`, and appends the envelope verbatim as JSON to the client's mailbox Redis Stream (`<prefix>:agent:<client>:inbox`) via `XADD MAXLEN ~ 1000 * envelope '<verbatim JSON>'`. Every kind is stored; nothing dead-letters for being uninteresting.

For a tmux message, the rendered line names the sender:

```
  [message from backend] can you review the auth change?
```

When multiple `Message` envelopes are drained together during a burst, their
rendered lines are concatenated into one combined block in arrival order:

```
  [message from backend] can you review the auth change?
  [message from systems] deployment complete on staging
```

That prefix is the entire reply mechanism. The agent reads a name and replies
with `office send -a <name> <message>` — nothing routes a reply, and nothing
needs to. Combining multiple burst messages into one paste preserves all
content and sender attributions while avoiding back-to-back paste races.

### `Command` — text to run, not text to read

`{"text": "git status"}`. The same window, the same paste sequence in §4, and
one difference that is the whole point: **no `[message from …]` prefix.** The
line is pasted bare, so the shell or the CLI in that window executes it.

That is the only distinction between the two kinds, and it is deliberate — the
prefix is what makes a `Message` inert, because a program reading it sees a
sentence addressed to it rather than an instruction. Remove the prefix and the
same mechanism becomes remote execution.

⚠ **`Command` is arbitrary code execution in an agent's window**, reachable by
anyone who can put an envelope on the bus — which now includes anyone holding
the api's bearer token. `LLD-tmux-host` §4 already says to treat handing out the
tmux socket as handing out the machine; this kind hands out the same thing
through a smaller hole. It is a deliberate capability, not an oversight, and it
is the reason `LLD-api` §6 says the token is not optional.

### `AddTicket` — board mutation, pastes nothing

`{"title": "…", "description": "…", "priority": "…"}`. The `AddTicket` opener
creates a v1 ticket entry in the destination agent's `tasks.todo` Redis list, records
the `add` event via `flock.bus.record_task_event`, and **pastes nothing** into the
window.

⚠ **No window check:** The opener writes for a rostered agent even when its
tmux window is absent. The pulled ticket waits in `tasks.todo` for a later
`office take`; a roster-less destination is rejected by the switch before port
delivery. The returned `RPUSH` list length confirms the synchronous mutation:
success logs `board_write_confirmed`. An exception logs `board_write_unknown`
because the write may have committed before its reply was lost; a returned
non-positive length is provably invalid and logs `board_write_failed`. Both
raise `DeadLetter`.

### Verification and usage-correlation markers

Before pasting a `Message` or `Command` into a `port_type: tmux` window, the
port writes the same marker to two bounded Redis Streams:

- `<prefix>:agent:<name>:pending.verify` via `XADD MAXLEN ~ 100`, for the
  watchdog's delivery-verification pass.
- `<prefix>:agent:<name>:delivery.markers` via `XADD MAXLEN ~ 500`, for the
  activity tailer's heuristic join from a later usage record to the delivery
  that prompted it.

Both entries have this shape:

```json
{ "stream_id": "<stream_id>", "ts": "<ts>" }
```
- **Ordering**: The marker is written *before* the paste sequence into the window. Writing it before paste prevents a sub-second race where a fast agent's reply arrives before the marker lands in Redis.
- **Allowlist `{claude, codex, agy}`**: Markers are recorded only for CLIs on an explicit allowlist (`claude`, `codex`, `agy`). (⚠ **`agy` was added to `VERIFIABLE_CLIS` 2026-08-27** once `~/.gemini/antigravity-cli/history.jsonl` was confirmed live and tailed by `ActivityTailer`.)
- **Confirmed synchronously for `AddTicket`**: `AddTicket` pastes nothing, so it confirms its board write directly and is not verified via activity inputs. It never creates `blocked`; an untaken ticket is normal board state.
- **Skipped for `bash`**: `bash` has no CLI turn records or session activity feed, so markers are skipped to avoid false unverified alerts.
- **Fail-safe**: Marker creation is wrapped in `try...except` so stream write failures never impact envelope delivery.
- **`blocked` state**: The watchdog checks `pending.verify` on its pass, after
  the marker is at least `VERIFY_AFTER_SECONDS` old (default 120 seconds). If
  an agent has produced prior activity and a delivery is unverified with no
  activity produced since, the watchdog writes
  `<prefix>:agent:<name>:blocked`. It catches wedged processes, trust pickers,
  and unauthenticated login prompts. An agent with no prior activity is
  `unknown` and its first delivery is `unjudged` rather than `blocked`.
- **Harness deadline**: `container/sim-blocked.sh` reads the running watchdog's
  `VERIFY_AFTER_SECONDS` and derives its wall-clock poll deadline from that
  value. The verifier window is configuration, not a fixed harness delay.
- **Wedged process simulation**: ⚠ `SIGSTOP` cannot wedge a process running as a tmux pane process — a plain `sleep` started from a shell reaches state `T`, but the same `sleep` started as a tmux pane process never does (it reads back state `S`, and process-group forms fare no better). To simulate an unconsuming wedged window in tests (`container/sim-blocked.sh`), the pane is respawned with a non-consuming process (`respawn-pane -k 'sleep infinity'`) while leaving the agent's launch key as `claude` so the delivery is marked for verification.

## 4. Getting text into a window

The mechanics matter more than they look, and each rule here is load-bearing.

**Paste, do not type.** `load-buffer` then `paste-buffer -p`. Sending the text as
raw keystrokes leaves the TUI inferring typed-versus-pasted from timing, and
under load a following Enter can be folded into the paste as a newline instead
of submitting. Bracketing removes the ambiguity rather than narrowing the window
in which it happens.

**Enter is a separate call.** Combined with the text it is swallowed as
shift+enter by interactive prompts.

**Keep a small delay before Enter.** Sending the paste and Enter together causes
the CLI's input handling to coalesce them into a single input line, swallowing the submit.
The delay is **0.5s**, configured via environment variable `PASTE_ENTER_DELAY` (read into module constant `ENTER_DELAY` in `src/flock/tmux/ops.py`). ⚠ It is **not** a fix for slow
terminals or waiting for the terminal to be ready — it is two distinct writes because
of CLI input coalescing. A shell never shows the difference; a real TUI does.

⚠ **It was 0.15s until build 14** — raised because ours was the outlier by an order of
magnitude against measurements elsewhere for the same CLIs, and because the failure is
silent: the Enter is swallowed, the message sits unsubmitted, and the agent looks idle.

**Newlines inside the brackets are content.** Without them a multi-line message
submits its first line early and arrives split in two.

**Verification never reads the pane and never retries.** Before the paste, the
port writes the two markers described in §3. The watchdog later compares
`pending.verify` with the CLI's own session-file activity events and reports verified,
unverified, or unjudged. A rendered pane is not a data source (the HLD's
*nothing in the data path reads a terminal* invariant),
and an unverified delivery is evidence for an operator rather than permission to
paste the same command again.

## 5. Is it safe to deliver?

For tmux agents, the port checks the window exists before it pastes. If it does not, the
envelope is dead-lettered rather than delivered into nothing.

**Measured: delivery into a busy window is buffered, not lost.** Three messages
pasted while a foreground process held the window were echoed by the terminal,
sat in the tty input buffer, and were read in order the moment the process
exited. Redis stayed clean and the `opened` records were honest. So the failure
this section worried about does not occur by default.

⚠ The residual is volume, not busy-ness: the tty input buffer is finite (~4 KB),
so a long message or a burst arriving during a long task could truncate silently.
And a process that *does* read stdin behaves differently — a real CLI takes the
text straight into its input box, which is what we want, and is why this is a
partial answer.

### The input box is a queue, and a modal is not

Two behaviours found by delivering into live CLIs, which pull in opposite
directions:

**A CLI's input box queues.** Text pasted while the agent is working is held and
picked up when the current turn ends — this is the behaviour the whole design
leans on when it says a message to a busy agent waits rather than being lost. An
`Escape` cancels only the **turn in flight**; anything already queued behind it
still gets picked up afterwards. Observed on agy, and reported as consistent
across claude and codex.

**A modal does not queue — it swallows.** With a picker or approval dialog
focused, a delivered message is *gone*: the text never reaches the input box and
the Enter actions the highlighted row. Verified on agy with a `/model` picker
open — no trace of the message in 2000 lines of scrollback, no reply, and the bus
recorded `opened`. The mechanism is not agy-specific; every CLI here has modals.

⚠ **`Escape` before pasting is not the fix.** It does clear a modal, and a
message delivered immediately after one arrives intact — but against an agent
mid-generation it **aborts the work** (`Interrupted · What should Antigravity CLI
do instead?`). Delivering to a busy agent is the ordinary case and a modal
collision is rare, so it would destroy real work far more often than it rescued a
message. Tested and rejected; see [`TODO.md`](TODO.md).

Beyond that it does **not** try to establish whether the agent is mid-turn.
tmux's `window_activity` is available for a whole tenant in a single
`list-windows -F` call and needs no cooperation from any CLI, so if delivery
gating is ever wanted that is the signal to use — measuring the terminal rather
than the tool, which is what keeps it agnostic. It is not in the first build,
because whether it is needed depends on which CLIs actually misbehave when typed
at while busy, and that is a measurement rather than a design question.

## 6. Talking to tmux

**Subprocess per command.** `tmux load-buffer`, `tmux paste-buffer`, `tmux
send-keys`, each its own call. No protocol to parse, each call fails
independently, and a failure is a return code rather than a stream to resynchronise.

The alternative is a single control-mode client (`tmux -C`), which avoids a fork
per operation and delivers pane output as `%output` events. It is not chosen
here, because its real advantage is streaming a window somewhere, and that
belongs to whatever eventually renders agent windows in an app — not to
delivery. Weigh it there, with that requirement in hand.

Fork cost is not a reason to prefer it. Delivery is a handful of `tmux` calls
against hundreds of milliseconds of paste-and-settle, so the forks are noise
next to the work. And processes spawned this way are waited on and reaped by the
caller — orphan reaping is a container concern, handled by running a real init
as PID 1, and unrelated to this choice.

## 7. Deferred

**Delivery gating** — see §5. Needs measurement first.

**Reading the window back onto the bus** — this remains out of scope. The
session service does read terminal output for human viewers, out of band from
envelope delivery; it does not turn pane output into bus data.

**Session providers** — implemented by the separate `flock.session` module; they
remain outside this port.

## 8. What this is not

Not the tmux host — it does not create the server, the session or the windows,
and it does not decide what runs in them. It attaches to what is already there,
and if a window is missing for `port_type: tmux`, that is a dead-letter, not something to repair.

Not the switch. It never resolves a destination and never writes another agent's
ingress.
