# LLD — the container

> **Status: built and running.**
>
> The deployment unit. What the other modules run inside, and how a tenant is
> brought up. It owns deployment plumbing and startup validation, but no
> envelope-routing or delivery logic.

## 1. One container is one tenant

The tenant is fixed when the container starts and never changes. Everything
inside belongs to it, every key written inside sits under its prefix, and
reaching a different tenant means reaching a different container.

This is a deliberate simplification, not a limit discovered later: co-locating
Redis, the switch and the agents means they address each other over loopback,
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
  │   │ switch  │   │    port    │      │     api     │        │
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
| redis | — | the bus. Loopback, AOF persistence enabled; ephemeral transport queues purged at boot (BUILD-63) |
| switch | `LLD-bus-and-switch` | one per tenant, therefore one per container |
| tmux host | `LLD-tmux-host` | creates the server, session and windows for `port_type: tmux` entries |
| `flock.port` | `LLD-port-tmux` | kicked per delivery; pastes into windows (`port_type: tmux`), appends to mailbox stream (`port_type: api`), writes pending.verify marker, exits |
| watchdog | `flock.watchdog` | background process; samples presence, tasks, activity; writes alerts for human operator |
| api | `LLD-api` | envelopes in, state out, client mailbox polling & SSE streaming |
| session | `LLD-session` | terminal output and keystrokes. Its own port |
| agents | — | one per tmux window for `port_type: tmux` roster entries |

## 2.1 The custody log outlives the container

⚠ **Container stdout is Docker's `json-file` driver, and it is deleted with the
container.** Until 2026-08-22 a `docker compose down` destroyed the only record
that a run had happened — the failure `TEST-SIGNOFF` still carries as its worked
REFUSED example, *"evidence /tmp/b77-build.log — torn down, no sha256"*.

| | |
|---|---|
| **`FLOCK_CUSTODY_FILE`** | `/home/ubuntu/.flock/custody/custody.jsonl`, set by `container/entrypoint.sh` before the first record and never unset |
| **volume** | named `<project>-custody`, so `down` keeps it and only an explicit `down -v` clears it |
| **`docker logs` cap** | `json-file`, `max-size: 50m`, `max-file: 5` — it was uncapped and grew until the container was removed |

**What is in the file:** a byte copy of every record that reaches container
stdout, for that container's lifetime, plus the records of every previous
lifetime — which is why it is a superset of `docker logs`, not an equal.

⚠ **`mirror()` (`bus/logging.py`) is gated on the same condition as the stdout
write, and that is load-bearing.** A pane record is `FLOCK_LOG_QUIET` and reaches
the log exactly once, when the switch re-emits the window file it tails. Mirroring
it directly *as well* would write it twice, and **a duplicated custody record is
indistinguishable from a duplicated delivery to every conservation check we have.**

⚠ **Four separate paths write whole records to stdout**, and `grep` found one of
them. The other three were found by diffing the evidence file against `docker
logs` on a live tenant: the watchdog's alerts and job errors, the session's
close record, and — the one that mattered — `switch/windowlog.py`, which carries
**every agent-originated `sent`**. Without it the evidence held `popped` through
`opened` and no `sent`, which reads exactly like an envelope the bus invented.
`tests/test_window_logging.py` now fails if any module prints a record without
mirroring it.

⚠ **It is not tamper-evident.** Any process in the container can append to it,
and the benchmark scripts do so by design. `writer` says who *claims* to have
written a record; it is a label, not a credential.

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

⚠ **The same generalisation applies to `API_PUBLISHED`.** The api door's
per-client HMAC enforcement and CORS (`LLD-api` §3, §6) are gated on
"published", and `API_BIND` cannot answer that question for the same reason
it cannot answer the TLS one — it is hardcoded `0.0.0.0` in the image. So
`entrypoint.sh` exports `API_PUBLISHED=1` at the exact point it already
computes "published" for the api door, right beside where it decides
`FLOCK_ALLOW_PLAINTEXT`. Loopback-only tenants never see it set, and both
features are off entirely in that case — not merely permissive.

### 3.2 Certificates arrive before the doors start

TLS certificates follow the credential rule — **never baked into the image,
never a volume** — so they arrive by `docker cp`. The doors start at boot, so
copying into a *running* tenant is too late: `setup.sh` does
`compose create` → `docker cp` → `compose start`.

⚠ **Two different paths, and conflating them is the classic bug here.** Where
the certificate sits on the operator's machine and where the door looks for it
inside the container are different strings; `container/.env` must carry the
second (`/home/ubuntu/tlscerts/tls.crt`). Writing the host path into it produced
an installer that reported success and a tenant that crash-looped on
`FileNotFoundError`.

⚠ **`docker cp` preserves mode and host uid.** A `mktemp -d` staging directory
is `0700`, so the door could only traverse it when the operator happened to be
uid 1000. Stage `0755`.

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

A single external provider is still available later, as a **proxy in front of
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
| `REDIS_READY_SECONDS` | maximum Redis startup wait. Default 30; expiry stops the tenant rather than hanging boot |

`TMUX_TMPDIR` is inherited rather than passed per invocation, which is the whole
reason `LLD-tmux-host` §4 chose it. It is listed here because anything attaching
to a running tenant needs it and it is otherwise folklore:

