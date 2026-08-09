# h-flock — the whole project in one file

> ⚠ **This is the architect's understanding, written to be checked.** Every claim
> is numbered so a lane can answer *correct* / *wrong* / *missing* against its own
> module. It is not a source of truth — [`HLD`](HLD.md), [`CONTRACTS`](CONTRACTS.md)
> and the LLDs are. Where this disagrees with them, this is wrong.

## 1. What h-flock is, in one paragraph

h-flock keeps **AI agents alive in tmux windows** and lets anything address them
**by name**. An agent is a seat someone occupies, not a task you invoke: it
persists, keeps its own context in its own CLI session, and can be messaged
repeatedly. Everything moves as **envelopes** on Redis. One tenant is one
container.

⚠ **The distinguishing feature is persistence.** Every hard problem in this
repo — did a message land, is anyone home, is this agent wedged — exists only
because an agent can be *unreachable while still existing*. A one-shot invocation
returns or errors and never has to answer that.

## 2. The one idea: it is a switch

Producers emit envelopes; the router forwards on `recipient` and never opens one.

| L2 switch | h-flock |
|---|---|
| destination MAC | `recipient` — the only thing forwarding depends on |
| source MAC | `producer` — derived from the queue, never from content |
| MAC table | the **roster**, `name → VAB` |
| port config | the **VAB** — a property of the port, not the frame |
| ethertype | `kind` — router ignores it; an opener at the far edge reads it |
| L3+ | `payload` — invisible to everything in the middle |

**Adding a kind of participant is writing one delivery routine.** Not touching
the router, the bus, or any command.

## 3. VAB — and a name collision worth knowing

A **VAB** is what sits behind a name:

| VAB | is | receives by |
|---|---|---|
| `tmux` | an AI CLI in a terminal window | text pasted into the window |
| `api` | an app — web, phone, Telegram bot | a mailbox it reads |
| `control` | the tenant's lifecycle endpoint (`host`) | acting on it |

⚠ **In h-cli and h-vab, "VAB" means something else entirely** — there it is the
Virtual Agent Bus, a tenancy address (`pod:agent:<pod>:<agent>`). Here it is the
delivery base. Same word, unrelated meaning.

## 4. The parts

| module | is | note |
|---|---|---|
| `flock.bus` | library: keys, envelopes, roster, logging | shared |
| `flock.tmux` | library: windows, the paste sequence | shared |
| `flock.router` | **the one daemon** | pops every egress; also the maintenance pass |
| `flock.adapter` | invoked per delivery, then exits | **not** a daemon |
| `flock.control` | Start/Stop/Pause/Resume openers | reached only via the bus |
| `flock.tmuxhost` | tmux server, session, windows | |
| `flock.office` | the one agent-facing command | imports `flock.bus` only |
| `flock.api` | REST, `:8080` | |
| `flock.session` | WebSocket terminals, `:8081` | |
| `flock.watchdog` | its own process, beside the router | alerts humans only |

`flock.bus` and `flock.tmux` are the **only** shared libraries.

## 5. The path an envelope takes

```
office send -a frontend …     an agent writes its OWN egress, never frontend's
  → router                    pops, resolves frontend in the roster, RPUSHes
  → …:frontend:ingress        and kicks `flock.adapter frontend`
  → adapter                   reads frontend's VAB, dispatches, exits
  → opener                    tmux → paste · api → mailbox · control → act
```

**Five log records:** `sent`, `popped`, `forwarded`, `received`, `opened`.

⚠ **Adapters are kicked, not running.** A long-running consumer per agent would
drain a durable Redis queue into process memory. Keeping the backlog in Redis is
the point. An office of idle agents costs nothing.

⚠ **A busy tag serialises delivery per agent** — two adapters pasting into one
window would interleave.

## 6. Kinds

| kind | opened by | does |
|---|---|---|
| `Message` | tmux | `[message from …] <text>` into the window |
| `Command` | tmux | pasted bare — **it executes** |
| `AddTicket` | tmux | writes a ticket to that agent's board, pastes nothing |
| `StartAgent` | control | enrols: roster row, and for tmux a home, window, CLI |
| `StopAgent` | control | reverses it |
| `PauseAgent` | control | stops the CLI, keeps agent, queues and board |
| `ResumeAgent` | control | restarts the CLI, drains what queued |

⚠ **Pause is not retire.** ⚠ **An app's mailbox takes every kind**, and the client
filters.

## 7. Two doors

| | port | for | |
|---|---|---|---|
| api | `:8080` | **programs** | envelopes in, messages and state out |
| session | `:8081` | **people** | a terminal rendered for a human |

