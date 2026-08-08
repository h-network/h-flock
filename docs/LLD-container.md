# LLD — the container

> **Status: built and running.**
>
> The deployment unit. What the other modules run inside, and how a tenant is
> brought up. It contains no logic of its own.

## 1. One container is one tenant

The tenant is fixed when the container starts and never changes. Everything
inside belongs to it, every key written inside sits under its prefix, and
reaching a different tenant means reaching a different container.

This is a deliberate simplification, not a limit discovered later: co-locating
Redis, the router and the agents means they address each other over loopback,
nothing needs discovery, and the whole tenant starts and stops as one thing.

```
  ┌─────────────── container — tenant hq ──────────────────────┐
  │                                                            │
  │   ┌────────────────────────────────────────────────┐       │
  │   │  redis      loopback only, never published     │       │
  │   └────────────────────────────────────────────────┘       │
  │        ▲              ▲                    ▲               │
  │        │              │                    │               │
  │   ┌────┴────┐   ┌─────┴──────┐      ┌──────┴──────┐        │
  │   │ router  │   │  adapter   │      │     api     │        │
  │   └─────────┘   └─────┬──────┘      └──────┬──────┘        │
  │                       │ send-keys          │               │
  │                 ┌─────▼──────┐             │               │
  │                 │ tmux server│◄─ host module creates       │
  │                 │  windows   │   and reconciles these      │
  │                 └─────┬──────┘             │               │
  │                       │ tmux -C            │               │
  │                 ┌─────▼──────┐             │               │
  │                 │  session   │             │               │
  │                 └─────┬──────┘             │               │
  └───────────────────────┼────────────────────┼───────────────┘
                          │                    │
                    the two published ports, one each
```

## 2. What is inside

| Process | Module | Notes |
|---|---|---|
| redis | — | the bus. Loopback, no persistence needed for a skeleton |
| router | `LLD-bus-and-router` | one per tenant, therefore one per container |
| tmux host | `LLD-tmux-host` | creates the server, session and windows |
| tmux adapter | `LLD-adapter-tmux` | kicked per delivery, pastes into windows, exits |
| api | `LLD-api` | envelopes in, state out |
| session | `LLD-session` | terminal output and keystrokes. Its own port |
| agents | — | one per tmux window, whatever the roster says to run |

## 3. Only doors are published, and each one separately

Redis binds loopback and is **never** port-mapped. It has no authentication in
this build, so exposing it would hand anyone the whole tenant — every queue,
every board, and the ability to write into any agent's ingress directly.

Two processes are reachable from outside, on separate ports:

| | Carries | Publish it when |
|---|---|---|
| `api` | envelopes in, state out | something needs to drive the tenant |
| `session` | terminal bytes and keystrokes | something needs to watch or type |

**Separate ports so publishing is one decision per door**, and so neither module
depends on the other. An app that needs both talks to two base URLs, which costs
it nothing. The alternative — one door proxying the other — would make one module
forward traffic it has no business understanding.

You may want the api reachable and terminals not, or terminals on a private
network while data calls go out. One mapping each rather than one for both.

A single external endpoint is still available later, as a **proxy in front of
both** rather than one module absorbing the other. Nothing here changes for it:
neither process learns the proxy exists, and it is also where TLS belongs
(`LLD-api` §7 — terminate it outside the process). Do it once there is something
to put behind it.

Together they are the entire attack surface, and both take the same token, which
is why it is not optional. ⚠ Both can execute arbitrary code in an agent's
window — the api through the `Command` kind, the session through keystrokes — so
neither is the "safe" one. Everything else talks over loopback and has no reason
to leave the container.

## 4. Identity comes from the environment

The pod and tenant are given at start and are read-only thereafter. Every module
in the container derives its prefix from them, so they are set once, in one
place, and inherited.

An agent's own identity is the same story one level down: each agent's window is
given its name in its environment, so the `send` command it runs knows which
egress to write without being told each time.

The same channel carries the one setting more than one module has to agree on:

| | |
|---|---|
| `POD`, `TENANT` | the prefix every module builds keys from |
| `ROSTER_POLL_SECONDS` | how often the roster is re-read. Default 5 |
| `TMUX_TMPDIR` | where the tenant's tmux socket lives. `/home/ubuntu/.flock/tmux` |

`TMUX_TMPDIR` is inherited rather than passed per invocation, which is the whole
reason `LLD-tmux-host` §4 chose it. It is listed here because anything attaching
to a running tenant needs it and it is otherwise folklore:

```bash
docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux <container> tmux attach -r -t <tenant>
```

⚠ It is **not** `/run/…`. The container runs as `ubuntu`, and `/run` belongs to
root — a socket there cannot be created by the user the agents run as.

`ROSTER_POLL_SECONDS` is here rather than in any module because the router, the
tmux adapter and the tmux host must use one value (`LLD-bus-and-router` §3.2).
Set in one place and inherited, they agree by construction; configured per
module, they agree until someone edits one of them.

## 5. Starting up

Order matters only where a dependency is real:

```
  redis            first — everything else connects to it
  tmux host        creates the server, session and one window per agent
  router           needs redis; subscribe set comes from the roster
  api              needs redis
  session          needs the tmux server; holds one control-mode client
                   the doors last, so neither is reachable before the
                   tenant behind them is up
```

**Bringing the container up twice must be safe.** Reconciliation converges
rather than duplicating, so a restart re-attaches to what is already correct
instead of rebuilding it.

## 6. When something dies

A real init runs as PID 1 so orphaned processes — the children agent CLIs spawn
and abandon — are reaped instead of accumulating as zombies. That is a container
concern and it is solved here rather than in any module.

Beyond that: if a module exits, the container exits, and the restart policy
brings the tenant back. This is deliberately blunt for a skeleton — no
per-process supervision inside, no partial states to reason about. A tenant is
either up or it is not.

## 7. Deferred

**Per-module supervision.** Restarting one module without the tenant is a real
thing to want eventually, and needs a supervisor inside the container. Not for
the first build, where "restart the tenant" is an acceptable answer.

**Redis persistence.** A skeleton loses its queues on restart, which is fine
while nothing depends on a backlog surviving one.

**More than one tenant per host.** Several containers is the obvious answer and
needs no design; what needs design is them reaching each other, which is
cross-tenant routing and already deferred.

## 8. What this is not

Not a module. It runs them and holds nothing of its own — no logic, no state,
no decisions that belong to anything inside it.

Not a general image. It is built to hold exactly one tenant, and the assumption
that there is exactly one is relied upon throughout.
