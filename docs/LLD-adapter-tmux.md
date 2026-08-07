# LLD — the tmux adapter

> **Status: design, not code.** Nothing here is implemented yet.
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

**Send is a tool, not a loop.** The agent emits by invoking a command, the way it
invokes anything else. The adapter's only job on that side is to make the
command available in the window and configured with the agent's own identity, so
it writes the right egress without being told.

**Receive runs outside the window**, because the agent has no way to know an
envelope arrived. Something else has to be waiting on its behalf and put the
result in front of it.

## 2. Receiving

**Arrival wakes a blocked consumer. Nothing is triggered, and no envelope is
polled for.** The adapter holds one `BLPOP` per agent. Redis wakes it the
instant the router `RPUSH`es, so the queue itself is the notification — there is
no signal to send and no call between the router and this module.

(The roster *is* polled, by a supervisor loop — see below. Envelopes are not.)

```
  router ──RPUSH──► …:alice:ingress
                          │ wakes
                          ▼
                    BLPOP for alice ──► open ──► paste into window
                          ▲                       (paste, delay, Enter, verify)
                          └───────────────────────────┘
                            blocks again only when done
```

The agent is not involved and its state is irrelevant — an idle agent is the
normal case, and it has no way to know anything arrived.

**Exactly one envelope per agent is ever in flight.** The consumer blocks again
only after its delivery completes, so nothing accumulates in process memory. A
long-running loop that popped eagerly and handed work to an internal queue would
do the opposite: delivery takes hundreds of milliseconds, arrivals are not rate
limited, and the backlog would move from Redis into RAM — invisible, lost on
restart, and with nothing to inspect when it goes wrong.

Keeping it in Redis means it is durable, and depth per agent is a number
anything can read.

Per-agent ordering falls out of the same rule: while alice's delivery is in
flight nothing else pops alice's queue. Deliveries for different agents are
independent and overlap freely.

**One connection per agent** is the cost. For the tens of agents a tenant holds,
that is not a consideration.

**Agents come and go**, so the set of blocked consumers has to follow the
roster. **One supervisor loop owns that set** — it re-reads the roster every
`ROSTER_POLL_SECONDS`, starts a consumer for anyone new, and stops one whose
agent has gone. A consumer only pops, opens and pastes; it never reads the
roster and never starts or stops another consumer.

The ownership matters, and not only for tidiness. If each consumer re-read the
roster on its own `BLPOP` timeout, then an empty roster would mean no consumers,
therefore nothing polling, therefore no way to ever notice the first agent — and
ten consumers waking independently would each see the same new agent and each
start a consumer for it, putting several `BLPOP`s on one ingress queue and
destroying the one-in-flight rule above.

The `BLPOP` timeout is then a separate and much smaller concern: how quickly a
consumer notices it has been told to stop. Membership staleness is the
supervisor's interval, and it is the same value the router and the tmux host
use. See `LLD-bus-and-router` §3.2.

## 3. Opening

`kind` selects an opener. The opener reads the header to know which window, and
relays the payload without interpreting it.

For a message, the rendered line names the sender:

```
  [message from alice] can you review the auth change?
```

That prefix is the entire reply mechanism. The agent reads a name and replies
with the same `send` command it would use anyway — nothing routes a reply, and
nothing needs to.

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

**Newlines inside the brackets are content.** Without them a multi-line message
submits its first line early and arrives split in two.

**Verify, optionally.** After Enter, check the bottom rows of the pane and press
it again if the text is still sitting there. It is a heuristic — it assumes a
bottom-anchored input box — and a false positive costs one extra Enter that an
empty prompt ignores.

## 5. Is it safe to deliver?

The adapter checks the window exists before it pastes. If it does not, the
envelope is dead-lettered rather than delivered into nothing.

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
