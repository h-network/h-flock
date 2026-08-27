<div align="center">

<img src="docs/assets/banner.svg" alt="h-flock — a message bus for agents that live in terminals" width="860">

<br/>

[![One tenant per container](https://img.shields.io/badge/one_tenant-per_container-06B6D4?style=for-the-badge)](#-quick-start)
![Bus](https://img.shields.io/badge/bus-Redis_lists-DC382D?style=for-the-badge&logo=redis&logoColor=white)
[![Apps](https://img.shields.io/badge/apps-REST_%2B_SSE-0EA5E9?style=for-the-badge)](docs/API.md)
[![License](https://img.shields.io/badge/license-MIT-22C55E?style=for-the-badge)](LICENSE)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-single_image-2496ED?style=flat-square&logo=docker&logoColor=white)
![tmux](https://img.shields.io/badge/tmux-agent_windows-1BB91F?style=flat-square&logo=tmux&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-two_doors-009688?style=flat-square&logo=fastapi&logoColor=white)
![Agents](https://img.shields.io/badge/agents-claude_codex_agy-8B5CF6?style=flat-square)
![Tests](https://img.shields.io/badge/tests-954_passing-22C55E?style=flat-square)

**An office of AI agents (Claude, Codex, and Antigravity — mix freely) that hire
into real terminals, work from their own task boards, and coordinate with each
other and with you — over a REST API or the bundled Telegram bot; a
browser-console demo also ships. One command brings up the office. One
container runs each tenant.**

`./setup.sh` asks for the tenant and its agents. Each gets a tmux window, a home
directory, and `office` — hire and retire colleagues live with no restart, hand
out tickets, and message anyone by name. The lead gets nudged automatically
when something's been sitting too long — routed there by a real Redis key, not
just a guide. Who reviews and merges is a separate, unenforced convention every
agent is told to follow — and envelope custody and board transitions are
logged as they happen, not reconstructed from terminal output afterward.

Underneath, it's a switch: envelopes are forwarded by name, and nothing in the
middle reads a payload. That discipline is *why* adding a phone app, a bot, or a
new kind of colleague is one delivery routine, not a rewrite.

[Quick start](#-quick-start) · [How it works](#️-how-it-works) · [Built by agents](#-built-by-an-office-of-agents) · [Build an app](#-build-an-app) · [Architecture](docs/HLD.md) · [API reference](docs/API.md)

</div>

---

## ✨ What it is

- **🏢 An office, not a framework.** Hire an agent, it gets a terminal and a
  board. Give it a ticket, it pulls it when it's ready — nothing pushes work
  onto a busy colleague. A lead hands out work and merges it; that's a role
  written into every agent's guide, not a permission the system enforces.
- **📱 Reachable from outside the terminal.** A Telegram bot ships with a real
  menu — board overview, add a ticket, hire/retire, pause/resume, broadcast,
  live-pushed alerts for blocked/stalled/credential conditions — built
  entirely against the same REST door any other app would use. **No terminal
  scraping anywhere in the loop.**
- **🔀 A switch underneath, not a framework.** Producers emit envelopes; the
  switch forwards them by `destination` and never opens one. Adding a new kind
  of participant is **one delivery routine** — not changing the switch, the
  bus, or any command.
- **🏗️ One container = one tenant.** Redis, the switch, a tmux server with one
  window per agent, and two doors to the outside. Bring it up twice and it
  converges.

Boards, presence and activity, live terminals, accounts, adapters that are not
daemons, and what gets logged: [`docs/HLD.md`](docs/HLD.md) has all of it, and
[the kinds table](docs/HLD.md) says which capabilities exist.

## 🏗️ Built by an office of agents

This repository is written by a team of AI agents — one per lane, each in its own
terminal — with a human lead reviewing and merging. **Not by h-flock itself:** the
office runs on h-flock's predecessor tooling, and dogfooding is
[still ahead](docs/TODO.md).

```
$ git rev-list --count HEAD
684
$ git log --merges --format=%s | grep -oE "origin/[a-z-]+/" | sort | uniq -c
     29 origin/api/      21 origin/bus/      20 origin/tmux/
```

Each lane branches from `main`, pushes, and the lead merges — the same workflow
the product exists to support. ⚠ **Numbers move with every commit; re-run the
commands rather than trusting these.**

## ⚙️ How it works

```
  backend's window                                          frontend's window
       │  office send -a frontend …                                  ▲
       ▼                                                        │ paste
  …:backend:egress ──► SWITCH ──► …:frontend:ingress ──kick──► port ┘
                     the one daemon              runs, delivers, exits
```

The switch blocks on every egress queue because agents produce whenever they
like. Nothing blocks on an ingress queue, because the switch *writes* those and
therefore already knows — so it kicks an port instead.

The L2 analogy is load-bearing rather than decorative:

| L2 switch | h-flock |
|---|---|
| destination MAC | `destination` — the only thing forwarding depends on |
| source MAC | `source` — stamped from the queue it was popped from, never from content |
| MAC table | the **roster** — `name → port_type`, agent to the base it runs on |
| port config | the **port_type** — a property of the port, not of the frame |
| ethertype | `kind` — the switch ignores it; an opener at the far edge reads it |
| L3 and above | `payload` — invisible to everything in the middle |

The switch never learns what is plugged into a port. That ignorance is what lets
you plug in something new without touching it.

## 🚀 Quick start

```bash
./setup.sh
#   Pod name [acme]: acme
#   Tenant name [hq]: hq
#   How many agents? [3]: 3
#     Agent #1 name [architect]:            # window 1 is always the lead
#     Agent #2 name [sme-2]: backend        # rename them — the name is the job
#     Agent #3 name [sme-3]: frontend
#   Use more than one account in this tenant? [y/N]: n
#   Point any agent at a local model endpoint? [y/N]: n
#   Open the REST API door? [y/N]: n              # OFF by default — see below
#   Run the Telegram bot against this tenant? [y/N]: n
#   Host port for the session console [8081]:     # first free port, so a second
#                                                 # tenant on this box just works
#   Reach the console from another machine? [Y/n]: y
#     Path to a TLS certificate (blank for more choices):
#     Generate a self-signed certificate? [y/N]: n     # plain HTTP, recorded as a choice
# → builds the image, brings the tenant up, prints how to reach it
```

⚠ **Agent #1 is the lead, whatever it is called.** The name is a job title, not
a role: the first name in the roster becomes the lead and every agent's guide
says so. `architect` is only the default suggestion.

**Runs on Linux and macOS**, including Apple Silicon natively — the base image
publishes `arm64`. Verified on a stock MacBook with Docker Desktop: install,
plumbing check 25/25 and failure simulator 19/19. ⚠ macOS ships **bash 3.2**, so
`setup.sh` avoids bash 4 syntax; if Docker Desktop is not on your `PATH` in a
non-interactive shell, add
`/Applications/Docker.app/Contents/Resources/bin`.

⚠ **The REST API door is OFF unless you ask for it.** It is the widest surface a
tenant has — one shared bearer token, and `as` on a post is a declaration rather
than a credential — and agents reach each other over the bus without it. Set
`API_ENABLED=1` in `container/.env`, or answer yes at the prompt.

⚠ **The Telegram bot is a CLIENT of that door, not a door of its own.**
`clients/telegram/bot.py` takes `--api-url`, so it cannot run with the API off;
answering yes to Telegram enables the API and says so. `setup.sh` does not start
the bot — it needs its own Telegram token — it prints the command.

⚠ **Host ports are asked, not assumed.** The doors always bind 8080/8081 *inside*
the container; the prompts choose the host side, defaulting to the first free
port. **This is what lets two tenants share one host** — the compose project was
already per-tenant, but the published ports used to be hardcoded, so the second
tenant came up healthy-looking with a door nobody could reach. A port already in
use is refused rather than written into `.env`.

⚠ **Choosing TLS makes `setup.sh` deliver the certificate before the doors
start** — it creates the container, `docker cp`s the certificate in, then starts
it. Certificates are never baked into the image and never a volume, the same
rule as credentials.

Then:

```bash
# watch the office
docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux h-flock-hq-tenant-1 \
  tmux attach -t hq

# drive it over HTTP
curl -H "Authorization: Bearer $TOKEN" http://HOST:8080/agents
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"text":"morning"}' http://HOST:8080/agents/backend/envelopes
```

The tenant serves its own API reference at `GET /restdoc`.

### Accounts

A **profile is an account — the email you log in with**. Work and private, or
client1 and client2. The unit is the account, not the agent: a config dir is one
interactive login, so several agents share one and only the extras cost a browser
flow. `setup.sh` asks for them by name, then assigns by defaults-plus-exceptions.

```bash
./container/seed-home.sh check   # which accounts still need a login
./container/seed-home.sh out     # after logging in — keeps it across rebuilds
```

Secrets travel by `docker cp` from `container/home/`, never baked into the image
and never a volume.

### Cloning or relocating a tenant

To clone or migrate an existing deployment without interactive re-authentication
across vendor login flows, use `seed-home.sh`'s `out`/`in` mechanism as a
migration path:

1. **On the SOURCE tenant:** pull real, currently-logged-in credential files out
   of the running container into `container/home/` on the host:
   ```bash
   ./container/seed-home.sh out <source-container-name>
   ```
2. **Copy the repository** (`cp -r` or your preferred transfer method) to the
   new location.
3. **Edit `container/.env`** for the new deployment (`CLAUDE_OAUTH_TOKEN_<PROFILE>`,
   `TENANT`, `POD`, `AGENTS`, `API_TOKEN`, etc.).
   > ⚠ **Naming rules:** `TENANT` and `POD` must be lowercase alphanumeric and
   > hyphens (1–63 chars, starting with a letter or digit, not all-digits, and
   > not reserved words like `pod`, `tenant`, `agent`, or `all`). The entrypoint
   > validates these upfront and fails fast with a clear error message instead of
   > crash-looping.
4. **Bring the new container up.** Both paths are supported:
   - **Interactive:** `./setup.sh` (prompts and generates `.env` for you — not
     needed if `container/.env` is already configured).
   - **Manual:**
     ```bash
     docker compose -p h-flock-<tenant> --env-file container/.env -f container/compose.yaml up -d
     ```
     ⚠ **Always pass `-p` explicitly with a real project name.** Omitting `-p`
     defaults Docker Compose's project name to the current directory name (e.g.
     `container`), producing confusing container names like `container-tenant-1`
     instead of `h-flock-<tenant>-tenant-1`.
5. **Seed the credentials into the new tenant:**
   ```bash
   ./container/seed-home.sh in <the-real-container-name>
   ```
   *(Note: `seed-home.sh` defaults to guessing `h-flock-${TENANT}-tenant-1`, which
   only matches if you used `-p h-flock-<tenant>` consistently; pass the actual
   container name explicitly otherwise.)*
6. **Verify the login status:**
   ```bash
   ./container/seed-home.sh check <the-real-container-name>
   ```

**End state:** assuming the source tenant was logged in and step 1 ran cleanly,
all three CLIs (`claude`, `codex`, `agy`) start authenticated in the new tenant
with zero interactive browser re-authentication flows required.

### Your own model

An agent can run against a **local inference server** instead of a vendor
account. `setup.sh` asks, offers the model ids the endpoint actually serves, and
checks it speaks the API the CLI needs before writing anything down.

```bash
Point any agent at a local model endpoint? [y/N]: y
  Endpoint type — vllm or ollama [vllm]:
  Endpoint base URL, e.g. http://10.0.0.5:8000 (NO trailing /v1):
  served by that endpoint: qwen3-vl-32b
  ✓ /v1/messages answered — claude can use this endpoint
  Which agents use it? (space-separated): sme-3
```

Such an agent needs **no login at all** — the CLI talks to your server — and is
an agent like any other: same window, same paste, same activity feed, same
board. Measured on a live vLLM: tool calls, multi-step work, and `office send`
to a colleague who replied.

⚠ **The endpoint name is per agent; the address is tenant configuration.** An
agent cannot read or change which model it is pointed at.

⚠ **claude talks to `/v1/messages`.** `setup.sh` probes exactly that, with a
model id the endpoint says it serves, and prints what came back — so a mismatch
shows up during install rather than as "issue with the selected model" later.

⚠ **vLLM and ollama are both tested**, each run end to end here: a tool call, a
multi-step turn, and `office send` to a colleague that arrived in their terminal.
ollama serves `/v1/messages` directly — no proxy, no translation.

⚠ **Give a cold model time.** The same ollama endpoint answered in 15.7s on the
first call and 0.5s once warm, so an installer probe that gives up early reports
a working endpoint as silent. `setup.sh` waits 90s.

## 🧑‍💻 What an agent sees

Its whole world, and nothing else:

```
$AGENT_NAME      who you are
$TENANT          the office you are in
$OFFICE_TOOLS    office
$AGENT_GUIDE     a short guide, also written to AGENTS.md and CLAUDE.md
```

```bash
office send -a frontend "can you take a look at this?"
office send -a frontend --file report.md    # or --stdin; never shell-parsed
office broadcast standup in five
office peers                       # who you can talk to
office profiles                    # which account each colleague runs under
office status                      # who is working, on what, since when
office hire networking --cli claude      # a new colleague, live, no restart
office letGo networking
office pause networking
office resume networking

office add -a frontend -t "review the auth change" -d "the brief"
office list                        # titles on your board
office take                        # the next one — prints it in full
office done
office cancel
office hold
```

A message arrives as `[message from backend] …` — **that prefix is the entire reply
mechanism.** Read a name, reply with the same command. Nothing routes a reply.

The board is **pulled, never pushed**: adding a ticket notifies nobody. If you
want it started now, add it and then send a message — the board carries *what*, a
message carries *now*.

**Nothing an agent is asked to do requires a queue, a kind, a payload schema,
Redis or the roster.** It has `REDIS_URL` and `redis-cli` like any process in the
container — this is about the sanctioned path, not a sandbox. Anything reachable
gets explored, so the reachable-and-obvious path has to be the good one.

## 📱 Build an app

A Telegram wrapper, a web front end and a macOS app each **enrol as a client** and
get their own address and mailbox:

```bash
POST /agents/host/envelopes  {"kind":"StartAgent","payload":{"agent":"telegram","vab":"api"}}
POST /agents/backend/envelopes {"text":"morning","as":"telegram"}
GET  /agents/telegram/messages?after=<cursor>     # catch-up, resumable
GET  /agents/telegram/messages/stream             # live, SSE
GET  /agents/backend/activity/stream              # what backend is doing, live
GET  /agents/backend                              # working | idle | unknown | blocked
```

Backend sees `[message from telegram]` and replies with `office send -a telegram`
— **reply by name, the same rule as replying to a person.** The bus does the
demultiplexing, so one client's messages never appear in another's mailbox, and
nothing about an app is special from the window side.

⚠ **An app never parses a terminal to get an answer.** `:8081` streams a TUI for
*watching* an agent work; it is not a data format.

📖 **[Full API reference for app developers →](docs/API.md)**

Two working clients live in [`clients/`](clients/) — a **Telegram bot** and a
**browser UI** — both built from that document and a token, with no access to
this source. They exist as much to test the reference as to be useful: between
them they found eight things it did not say.

## 📁 Layout

```
  src/flock/
    bus/         prefix, envelope, the two doors, roster reads   ← library
    tmux/        create/kill/list windows, the paste sequence    ← library
    switch/      the one daemon
    port/     invoked per delivery, dispatches on port_type, exits
    control/     StartAgent / StopAgent openers
    tmuxhost/    the tmux server, session and windows
    office/      the one agent-facing command
    api/         REST
    session/     WebSocket terminals
  container/     Dockerfile, entrypoint, compose, seed-home.sh
  docs/          the design, and why each decision went the way it did
```

`flock.bus` and `flock.tmux` are the only shared libraries; nothing else imports
anything else.

## 📊 Status

Built, deployed and load-tested: addressing, routing, kicked adapters, per-agent
delivery serialisation, broadcast, dead-lettering, every kind, agent lifecycle
over the bus, task boards, app clients with their own mailboxes, both doors, and
a container that comes up idempotently.

Measured, not assumed: 100 envelopes at 10/s with none lost, ordering preserved,
3 KB messages intact, delivery into a busy window buffered rather than dropped,
~500 ms per delivery of which startup is the larger half.

A **watchdog** runs beside the switch: a ticket open too long, with no model
activity and a silent window, raises one alert — to `GET /alerts` and the log,
never to an agent. It also warns before a login expires, and marks an agent
`blocked` when a delivery was not consumed — which catches a wedged CLI, and both
claude and codex sitting at a login prompt. An agent that has never spoken is
`unknown`, and its first delivery is not judged at all.

Two **demo clients** ship with it, both built from `docs/API.md` and a token
alone: a **Telegram bot** and a **browser console** with live presence, boards,
alerts, terminals into any agent, session recording and an operator login. They
are examples, not products — the framework is the product.

Both doors support TLS via `API_TLS_CERT`/`API_TLS_KEY` and
`SESSION_TLS_CERT`/`SESSION_TLS_KEY`. **A door published beyond loopback without
TLS stops the tenant starting**, because the bearer token — and everything typed
into a terminal — would cross the network in clear text. `setup.sh` asks; if you
accept plain HTTP it records `ALLOW_PLAINTEXT_PUBLISH=1` in `container/.env`, so
it is a typed answer rather than a default nobody saw.

⚠ **A bind is not an exposure.** Both doors bind `0.0.0.0` *inside* the
container by design — publishing is the deliberate act, and the port mapping
that decides it (`API_HOST`, `SESSION_HOST`) is invisible to the door process.
So the entrypoint judges it. Running a door directly, outside a container,
nobody has judged anything and the bind is the exposure: it refuses a
non-loopback bind without TLS.

⚠ **Certificates must exist before the tenant boots.** They are not baked into
the image and not a volume, so they arrive by `docker cp` — and the doors start
at boot, so copying into a *running* tenant is too late. Create, copy, then
start:

```bash
. container/flock-compose.sh && flock_compose_args
docker compose -p h-flock-<tenant> --env-file container/.env "${FLOCK_COMPOSE_ARGS[@]}" create
docker cp /path/to/certs <container>:/home/ubuntu/tlscerts
docker compose -p h-flock-<tenant> --env-file container/.env "${FLOCK_COMPOSE_ARGS[@]}" start
```

**Verified end to end:** TLS 1.3 on both doors, `200` with a token and `401`
without, plain HTTP refused, and the terminal socket answering
`101 Switching Protocols` over `wss://`. The container healthcheck follows the
scheme — with certs configured it probes `https`, because probing plain HTTP got
`Empty reply from server` forever and a correctly serving TLS tenant never
became healthy.

⚠ **The browser console does not work against TLS doors.** It is a *proxy*: the
browser talks only to the console server, which talks to the doors server-side —
so the certificate question is entirely server-side, and there is nothing to
accept in the browser. Two things in `clients/web/server.py` block it:

- the WebSocket proxy opens a **plain socket** to the session door, so terminals
  fail even against a certificate that is perfectly valid
- the REST proxy verifies with the default context and takes no CA or insecure
  option, so a self-signed certificate fails outright

**So pick one:** publish both doors to `127.0.0.1` and terminate TLS in a
reverse proxy in front (what `LLD-container` §3 says, and what leaves the
console working over loopback), or serve TLS from the doors and use an app that
speaks it. See [`docs/TODO.md`](docs/TODO.md).

Not built: per-client tokens, CORS. See [`docs/TODO.md`](docs/TODO.md), which says why for each.

⚠ Agents run with `sudo` in the container, deliberately. Nothing inside it is a
boundary — the container is. Tools and a clean environment remove the *reason* to
go looking, not the ability.

## 📚 Docs

The [`docs/`](docs) directory is the design, and each file says why a decision
went the way it did rather than only what it was.

| | |
|---|---|
| [`HLD.md`](docs/HLD.md) | **start here** — how the pieces fit, and the invariants |
| [`API.md`](docs/API.md) | **for app developers** — the whole HTTP surface, no repo needed |
| [`LLD-bus-and-switch.md`](docs/LLD-bus-and-switch.md) | addressing, the envelope, the two doors, the invariants |
| [`LLD-office.md`](docs/LLD-office.md) | the agent-facing command — the board, lifecycle, and what crosses the bus versus a direct Redis op |
| [`LLD-port-tmux.md`](docs/LLD-port-tmux.md) | how text actually gets into a terminal, and why each rule is load-bearing |
| [`LLD-tmux-host.md`](docs/LLD-tmux-host.md) | the server, windows, geometry, reconciliation |
| [`LLD-api.md`](docs/LLD-api.md) · [`LLD-session.md`](docs/LLD-session.md) | the two doors — `:8080` envelopes and state, `:8081` terminal bytes |
| [`LLD-container.md`](docs/LLD-container.md) | one container is one tenant |
| [`CONTRACTS.md`](docs/CONTRACTS.md) | what more than one module depends on |
| [`LLD-watchdog.md`](docs/LLD-watchdog.md) | what it watches, and why it tells a human and never an agent |

---

MIT licensed — see [`LICENSE`](LICENSE). The name and logo are trademarks; what
you may do with them without asking, and the short list that needs permission, is
in [`TRADEMARKS.md`](TRADEMARKS.md).