⚠ **An app must never parse a terminal to get an answer.** Answers are messages.
`:8081` is for showing a person what is happening, and for interactive logins —
device-code OAuth is terminal bytes in both directions.

## 8. Observation — all from files, never screens

| | source |
|---|---|
| activity | the CLI's own session JSONL, tailed — `input` / `output` / `tool` |
| presence | recency of activity |
| verify | a delivery marker vs a later `input` |
| window log | a file `office` writes, tailed |

**Presence is `working` / `idle` / `unknown` / `blocked`.**

⚠ **`unknown` is not `idle`** — agy and bare shells write no session file, so
nothing can be said. For codex and agy this is the correct terminal state, not a
gap: they run for days on one token.

⚠ **Activity carries tool names, never arguments.**

## 9. `blocked`, and what changed in builds 30–31

**`blocked` = a delivery was judged unverified and nothing was consumed since.**
Written by the **router** from its own verdict — no screen involved.

Measured live, each precondition proved on screen (`sim-blocked.sh`, 19/0):

| case | result |
|---|---|
| wedged CLI (pane consumes nothing) | `blocked` set |
| claude at a login prompt | `blocked` set — **caught** |
| codex at a login prompt | `blocked` set — **caught** |
| healthy freshly-started agent | **unjudged**, not blocked |

⚠ **The "CLI records input it does not act on" gap does not exist.** It came from
a test asserting an absence that passed whenever the router had not yet judged.
It was the only thing that ever argued for a screen scraper.

⚠ **A delivery is judged only for an agent that has produced activity before.**
No history → `unknown` → `delivery_unjudged`, never `blocked`. **Cost: the first
delivery to a new agent is never judged.**

⚠ **No retry, ever.** Verification cannot tell an unsubmitted paste from text
sitting in a wedged CLI, so a retry either cannot help or duplicates. Chosen:
possible loss, surfaced to a human, over possible duplication.

## 10. Pulled, not pushed

**Boards** — a ticket waits until an agent asks. Nothing notifies. One ticket in
`doing` *falls out* of that rather than being a rule.

**Mailboxes** — an app reads its own by cursor. `POST` returns `202`.

⚠ **A reply may never come.** Every client is built for silence.

## 11. The invariants — cite by name, never by number

1. the router forwards on `recipient` alone
2. `producer` is derived from the queue
3. nothing writes another agent's keys — it sends an envelope
4. **roster fields, never values** — the router cannot know a VAB
5. adapters do not exist between deliveries
6. the api does not validate `kind`
7. **nothing in the data path reads a terminal**; observation may look, and may
   only report

⚠ **7 is a statement about position, not technique.** A scraper is acceptable in
a watchdog and unacceptable in an adapter. ⚠ **And nothing scrapes** — a scraping
`blocked` was built and abandoned because a consumed message stays visible in the
transcript, so it marked healthy agents blocked.

## 12. Operational truths learned the hard way

- **`PASTE_ENTER_DELAY = 0.5`** — paste and Enter are two writes. Together, a CLI
  takes the text and drops the submit. Not a slow-terminal fix
- **window creation is idempotent by name** — a duplicate makes an agent
  *unaddressable*, not slow
- **all-digit agent names are rejected** — tmux reads `s:2` as window index 2
- **the verify marker is written before the paste** — after loses a sub-second race
- **verify marks by allowlist `{claude, codex}`** — never a denylist
- **rebuilding a tenant is not restarting it.** It destroys every runtime
  enrolment — hired agents, client enrolments, and seeded credentials. Do not
  rebuild a tenant someone is using
- **seeded claude credentials go stale** — mechanism still being measured; the
  source refreshed at 15:25 and a live agent on a copy died at ~15:30

## 13. Where it stands

452 commits, 209 tests green, 4505 LOC, 55 docs. Live gates: `plumbing-check.sh`
(12 sections, 33 assertions) and `sim-blocked.sh` (4 cases, 19 assertions).
Proven end to end with three CLIs driven from Telegram, plus a web client.

**Open:** claude credential staleness (in flight), the live terminal view client
half, `clients/` needing its own repo, profile logins (needs a person), and
security — TLS, CORS, per-client tokens, Redis ACLs — parked deliberately.

## 14. What I want checked

Answer per numbered claim, for **your module only**:

- **correct** — and say how you know
- **wrong** — with the file and line that contradicts it
- **missing** — something load-bearing I left out

⚠ **Do not fix anything.** This is a comprehension check. If it is wrong, the
question is whether *this file* is wrong or the *code* is.

⚠ **I have already found one drift myself:** `HLD` §8 still says verify "does not
catch a message eaten by an open modal — that hole is known and open", which
audit 06 removed from §8a and missed here. Expect more of that kind.
