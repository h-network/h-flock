# LLD — the tmux host

> **Status: design, not code.** Nothing here is implemented yet.
>
> The module that brings up and maintains the tmux the agents live in. Moving
> envelopes into and out of those windows is
> [`LLD-adapter-tmux.md`](LLD-adapter-tmux.md); this one never touches an
> envelope.

## 1. Purpose

One tmux server, one session per tenant, one window per agent. This module
creates them, keeps them matching the roster, and configures them so that
everything else can assume they are there.

It knows nothing about the bus. It does not read queues, does not deliver, does
not know what an envelope is. Its entire output is "there is a window named
`alice` and something is running in it".

## 2. Headless is the normal state

The server runs detached and **nobody attaches**. That is not a degraded mode —
it is how the office runs, and everything downstream is built for it.

```
  tmux new-session -d          create without attaching
  set -g exit-empty off        server survives its last window closing
```

`exit-empty off` matters more than it looks: without it, removing the last agent
takes the server down.

⚠ **It does not save the session, and the session is what everything depends
on.** A session whose last window closes is destroyed by tmux, and no option
prevents that — `exit-empty off` keeps the *server* running with no sessions in
it, which is not the same thing and is not enough. Every later
`new-window -t <session>` then fails with "no current target", permanently.

This is not theoretical: it is how the first deployment failed. See §5 — it is
the reason reconciliation has an order.

Attaching is an **escape hatch for a human**, not the interface. Nothing may
depend on a client being connected.

## 3. Geometry

The one that bites, because it only appears when no one is looking.

With no client attached, panes get `default-size` — 80×24. Every TUI in the
office renders to that, and anything reading a pane sees 80 columns. Then a
human attaches with a wide terminal, tmux resizes, and every window reflows
underneath whatever was reading it.

```
  new-session -d -x <cols> -y <rows>    an explicit size, not the default
  set -g window-size manual             an attaching client does not resize
```

`window-size` defaults to `latest`, which hands control to whoever attached most
recently. That is the wrong owner once the windows exist to be read by software
rather than looked at.

Also set here, because it is a property of the host rather than of any agent:

```
  set -g history-limit <n>              scrollback per pane
```

Keep it small. Scrollback is per-pane memory across every window in the tenant,
and nothing in this design reads it.

## 4. The socket

Give the server its own socket rather than sharing the default:

```
  TMUX_TMPDIR=<dir>            relocates the default socket's directory
```

`-L <name>` also works but has to be passed on **every** `tmux` invocation
everywhere; `TMUX_TMPDIR` is inherited by children, so the isolation happens
once and nothing else has to remember.

⚠ **Socket access is total.** Anything that can reach it can `send-keys` into any
pane, which is arbitrary code execution as that user. There is no authentication
and no per-window scoping. The directory permissions are the boundary — keep it
owner-only, and treat handing out the socket as handing out the machine.

## 5. Windows

One window per agent, **named after the agent**, so a window is addressable by
the same name the bus uses. That is the only coupling between this module and
the rest: not a shared library, just a naming rule both ends honour.

Windows are **reconciled against the roster**, in both directions — an agent in
the roster with no window gets one, a window with no agent in the roster is
removed. Reconciliation is a repeatable operation, not a one-time setup step, so
running it again after a roster change is the whole mechanism for hiring and
letting go.

⚠ **Create before you kill.** The two directions are not interchangeable in
order. Killing first can empty the session — most obviously on the very first
pass, where the session's own initial window is by definition not an agent — and
an emptied session is destroyed and does not come back (§2). Creating first
means the session always holds at least one window and the destructive half is
never the last thing standing.

Nothing announces a roster change, so this module polls for it like the others.
Having no queue to block on, it polls on a loop of its own, every
`ROSTER_POLL_SECONDS` — the same value the router and the adapter take from the
environment, so all three see the same membership. See `LLD-bus-and-router` §3.2
for why that value is shared, and for the one case where being a poll behind
still hurts: windows should lead routes, so this module reconciling promptly is
what keeps a new agent's first envelope from being dead-lettered.

What runs in the window is configuration, not this module's opinion. It starts
what it is told to start, in the working directory it is told to use, with the
environment it is given.

## 6. Lifecycle

tmux restarts nothing. A window whose process exits stays dead; a server that
dies takes every pane with it.

So supervision lives **above** this module — a service manager or the
container's restart policy. What this module owes that supervisor is
idempotence: bringing the host up when it is already up must be a no-op, and
reconciliation must converge rather than duplicate.

Two consequences for anything downstream:

- A missing window is a real state, not an error to repair from elsewhere. The
  adapter dead-letters into it rather than trying to create one.
- Nothing may assume a window it saw earlier is still there.

## 7. Deferred

**Restart policy for a dead agent.** Whether a window whose process exited should
be relaunched, and how many times before giving up, is a decision that needs
something watching. Not part of bringing the host up.

**Multiple tenants on one host.** One session per tenant is the shape, but
whether one process manages several sessions or one runs per tenant is not
settled and does not need to be yet.

## 8. What this is not

Not the adapter — it never reads a queue, never opens an envelope, never types
into a window.

Not a supervisor. It creates windows and reconciles them; keeping processes
alive is someone else's job.

Not a terminal multiplexer for humans. Attaching is supported because tmux
supports it, not because anything here is designed around a viewer.
