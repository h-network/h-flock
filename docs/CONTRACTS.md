# Contracts

> **Cross-module agreements.** Everything here is depended on by more than one
> lane, which is the only reason it is centralised. Anything one module can
> decide alone belongs in that module's LLD, not here.
>
> The five LLDs remain the design. This file adds nothing to it — it fixes the
> details three lanes would otherwise each answer differently.

## 1. Stack and layout

**Python 3.12 throughout.** `LLD-api` §6 already commits to FastAPI, and the api
and the tmux adapter both import the bus library — any second language turns that
import into an IPC boundary nobody asked for.

One project, one `pyproject.toml`, one virtualenv in the container. The library
is imported, never vendored.

```
  src/flock/
    bus/         prefix, envelope, the two doors, roster reads   ← the library
    router/      the router process
    adapter/     the tmux adapter: supervisor, consumers, openers
    tmuxhost/    the tmux host
    api/         the FastAPI app
  tests/
  container/     Dockerfile, entrypoint, compose file
```

Every process is `python -m flock.<module>`. Dependencies: `redis`, `fastapi`,
`uvicorn`. Nothing else without saying why.

**`flock.bus` is the only module the others import.** `router`, `adapter`,
`tmuxhost` and `api` never import each other — the layer split in
`LLD-bus-and-router` §1 is enforced by that rule and is checkable by grep.

## 2. The bus library surface

Frozen here so the api and adapter lanes can code against it before it exists.
The `bus` lane owns the implementation and may add to this; it may not change
what is written below without saying so.

```python
# flock.bus.keys
def prefix(pod: str, tenant: str, agent: str | None = None,
           resource: str | None = None) -> str
    # pod:<pod>:tenant:<tenant>[:agent:<agent>][:<resource>]
    # validates every segment against ^[a-z0-9][a-z0-9-]{0,62}$
    # rejects the reserved words pod / tenant / agent
    # raises KeyError on anything invalid. There is no way to build a flat key.

# flock.bus.envelope
def build(kind: str, producer: str, recipient: str, payload: dict,
          correlation_id: str | None = None) -> dict
    # mints stream_id; mints correlation_id when not given (propagate-or-mint)
def parse(raw: str) -> dict          # raises EnvelopeError on malformed input

# flock.bus.doors
def send(r, *, pod, tenant, producer, recipient, payload,
         kind="Message", correlation_id=None) -> str
    # builds, writes the producer's OWN egress, logs. Returns stream_id.
def receive(r, *, pod, tenant, agent, openers: dict[str, callable],
            timeout: int) -> None
    # BLPOP this agent's ingress, validate, dispatch on kind, log.
    # unknown kind -> dead-letter under THIS agent's prefix

# flock.bus.roster
def members(r, *, pod, tenant) -> set[str]        # SMEMBERS
def is_member(r, *, pod, tenant, agent) -> bool   # SISMEMBER
```

An opener is `callable(envelope: dict) -> None`. Registering one is how a kind
becomes deliverable; `LLD-adapter-tmux` §3 is the tmux implementation of one.

## 3. What a log record is

`LLD-bus-and-router` §4 promises two records per component and four across a
delivered envelope's life, and that a crash shows up as "popped, no outcome".
That only works if the records join, so the shape is a contract.

**One JSON object per line, on stdout.** The container collects them; nothing
writes a log file.

| Field | | |
|---|---|---|
| `ts` | required | RFC3339, UTC, milliseconds |
| `module` | required | `bus` · `router` · `adapter` · `tmuxhost` · `api` |
| `event` | required | see below |
| `stream_id` | required | the join key |
| `correlation_id` | when known | |
| `producer`, `recipient` | when known | |
| `reason` | on a failure | why it dead-lettered |

Events, in the order they occur:

```
  sent          send wrote an egress                     (flock.bus.doors)
  popped        the router took it off an egress         (router)
  forwarded     … and wrote an ingress                   (router)
  dead_lettered … or could not                           (router or adapter)
  received      receive took it off an ingress           (flock.bus.doors)
  opened        an opener ran to completion              (adapter)
```

⚠ **Never log a payload.** Invariant 4 says the router does not read one; the
same restraint applies to everything else, and a payload is the one field that
may hold something private. Headers are enough to trace an envelope end to end.

## 4. The `send` command

The agent-facing surface, and the only part of this a human touches. Available on
`PATH` in every agent window (`LLD-adapter-tmux` §1).

```bash
send <recipient> <text>...        # kind defaults to Message
send --kind <kind> <recipient> --payload '<json>'
```

Identity is **never** an argument — it comes from `AGENT_NAME`, `POD` and
`TENANT` in the window's environment, so the command writes the right egress
without being told. Exit 0 on write, non-zero with a message on an invalid
recipient name. It does not report delivery, because it cannot observe it.

**Payload for `kind: "Message"`** is `{"text": "<the message>"}`. This is an
agreement between `send` and the tmux Message opener, not a bus concern — the
bus does not validate payloads (`LLD-bus-and-router` §5).

## 5. Seeding the roster

`LLD-bus-and-router` §7 defers who *owns* the roster. Build 01 still needs one to
exist, so the container's entrypoint writes it once at start, from the
environment, before any module runs:

```bash
SADD pod:$POD:tenant:$TENANT:roster $AGENTS      # AGENTS=alice,bob,carol
```

`SADD` is idempotent, so bringing the container up twice converges
(`LLD-container` §5). **Nothing else writes the roster** — this is boot
configuration, not the write path §7 defers, and no module may acquire one.

## 6. Shared environment

Set once by the container, inherited by everything (`LLD-container` §4).

| | |
|---|---|
| `POD`, `TENANT` | the prefix every key is built from |
| `AGENTS` | comma-separated, seeds the roster |
| `ROSTER_POLL_SECONDS` | default `5`. One value, three readers |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` — loopback, never published |
| `AGENT_NAME` | in an agent's window only |
| `API_TOKEN`, `API_BIND` | api only. Non-loopback bind with no token must refuse to start |
