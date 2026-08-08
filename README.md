# h-flock

A message bus for agents that live in terminals.

One container is one **tenant**: a Redis, a router, a tmux server with one window
per agent, and two doors to the outside. Agents talk to each other by name. What
an agent *is* — a CLI in a window, an HTTP client, a lifecycle endpoint — is not
the bus's concern.

---

## What it is

Producers emit envelopes; a switch forwards them by address without reading the
payload. That is the whole design, and the analogy is load-bearing rather than
decorative:

| L2 switch | h-flock |
|---|---|
| destination MAC | `recipient` — the only thing forwarding depends on |
| source MAC | `producer` — derived from the queue it was popped from, never from content |
| MAC table | the **roster** — `name → VAB`, agent to the base it runs on |
| port config | the **VAB** — a property of the port, not of the frame |
| ethertype | `kind` — the router ignores it; an opener at the far edge reads it |
| L3 and above | `payload` — invisible to everything in the middle |

The switch never learns what is plugged into a port. That ignorance is what lets
you plug in something new without touching it: **adding a kind of participant is
writing one delivery routine**, not changing the router, the bus, or any command.

```
  alice's window                                          bob's window
       │  office send -a bob …                                  ▲
       ▼                                                        │ paste
  …:alice:egress ──► ROUTER ──► …:bob:ingress ──kick──► adapter ┘
                     the one daemon              runs, delivers, exits
```

The router blocks on every egress queue because agents produce whenever they
like. Nothing blocks on an ingress queue, because the router *writes* those and
therefore already knows — so it kicks a short-lived adapter instead. Adapters do
not exist between deliveries.

---

## Quick start

```bash
./setup.sh
#   Pod name [acme]: acme
#   Tenant name [hq]: hq
#   How many agents? [3]: 3
#     Agent #1 name: alice
#     Agent #2 name: bob
#     Agent #3 name: carol
#   Use more than one account in this tenant? [y/N]: n
# → builds the image, brings the tenant up, prints how to reach it
```

Then:

```bash
# watch the office
docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux h-flock-hq-tenant-1 \
  tmux attach -t hq

# drive it over HTTP
curl -H "Authorization: Bearer $TOKEN" http://HOST:8080/agents
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"text":"morning"}' http://HOST:8080/agents/alice/envelopes
```

Full API reference is served by the tenant itself at `GET /restdoc`.

### Accounts

A **profile is an account — the email you log in with**. work and private, or
client1 and client2. The unit is the account, not the agent: a config dir is one
interactive login, so several agents share one and only the extras cost a browser
flow. `setup.sh` asks for them by name, then assigns by defaults-plus-exceptions.

```bash
./container/seed-home.sh check   # which accounts still need a login
./container/seed-home.sh out     # after logging in — keeps it across rebuilds
```

Secrets travel by `docker cp` from `container/home/`, never baked into the image
and never a volume.

---

## What an agent sees

Its whole world, and nothing else:

```
$AGENT_NAME      who you are
$TENANT          the office you are in
$OFFICE_TOOLS    office
$AGENT_GUIDE     a short guide, also written to AGENTS.md and CLAUDE.md
```

```bash
office send -a bob can you take a look at this?
office broadcast standup in five
office peers                       # who you can talk to
office hire dave --cli claude      # a new colleague, live, no restart
office letGo dave
office pause dave
office resume dave
office add -a backend -t "review the auth change" -d "the brief"
office list                        # titles on your board
office take                        # the next one — prints it in full
office done
office cancel
office hold
```

The board is **pulled, never pushed**: adding a ticket notifies nobody. If you
want it started now, add it and then `office send` — the board carries *what*, a
message carries *now*.

A message arrives as `[message from alice] …` — **that prefix is the entire reply
mechanism.** Read a name, reply with the same command. Nothing routes a reply.

An agent never encounters a queue, a kind, a payload schema, Redis, or the
roster. That is deliberate: anything reachable gets explored, so the sanctioned
path has to be the good one.

---

## The two doors

Separate processes, separate ports, so publishing is one decision per door and
neither depends on the other.

| | | |
|---|---|---|
| **api** | `:8080` | envelopes in, **messages and state out** — REST, bearer token |
| **session** | `:8081` | terminal output and keystrokes — WebSocket |

### Apps are participants, not spectators

A Telegram wrapper, a web front end and a macOS app each **enrol as a client**
and get their own address and mailbox:

