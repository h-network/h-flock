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
  │  receive   a daemon outside the window                        │
  │            pops ingress, opens the envelope, pastes it in     │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘
```

**Send is a tool, not a loop.** The agent emits by invoking a command, the way it
invokes anything else. The adapter's only job on that side is to make the
command available in the window and configured with the agent's own identity, so
it writes the right egress without being told.

**Receive is a daemon**, because nothing in the window is waiting for anything.

## 2. Receiving

One consumer, per-agent workers:

```
  BLPOP over every ingress in the tenant
        │
        ▼
  hand to that agent's worker ──► open ──► paste into window
        │                          (slow: paste, delay, Enter, verify)
        └──► straight back to BLPOP
```

The pop loop must not do the pasting. Delivery is hundreds of milliseconds —
paste, settle, Enter, verify — and a single loop doing both means a burst to one
agent holds up everyone else's mail behind it. One worker per agent isolates
that: a wedged window blocks only its own queue.

One process, N workers. Per-agent processes would work too and buy nothing.

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

**Open choice.** Two ways, and it is not settled:

- **Subprocess per command.** Simple, no protocol to parse, each call fails
  independently. Costs a fork per operation, and delivery is several operations.
- **One control-mode client** (`tmux -C`). One long-lived process, no per-command
  fork, and pane output arrives as `%output` events — which would also supply the
  activity signal in §5 for free. Costs a stateful line protocol to parse,
  octal-escaped output, and reconnect logic; when it wedges, everything it
  carries wedges together.

Subprocess is the smaller first build. Control mode is the better long-run
answer if fork churn or output streaming turns out to matter.

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