```bash
docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux <container> tmux attach -r -t <tenant>
```

⚠ It is **not** `/run/…`. The container runs as `ubuntu`, and `/run` belongs to
root — a socket there cannot be created by the user the agents run as.

`ROSTER_POLL_SECONDS` is here rather than in either polling module because the
switch and tmux host must use one value (`LLD-bus-and-switch` §3.2). Set in one
place and inherited, they agree by construction; configured per module, they
agree until someone edits one of them. The port is invoked per delivery and
does not poll the roster.

## 5. Starting up

Order matters only where a dependency is real:

```
  redis            first — everything else connects to it
  tmux host        creates the server, session and one window per tmux agent
  switch           needs redis; subscribe set comes from the roster
  watchdog         needs redis; samples presence, tasks, activity; writes alerts
  api              needs redis
  session          needs the tmux server; holds one control-mode client
                   the doors last, so neither is reachable before the
                   tenant behind them is up
```

**Bringing the container up twice must be safe.** A second `compose up` against
an already-running container is a no-op, and every reconciliation pass converges
rather than duplicating. A container restart is different: Redis persistence (AOF)
replays durable boards and stream history, while `container/entrypoint.sh` purges
ephemeral transport queues at boot before services launch.

Enrolling an external application client (`StartAgent` with `port_type: "api"`) adds a roster row only, creating no window or CLI process.

### Entrypoint CLI Defaulting & Credential Verification

- **Default CLI initialization:** `setup.sh` writes `AGENT_CLIS` only for agents that differ from the default CLI (`claude`). Therefore, a single-account default install passes no `AGENT_CLIS` environment variable. `container/entrypoint.sh` explicitly defaults every tmux agent's `launch` key in Redis (`pod:<pod>:tenant:<tenant>:agent:<name>:launch`) to `claude` before exception maps (`AGENT_CLIS`, `AGENT_PROFILES`) are applied. Without this explicit default, a default install writes no `launch` keys, `tmuxhost` builds every window as a bare shell, and the office comes up as bash prompts with presence `unknown`.
- **`seed-home.sh check` credential verification:** `seed-home.sh check` inspects profile credentials. It checks actual token expiration timestamps (`refreshTokenExpiresAt` or `expiresAt`) rather than just non-empty file existence. Previously, a 281-byte credential file with an expiry of zero reported `"logged in"` while every agent sat at `"Not logged in · Run /login"`. `seed-home.sh check` now parses the credential JSON and reports `"logged in"`, `"EXPIRED"`, `"UNREADABLE"`, or `"NEEDS LOGIN"`.
- **Upfront segment format validation:** `container/entrypoint.sh` validates `POD`, `TENANT`, and each agent name in `AGENTS` against segment rules (`^[a-z0-9][a-z0-9-]{0,62}$`, non-all-digits, non-reserved) before starting Redis. Hand-edited `.env` or cloned deployments with uppercase or invalid segment names fail fast with a clear error message rather than crash-looping on Python tracebacks.
- **Custody log permission reconciliation:** On boot, `container/entrypoint.sh` reconciles directory and file permissions on `FLOCK_CUSTODY_FILE` (fixing ownership via `sudo` if carried over from `cp -r` clones or root mounts). If the path cannot be made writable, the container refuses to start loudly rather than silently dropping custody records.

## 6. When something dies

A real init runs as PID 1 so orphaned processes — the children agent CLIs spawn
and abandon — are reaped instead of accumulating as zombies. That is a container
concern and it is solved here rather than in any module.

The tmux host, switch, watchdog, api and session each have an independent restart
loop with a one-second delay. One of those service exits is recorded, only that
service is restarted, and the entrypoint stays alive; it does not kill the other
services, the tmux server or agent windows. The modules already owe their callers
idempotent startup and reconnection, so recovery remains local to the failed
service.

`SIGINT` or `SIGTERM` to the entrypoint is different: it is an actual container
stop. The shutdown path signals every supervisor, each supervisor forwards the
signal to its current child, and the entrypoint waits for them before exiting.
Docker's `unless-stopped` policy remains a last resort for an entrypoint or
container failure, not the normal service restart mechanism.

⚠ **Redis is the deliberate exception.** If Redis exits, the entrypoint exits
and Docker restarts the whole tenant. That takes every peer service down, then
runs the transport purge in §5 before any switch can reconnect. Treating Redis
symmetrically would let its AOF restore an older `RPUSH` after losing a newer
acknowledged `LPOP`, making duplicate delivery possible. Preserving the custody
guarantee is worth a full restart for this foundational failure; local door or
worker failures do not pay that cost.

## 7. Deferred

**Cross-tenant persistence.** Redis persistence is enabled locally within the
container (AOF `appendfsync everysec` for durable boards and streams, with
transport queues purged at boot via `purge_transport`).

**More than one tenant per host.** Several containers is the obvious answer and
needs no design; what needs design is them reaching each other, which is
cross-tenant routing and already deferred.

## 8. What this is not

Not a domain module. It runs them and holds no application state of its own.
Startup ordering, exposure validation, and credential handoff are deployment
decisions owned here; routing and delivery decisions belong to the modules
inside it.

Not a general image. It is built to hold exactly one tenant, and the assumption
that there is exactly one is relied upon throughout.