```bash
POST /agents/host/envelopes  {"kind":"StartAgent","payload":{"agent":"telegram","vab":"api"}}
POST /agents/alice/envelopes {"text":"morning","as":"telegram"}
GET  /agents/telegram/messages?after=<cursor>     # catch-up
GET  /agents/telegram/messages/stream             # live, SSE
```

Alice sees `[message from telegram]` and replies with `office send -a telegram`
— **reply by name, the same rule as replying to a person.** Nothing about an app
is special from the window side, and the bus does the demultiplexing, so one
client's messages never appear in another's mailbox.

⚠ **An app never parses a terminal to get an answer.** `:8081` streams a TUI for
*watching* an agent work; it is not a data format. A chat view is built from
`/messages`.

`POST /agents/{agent}/envelopes` carries any `kind`; the api does not validate it
and could not — which kinds are openable is a fact about adapters, discovered at
the far edge. An unknown kind returns `202` and then dead-letters with a reason.

The session socket streams `%output` from one `tmux -C` client per tenant and
takes keystrokes back, with `read-only` enforced server-side. Terminal bytes are
passed through untouched; rendering is the app's job.

⚠ Both can execute code in an agent's window — the api through the `Command`
kind, the session through keystrokes. Neither is the safe one, and the token is
not optional.

---

## Kinds

Capabilities are `kind`s, opened at the edge. Adding one is adding an opener.

| kind | opened by | does |
|---|---|---|
| `Message` | `tmux` | `[message from …] <text>` into the window |
| `Command` | `tmux` | pasted bare — **it executes** |
| `StartAgent` | `control` | enrol: roster row, home, window, CLI |
| `StopAgent` | `control` | reverses all of it |
| `PauseAgent` | `control` | stops the CLI while preserving the agent |
| `ResumeAgent` | `control` | resumes the CLI and drains its inbox |
| `AddTicket` | `tmux` | writes a ticket to the recipient's board — and pastes nothing |

Anything addressed to an **api client** lands in that client's mailbox whatever
its kind — the api decides nothing about which kinds are interesting, the same
way the router decides nothing about payloads.

`office hire dave` is a `StartAgent` envelope addressed to `host`. The router forwarded
a kind it has never heard of, to a name like any other.

---

## Layout

```
  src/flock/
    bus/         prefix, envelope, the two doors, roster reads   ← library
    tmux/        create/kill/list windows, the paste sequence    ← library
    router/      the one daemon
    adapter/     invoked per delivery, dispatches on VAB, exits
    control/     StartAgent / StopAgent openers
    tmuxhost/    the tmux server, session and windows
    api/         REST
    session/     WebSocket terminals
  container/     Dockerfile, entrypoint, compose, seed-home.sh
  docs/          the LLDs — the design, and why each decision went the way it did
```

`flock.bus` and `flock.tmux` are the only shared libraries; nothing else imports
anything else.

---

## Status

Built, deployed and load-tested: addressing, routing, kicked adapters, per-agent
delivery serialisation, broadcast, dead-lettering, all four kinds, agent
lifecycle over the bus, both doors, and a container that comes up idempotently.

Measured, not assumed: 100 envelopes at 10/s with none lost, ordering preserved,
3 KB messages intact, delivery into a busy window buffered rather than dropped,
~500 ms per delivery of which startup is the larger half.

Task boards are built: tickets with a title and a brief, four columns, ids
accepted by prefix, and an append-only history in `$TASK_RECORD`.

Not built: presence, per-client tokens, TLS, CORS. See [`docs/TODO.md`](docs/TODO.md), which says why for each.

⚠ Agents run with `sudo` in the container, deliberately. Nothing inside it is a
boundary — the container is. Tools and a clean environment remove the *reason* to
go looking, not the ability.

---

## Docs

The [`docs/`](docs) directory is the design, and each file says why a decision
went the way it did rather than only what it was.

| | |
|---|---|
| [`LLD-bus-and-router.md`](docs/LLD-bus-and-router.md) | addressing, the envelope, the two doors, the invariants |
| [`LLD-adapter-tmux.md`](docs/LLD-adapter-tmux.md) | how text actually gets into a terminal, and why each rule is load-bearing |
| [`LLD-tmux-host.md`](docs/LLD-tmux-host.md) | the server, windows, geometry, reconciliation |
| [`LLD-api.md`](docs/LLD-api.md) · [`LLD-session.md`](docs/LLD-session.md) | the two doors |
| [`LLD-container.md`](docs/LLD-container.md) | one container is one tenant |
| [`CONTRACTS.md`](docs/CONTRACTS.md) | what more than one module depends on |
