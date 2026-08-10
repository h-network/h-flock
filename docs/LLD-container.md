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

⚠ **A rebuild is a new office wearing the same name.** Rebuilding a tenant container
(`docker compose up --force-recreate`) restarts the office and destroys all runtime
enrolments (hired agents, external API clients like `telegram` and `web`). Those clients
keep running against a tenant that no longer knows them, causing them to go silently quiet.
**Rule:** Do not rebuild a tenant container someone is actively using. Bring up a second
tenant container instead.

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
| tmux host | `LLD-tmux-host` | creates the server, session and windows for `vab: tmux` entries |
| tmux adapter | `LLD-adapter-tmux` | kicked per delivery; pastes into windows (`vab: tmux`), appends to mailbox stream (`vab: api`), writes pending.verify marker, exits |
| watchdog | `flock.watchdog` | background process; samples presence, tasks, activity; writes alerts for human operator |
| api | `LLD-api` | envelopes in, state out, client mailbox polling & SSE streaming |
| session | `LLD-session` | terminal output and keystrokes. Its own port |
| agents | — | one per tmux window for `vab: tmux` roster entries |

## 3. Only doors are published, and each one separately

Redis binds loopback and is **never** port-mapped. It has no authentication by
default, so exposing it would hand anyone the whole tenant — every queue, every
board, and the ability to write into any agent's ingress directly. Widening
`REDIS_BIND` without a `REDIS_PASSWORD` stops the tenant starting.

### 3.1 A bind is not an exposure

⚠ **This section exists because getting it wrong crash-looped every tenant.**
Build 36 made both doors refuse a non-loopback bind without TLS. But the doors
bind `0.0.0.0` *inside* the container **by design** — that is how a published
port reaches them at all — so the refusal fired on every container that had ever
run, and the deployed tenant looped on
`SESSION_TLS_CERT … required when SESSION_BIND is not loopback`.

What decides whether plaintext leaves the machine is the **port mapping**
(`API_HOST`, `SESSION_HOST`), and no door process can see it. So the judgement
is made in one place that is told:

- compose passes the published host in, per door
- `entrypoint.sh` refuses **before starting anything** when a door is published
  beyond loopback with no cert and no `ALLOW_PLAINTEXT_PUBLISH=1`
- having decided, it exports `FLOCK_ALLOW_PLAINTEXT=1` and the doors stop
  second-guessing a bind they cannot interpret

Outside a container nobody has judged anything, the variable is unset, and the
door's own bind check is the right one. **The rule generalises:** a check
belongs where the decision is made, not where its consequence lands.

Two processes are reachable from outside, on separate ports:

| | Carries | Publish it when |
|---|---|---|
| `api` | envelopes in, state out, client mailboxes | something needs to drive the tenant |
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
given its name in its environment, so the `office send` command it runs knows which
egress to write without being told each time.

The same channel carries the one setting more than one module has to agree on:

| | |
|---|---|
| `POD`, `TENANT` | the prefix every module builds keys from |
| `ROSTER_POLL_SECONDS` | how often the roster is re-read. Default 5 |
| `ACTIVITY_POLL_SECONDS` | how often activity session files are tailed. Default 2 |
| `AGENT_PROFILES` | agent account profile assignments (`agent=profile,...`) |
| `TMUX_TMPDIR` | where the tenant's tmux socket lives. `/home/ubuntu/.flock/tmux` |
| `REDIS_BIND`, `REDIS_PASSWORD` | Redis bind host (`127.0.0.1`) and password. Non-loopback bind requires `REDIS_PASSWORD` |

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
  tmux host        creates the server, session and one window per tmux agent
  router           needs redis; subscribe set comes from the roster
  watchdog         needs redis; samples presence, tasks, activity; writes alerts
  api              needs redis
  session          needs the tmux server; holds one control-mode client
                   the doors last, so neither is reachable before the
                   tenant behind them is up
```

**Bringing the container up twice must be safe.** Reconciliation converges
rather than duplicating, so a restart re-attaches to what is already correct
instead of rebuilding it.

Enrolling an external application client (`StartAgent` with `vab: "api"`) adds a roster row only, creating no window or CLI process.

### Entrypoint CLI Defaulting & Credential Verification

- **Default CLI initialization:** `setup.sh` writes `AGENT_CLIS` only for agents that differ from the default CLI (`claude`). Therefore, a single-account default install passes no `AGENT_CLIS` environment variable. `container/entrypoint.sh` explicitly defaults every tmux agent's `launch` key in Redis (`pod:<pod>:tenant:<tenant>:agent:<name>:launch`) to `claude` before exception maps (`AGENT_CLIS`, `AGENT_PROFILES`) are applied. Without this explicit default, a default install writes no `launch` keys, `tmuxhost` builds every window as a bare shell, and the office comes up as bash prompts with presence `unknown`.
- **`seed-home.sh check` credential verification:** `seed-home.sh check` inspects profile credentials. It checks actual token expiration timestamps (`refreshTokenExpiresAt` or `expiresAt`) rather than just non-empty file existence. Previously, a 281-byte credential file with an expiry of zero reported `"logged in"` while every agent sat at `"Not logged in · Run /login"`. `seed-home.sh check` now parses the credential JSON and reports `"logged in"`, `"EXPIRED"`, `"UNREADABLE"`, or `"NEEDS LOGIN"`.

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
