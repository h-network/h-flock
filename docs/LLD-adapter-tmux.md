# LLD — the tmux adapter

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-router.md`](LLD-bus-and-router.md) for the address
> scheme, the envelope, and the two doors. One adapter per kind of agent; this
> is the one for agents that live in a tmux window. Bringing tmux up — the
> server, the windows, sizing — is a separate module and out of scope here.

## 1. Purpose

An agent in a tmux window is a program at a terminal. It cannot pop a queue, and
nothing can hand it an object — it reads bytes on a screen and writes bytes to a
prompt. This adapter is what makes such a thing addressable on the bus.

It implements the two doors for one class of agent, and the two halves are built
differently even though the contract is symmetric:

```
  ┌──────────────────────── tmux adapter ─────────────────────────┐
  │                                                               │
  │  send      a command the agent runs inside its own window     │
  │            builds the envelope, writes its own egress         │
  │                                                               │
  │  receive   blocks on ingress, woken by Redis on arrival       │
  │            pops it, opens it, pastes it into the window       │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘
```

**Send is a tool, not a loop.** The agent emits by invoking a command (`office send`,
`office broadcast`, `office add`, etc.), the way it invokes anything else. The
adapter's only job on that side is to make the command available in the window and
configured with the agent's own identity (`AGENT_NAME`), so it writes the right
egress without being told.

**Receive runs outside the window**, because the agent has no way to know an
envelope arrived. Something else has to be waiting on its behalf and put the
result in front of it.

## 2. Receiving

**The router triggers the adapter. There is no polling loop, and nothing is held
open.** The router is the only thing that writes an ingress queue, so it is the
only thing that knows an envelope just landed on one. Having written it, it
kicks off delivery for that agent.

```
  router  ──RPUSH──►  …:alice:ingress
     │
     └──kick──►  adapter for alice ──► pop ──► open ──► paste into window
                 (runs, delivers, exits)      (paste, delay, Enter, verify)

  alice's delivery already in flight?  the envelope stays in the queue
```

The agent is not involved and its state is irrelevant — an idle agent is the
normal case, and it has no way to know anything arrived.

**The adapter is not a daemon.** It is invoked, it delivers **one envelope**, and
it exits. Nothing sits blocked on a queue, no connection is held per agent,
and an office of idle agents costs nothing at all. The alternative — a
long-running consumer per agent, popping eagerly — **moves the backlog into
process memory**: delivery takes hundreds of milliseconds, arrivals are not rate
limited, so a loop draining as fast as it can buffers unboundedly in RAM,
invisible, lost on restart, and with nothing to inspect when it goes wrong.

Triggering on arrival keeps the backlog in Redis, which is the only place it
should be. It is durable there, it is visible there, and depth per agent is a
number anything can read.

**One delivery per agent at a time, and this is the one thing the kick does not
give for free.** The number of adapters running for alice is the number of kicks
the router fired, so two envelopes arriving close together start two of them.
They do not merely reorder — the tmux calls interleave against one window:

```
  A: paste-buffer -t hq:bob      "[message from alice] …"
  B: paste-buffer -t hq:bob      "[message from carol] …"   appended
  A: send-keys Enter             submits both lines as one input
  B: send-keys Enter             submits an empty prompt
```

`send-keys` targets a window, not a delivery, so nothing separates them. A busy
tag in Redis serialises them: an adapter kicked for an agent that is already
being delivered to **waits for the tag to clear, then delivers its own
envelope**. It does not exit, and nothing drains a backlog on another kick's
behalf. See `LLD-bus-and-router` §3.3 for the tag, and for why a crash leaves it
set on purpose.

Deliveries for *different* agents are independent and overlap freely. A wedged
window blocks only its own agent.

**Agents come and go, and this module does not care.** There is no set of
consumers to keep in step with the roster, because there are no consumers
between deliveries. An agent that joins is deliverable the first time the router
kicks for it; one that leaves simply stops being kicked. The roster polling that
the router and the tmux host need (`LLD-bus-and-router` §3.2) has no equivalent
here.

## 3. Opening

`kind` selects an opener. The opener reads the header to know which window, and
relays the payload without interpreting it.

For a message, the rendered line names the sender:

```
  [message from alice] can you review the auth change?
```

That prefix is the entire reply mechanism. The agent reads a name and replies
with `office send -a <name> <message>` — nothing routes a reply, and nothing
needs to.

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
creates a v1 ticket entry in the recipient agent's `tasks.todo` Redis list, records
the `add` event via `flock.bus.record_task_event`, and **pastes nothing** into the
window.

`AssignTask` is accepted as a deprecated alias (logged via `log_record`).

An envelope whose `kind` has no opener is dead-lettered under **this agent's own
prefix** and logged. The failure happened at this end, and an adapter writing to
the sender's prefix would reach outside its own agent's keys.

## 4. Getting text into a window

The mechanics matter more than they look, and each rule here is load-bearing.

**Paste, do not type.** `load-buffer` then `paste-buffer -p`. Sending the text as
raw keystrokes leaves the TUI inferring typed-versus-pasted from timing, and
under load a following Enter can be folded into the paste as a newline instead
of submitting. Bracketing removes the ambiguity rather than narrowing the window
in which it happens.

**Enter is a separate call.** Combined with the text it is swallowed as
shift+enter by interactive prompts.

**Keep a small delay before Enter.** `paste-buffer -p` only emits the markers
when the application has asked for bracketed paste mode; a CLI that never does
gets the old behaviour, and the delay is what that case still relies on.
**0.15s**, from `PASTE_ENTER_DELAY` — the value h-office settled on in the field
after roughly one delivery in ten was left sitting in an input box. A shell never
shows the difference; a real TUI does.

**Newlines inside the brackets are content.** Without them a multi-line message
submits its first line early and arrives split in two.

**Verify, optionally.** After Enter, check the bottom rows of the pane and press
it again if the text is still sitting there. It is a heuristic — it assumes a
bottom-anchored input box — and a false positive costs one extra Enter that an
empty prompt ignores.

## 5. Is it safe to deliver?

The adapter checks the window exists before it pastes. If it does not, the
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

**Reading the window** — capturing pane output back onto the bus is a different
job with a different shape, and nothing needs it yet.

**Session endpoints** — exposing a live window over HTTP belongs to whatever
serves that, not here.

## 8. What this is not

Not the tmux host — it does not create the server, the session or the windows,
and it does not decide what runs in them. It attaches to what is already there,
and if a window is missing that is a dead-letter, not something to repair.

Not the router. It never resolves a recipient and never writes another agent's
ingress.
