# CHANGELOG — what changed, and what it invalidated

> **Contract changes only.** Wire formats, event names, key shapes, endpoints,
> limits — anything another component or an external client can depend on.
> Refactors and fixes are in git; they do not belong here.

> ⚠ **Every entry names what the change made FALSE.** That is the point of this
> file. A change log that lists only what was added leaves the reader to discover
> which docs, scripts and assumptions just went stale — which is how
> Documentation drift reached two blocking rows in nineteen builds.

---

## 2026-08-26 — the watchdog can also message the lead for an unpicked `todo` ticket

Same family, same day as the `doing`-duration alert below. Any ticket sitting
in an agent's `tasks.todo` past `WATCHDOG_TODO_ALERT_SEC` (default 300s) now
pastes `[alert from watchdog] <agent> has an unpicked ticket "<title>"
waiting <N> min` into the tenant `lead`'s pane, via the same `_notify_lead`
path the `doing`-duration alert uses.

**What this made false:** that §2a's exception to "alerts a human, never an
agent" (HLD §8c) was singular. It is now two independent rules sharing one
mechanism and one scope (the `lead`, never the ticket's agent, never any other
peer) — HLD §8c and LLD-watchdog §4/§7 invariant 6 are worded to cover both.

New per-agent key `<prefix>:agent:<name>:todo.alerted`, a **HASH** keyed by
ticket id (unlike `doing.alerted`'s STRING): `tasks.todo` can hold several
aging tickets for one agent at once, each tracked and re-fired independently,
with stale ticket ids dropped once they leave `todo`.

⚠ Presence-independent for a different reason than §2a: there is no work in
progress yet to have a presence opinion about. An agent can be entirely
healthy and simply not have looked at its board — which is exactly the
condition this rule surfaces.

## 2026-08-26 — the watchdog can message the lead directly for a long-`doing` ticket

Any agent's `tasks.doing` ticket older than `WATCHDOG_DOING_ALERT_SEC` (default
900s) now pastes `[alert from watchdog] <agent> has been working on "<title>"
for <N> min, request an update` straight into the tenant's `lead` pane —
`office send`'s delivery path, not the `<prefix>:alerts` stream. It re-fires
once per `WATCHDOG_DOING_ALERT_SEC` crossing while the same ticket stays open
(`LLD-watchdog` §2a), tracked at the new per-agent key
`<prefix>:agent:<name>:doing.alerted`.

**What this made false:** HLD §8c's *"it alerts a human, and never an
agent"* and LLD-watchdog §7 invariant 6's *"never into an agent's ingress
queue"* were both unqualified. Both now carry the single, deliberate
exception: the tenant's `lead`, and only the lead — never the ticket's own
agent, never any other peer. Neither statement changes for `stalled`,
`blocked` or `credential` records, which still go only to the alerts stream.

⚠ Board-only trigger, no presence or window signal — unlike §2's `stalled`
rule, which exists to keep the *passive* alerts stream from crying wolf. This
alert is not passive: it lands in front of the one participant whose job is to
weigh it, so the bar is intentionally lower and the two rules can both fire
for the same ticket independently.

## 2026-08-26 — `office profiles`: one place to audit account assignment

`office profiles` lists every configured account, which tmux agents are on it,
which agents landed on `default` because no `profile` was set, and which
members carry no CLI account at all (`api`, `control` port_types).

**What was false:** that account assignment was visible only one agent at a
time. `office peers -v` (build 108) already showed a peer's own profile, but a
multi-account tenant had no single command to see which account was
over-subscribed, under-used, or silently inheriting `default`.

⚠ A legacy tenant with no canonical `accounts` registry in Redis prints
`configured accounts: unknown` and falls back to the profiles it can observe
from agents' own `profile` keys, rather than failing closed — the same
permissive-on-absence precedent as `bus/policy.py`.

## 2026-08-22 — the custody log outlives the container

**Build 79.** `FLOCK_CUSTODY_FILE` is a byte copy of every record reaching
container stdout, on a named volume that survives `docker compose down`.

**What was false:** that `docker logs` is where a run's evidence lives. It is
deleted with the container, and was uncapped. Any sign-off citing a torn-down
tenant's log had no retained evidence — `TEST-SIGNOFF`'s own REFUSED example.

⚠ **The file is a SUPERSET of `docker logs`, not an equal.** It accumulates
across container lifetimes, so comparing the whole file to a running container's
log will differ by every previous life, including the `stopped` record that
`docker logs` for a removed container cannot show at all.

⚠ **Three of the four record paths were found by diffing a live tenant, not by
grep.** The one that mattered is `switch/windowlog.py`: it re-emits pane records,
so it carries **every agent-originated `sent`**. Before the fix the evidence held
`popped` through `opened` and no `sent`.

## 2026-08-22 — every record says who wrote it

**Build 80.** New key `writer` on every custody record, from `FLOCK_WRITER`,
defaulting to `module`.

**What was false:** that a record's origin could be inferred. `bench-port.py` and
`bench-send.py` write custody records **by design**, so synthetic and real were
byte-indistinguishable and every conservation count silently included benchmark
traffic.

| | |
|---|---|
| **default** | `module` — no existing record changes meaning |
| **tailer** | preserves an explicit `writer`, fills only an absence with `window:<agent>` |
| **analyser** | `--writer` / `--exclude-writer`, always prints the census, marks a run REFUSED when an *undeclared* bench writer appears |
| **`--expect-writer NAME=COUNT`** | exact match, so leftover contamination still refuses |

⚠ **`writer` is a label, not a credential.** It is not signed and is not meant to
be; a sibling project measured that alternative and declined it.

## 2026-08-22 — delivery verification accepts any activity, and waits 120s

**Build 81.** `input`, `output` **or** `tool` after the marker counts as alive.
`VERIFY_AFTER_SECONDS` default **10 → 120**.

**What was false:** that `delivery_unverified` meant a delivery failed. It was
wrong for **1,180 of 1,285** on one run and **4 of 13** on another; the live rate
is now **0 of 40**.

⚠ **This admits a false positive**: `output` can belong to the previous turn, so
alive does not prove the paste was consumed. That is the safer error — a wedged
process or a login prompt emits no activity of any kind.

⚠ **It also invalidated every fixed-duration wait on a verdict.**
`container/sim-blocked.sh` polled 20 s and reported four true detections as
failures on the lab. Anything waiting for `blocked` or an empty `pending.verify`
must derive its patience from the tenant's window.

## 2026-08-22 — usage and cost records

**Build 82.** New `usage` event carrying four token buckets, and `office usage`.

**What was false:** that h-flock had no cost surface. It now has one, and
`CONTRACTS` §5 listed **fifteen** office subcommands against seventeen in code —
`cloneToAll` and `usage` were both shipped and both undocumented.

| | |
|---|---|
| **record** | `{"event":"usage","writer":"usage","agent","cli","model","input","cache_read","cache_write","output"[,"stream_id","correlation_id"]}` |
| **pricing** | `container/config/pricing.json`, longest-prefix match, USD per 1M |
| **unpriced** | a model with no entry reads `unpriced`, **never `0.00`** |
| **correlation** | first usage after a delivery marker gets that envelope's ids; **omitted, never guessed**, when no marker precedes it |

⚠ **`delivery.markers` is bounded at 500 and attribution loss is silent.** A
trimmed marker yields a usage record with no `stream_id` — the specified
degradation. Measured live: **18 of 27 attributed, 9 omitted.**

⚠ **`flock.bus.resp.Redis` gained `xrange`/`xlen`.** It had `xadd` and no reader,
so `office usage` returned an empty table with exit 0 against a stream holding 27
records. No unit test could catch it: the fake client in the tests had `xrange`
and the real one did not.

## 2026-08-21 — the docs caught up to wire v4, six days late

**Build 73 took the wire to v4/256 on 2026-08-15 and updated `HLD.md` alone.**
Five other docs kept describing v3.

| doc | said | now |
|---|---|---|
| **`API.md`** ⚠ public | `v: 3`, 191-byte header, "same eight keys" | `v: 4`, 256, **`ttl`/`hops` documented** |
| `API.md` field table | `v` is *"Always `2`"* | `4` — that line survived **both** prior corrections |
| `CONTRACTS.md:101` | "the Redis wire is **hard v3**" | hard v4; notes 191 is `TTL_START` now |
| `LLD-bus-and-switch` §5 | frame example `"v": 3`, no `ttl`/`hops` | v4 with both |
| `DESIGN-layers.md` | `raw[:191]`, `parse_for_switch` at `:132` | `raw[:HEADER_WIDTH]`, `:217` |

⚠ **What was false, and it was client-visible:** v4 added `ttl` and `hops` to the
envelope a mailbox consumer receives. `API.md` told external developers to expect
**eight keys**; they get **ten**. A client validating against a closed schema
rejects every envelope, and the public reference said the wrong thing about it
for six days.

**`LLD-bus-and-switch` also said "six transport records" above a list of five** —
`kick_started` (build 65) never reached the block. And broadcast is now recorded
correctly: a `kick_started`/`received`/`opened` **triple** per recipient, not a
pair, because `switch/service.py:173` kicks each accepted recipient in turn.

⚠ **Why it went unnoticed: the drift check was `rg -l '"v": ?2' docs/`** —
hardcoded to the version it was written for. At v3 and then v4 it kept looking
for v2, found nothing, and reported clean. It is now derived from
`envelope.py:VERSION` and searches `range(2, VERSION)`, so v5 needs no edit.
**`"v": 1` is deliberately excluded** — the activity/alert stream is a separate
schema that is legitimately still v1, and flagging it makes the check noise.

**Two drift rows were re-labelled from ✅ FIXED to RECURRED.** The first had listed
`API.md:13,21,25,166,249` as the worst case; the recurrence hit lines 13, 22, 26,
167, 250 of the same file.

## 2026-08-21 — `cloneToAll` had two implementations; the newer one is gone

**A duplicate I introduced on 2026-08-19 and did not notice for two days.**
`office cloneToAll` has existed since `9a3658f` with seven tests. I ported
h-office's standalone version on top of it as `flock/office/clone_to_all.py`,
verified *that* copy live on h-oracle, and reported it as a new capability.

**What was false:** anything reading `cloneToAll` as newly added. It was not.

| | before today | now |
|---|---|---|
| `office cloneToAll` | `cli.py:_clone_to_all_command` | unchanged |
| bare `cloneToAll` | `flock.office.clone_to_all:main` | `flock.office.cli:clone_to_all_main` — delegates |
| output | two formats, one per spelling | one: `summary: cloned=N skipped=N failed=N` |
| exit on a bad `-a` | `2` from the copy, `1` from the office | `1` |

⚠ **The copy was worse, and the tests already said so.** It dropped
`_clone_to_all_command`'s `shutil.rmtree` of a half-written clone, so a failed
clone left a directory that every later run read as *"exists, skipped"* — a
permanent gap needing manual repair. `test_clone_to_all_removes_partial_directory_after_failure`
covers that and my copy had no equivalent. It also always fetched from the
network, where the original reuses a clone an agent already has.

**Found by** reconciling `TODO.md` against the tree and noticing
A dated verification record noted a passing `cloneToAll` run twelve days before I
"added" it. ⚠ **No gate could have caught this** — both implementations passed,
every citation resolved, and the suite was green at 395 with the duplicate in it.

## 2026-08-15 — wire v2 → v3: fixed-width L2 header

**Build 72.** A frame is now **191 ASCII header bytes** then an **opaque JSON
body**, replacing one flat JSON object.

| offset | width | field |
|---:|---:|---|
| 0 | 1 | `v` = `3` |
| 1 | 32 | `stream_id` |
| 33 | 32 | `correlation_id` |
| 65 | 63 | L2 `source` |
| 128 | 63 | L2 `destination` |
| 191 | — | body: `kind`, `ts`, `l3`, `payload` |

**Why:** the switch is an L2 device and must not read the payload. It was
decoding the whole frame to reach two fields — 4,381 µs at 1 MiB nested, against
3.15 µs now.

### ⚠ What this made false

- **`"v": 2` everywhere.** Corrected in `API.md`, `CONTRACTS.md`,
  `LLD-bus-and-switch.md`. **Left alone in `BUILD-53-*` and `BUILD-63-*`** — those
  are dated records, not claims about today.
- **`DESIGN-layers` §6's caveat** that the switch is "*approximately*
  header-independent". Now discharged, with the before/after in place.
- **Frames grew 36 bytes** (315 → 351 at a small payload) — fixed-width padding.
- **`file:line` citations drifted** in three older docs. Any wire change does
  this.
- ⚠ **The dead-letter boundary moved.** A **corrupt body** now dead-letters at the
  **port**, not the switch — the switch cannot judge what it cannot read. It
  retains `stream_id` and the real recipient, so `analyse-run.py` still joins
  through it. A **malformed header** stays `unknown`: there is no trustworthy key
  to attribute it to.

### Unchanged, deliberately

- **The JSON an API client receives** — same eight keys, only `v` differs.
  Clients never see the wire form.
- **Throughput** — 848.52 → 853.87/s, +0.63%. This build was for an invariant,
  not for speed.
- ⚠ **`RPUSH` still scales with payload**, and that is correct. The switch may
  **carry** any payload and must **interpret** none.

---

## 2026-08-19 — the REST API door is opt-in, and setup asks for ports

**Contract:** `API_ENABLED` defaults to **0**. The api door does not start unless
asked. Liveness when it is off is the switch plus Redis, not `/health`.

`setup.sh` now asks which doors to open and on which **host** ports, defaulting
to the first free one and refusing a port already in use.

### ⚠ What this made false

- **"A tenant serves :8080."** It serves it only with `API_ENABLED=1`. Anything
  assuming the door is present — including `accept.sh`, `plumbing-check.sh` and
  every scenario that enrols over HTTP — must set it.
- **"`setup.sh` writes a working api config."** It wrote `API_TOKEN` and
  `API_PORT` and never `API_ENABLED`, so between the default change and this
  entry it generated a `.env` for a door that would not start, and printed the
  URL anyway.
- ⚠ **"Ports are fixed at 8080/8081."** They were hardcoded in `setup.sh` while
  the compose project was already per-tenant — so a second tenant on one host
  came up with a working door nobody could reach. `compose.yaml:53` had recorded
  that failure; the fix never reached `setup.sh`.

### Unchanged, deliberately

- **The session console stays on by default.** It carries the same token but is
  the only way to see a tenant without `docker exec`.
- ⚠ **Telegram is a client, not a door.** `clients/telegram/bot.py` speaks HTTP
  to the api door, so it depends on it; the prompt enables the API rather than
  offering an independent choice.


## 2026-08-15 — wire v3 → v4: frozen reserved header, TTL and hops

**Build 73.** A frame is now **256 ASCII header bytes** followed by the same
opaque JSON body. Bytes 191–193 are a three-digit TTL (default 016), bytes
194–196 are a three-digit hop count (starting 000), and bytes 197–255 are
reserved. Reserved bytes are ignored; future allocated fields may use them
without moving the body boundary. An allocated three-byte field containing
spaces is absent.

Every forward decrements TTL and increments hops using fixed-offset splices.
TTL reaching zero dead-letters at the switch and issues no kick. The switch
still never reads or decodes the body.

### ⚠ What this made false

- **Wire v3 and a 191-byte header.** Version 4 is a hard break; transport queues
  are purged at boot, while durable boards and streams survive.
- **HEADER_WIDTH may move for each new L2 field.** It is frozen at 256. A future
  field consumes the 59 reserved bytes or requires a new wire version.
- **Frames grew 65 bytes** (351 → 416 at the same small-payload fixture).
- **API-delivered frames have eight keys.** They now also expose integer `ttl`
  and `hops`; the JSON body fields themselves are unchanged.

### Unchanged, deliberately

- ⚠ **This does not close the autonomous-agent reply loop at `TODO.md:33`.** A
  reply is a new frame with a fresh correlation ID and a fresh TTL because the
  pane receives no lineage. TTL bounds forwarding of the same frame; it does
  not bound a conversation that creates new frames.
- The switch's payload-independence invariant. Interleaved h-oracle measurement
  was flat at 3.35–3.36 µs from 16 B through 1 MiB across both payload shapes.

---

## 2026-08-15 — v4 verified against real model output (no code change)

**Build 74.** Recorded because it **discharges a claim**, not because anything
moved. Three tmux agents on Nemotron, 13 model-originated frames, bytes compared
at egress and ingress out of the captured Redis AOF.

**v4's claim was that the body is opaque bytes nothing between sender and port
interprets.** Now evidenced from a source we do not control: newlines, code
fences, quotes, backslashes, Unicode, JSON-inside-JSON and **the empty string**
all arrived byte-identical across all 17 forwarded frames. `ttl`/`hops` correct
17/17; the source-stamp control passed with the body unchanged through the splice.

### ⚠ Two findings that are NOT closed

- **`delivery_unverified` fired on 4 of 13, all four to one agent** (30.8%). This
  is the **first real reading** of `watchdog/verification.py`, which only applies to
  `tmux` ports and was never exercised by an api or synthetic run. A
  concentration on one agent is a signal, not noise — **it is unknown whether
  that agent failed to process or the heuristic false-positives.** ⚠ Relevant
  before the watchdog leans on any progress signal.
- **One model send produced an exact empty-text payload** and traversed every
  stage successfully. Counterexample to reading "one send command" as "one
  non-empty message" — anything counting messages must not assume content.

**`received -> opened` p50 507 ms**, against 506 ms on the failed first run. That
is `PASTE_ENTER_DELAY` landing where it should, on the path real agents use — the
first in-situ confirmation rather than an inference.

---

## 2026-08-15 — custody `destination` is always the real recipient

`port/deliver.py:deliver_unroutable` emitted `received` and `dead_lettered`
through `emit()`, which takes `destination` from the envelope's **L2
destination**. For a broadcast that is `"all"`, so those records landed under
`(stream_id, "all")` instead of `(stream_id, agent)`.

**Contract:** every custody record's `destination` names the **receiving agent**,
never the envelope's L2 destination. `analyse-run.py` joins on
`(stream_id, recipient)` and depends on it.

### ⚠ What this made false

- **Nothing in the docs** — this was code disagreeing with itself, not with a
  document. Found while reviewing documentation drift.
- ⚠ **Any broadcast custody analysis run before this date** on a tenant with an
  unroutable `port_type` under-counted that agent's `received`/`dead_lettered`.
  Narrow path; no published figure is known to depend on it.

---

## 2026-08-14 — the performance host, and what it invalidated

Not a code change. Recorded because it **falsified published numbers**.

Identical scripts, same day: **6.5/s on the lab, 832/s on h-oracle.** The switch
read 7–9 ms there and 0 ms here; spawn 622–677 ms against 23 ms.

### ⚠ What this made false

- **Every throughput figure in 25 `BUILD-*.md` files** — all 4-vCPU numbers, none
  naming a host.
- **Build 71 (kicker)** — cancelled. The 11 ms it existed to remove was four-vCPU
  contention, 0 ms on real hardware.
- **Build 67/68's CPU magnitudes** (1084%, 1366%) — impossible above 400% on four
  vCPUs. Withdrawn; the count evidence survives.

**Standing split, now in `BUILD-CONVENTION` §3.0:** lab for **correctness**
(contention surfaces races), h-oracle for **performance**. Never quote a lab
throughput number.

---

## Earlier

Before 2026-08-15 there was no changelog, so contract changes have to be read out
of `BUILD-*.md`. Two that bite most often:

- **`kick_started` (build 65)** made a delivered unicast **six** records, not
  five. ⚠ **Four docs still said five until 2026-08-15** — the change was made and
  never propagated. This file exists so that stops happening.
- **`vab` → `port_type`, `adapter` → `port`, `router` → `switch`** (build 56). The
  bulk rename also hit `BUILD-46-*.md`, which describes **h-vab, a separate
  project**, producing a dead URL and a paragraph contradicting itself. Repaired
  2026-08-15. ⚠ **Do not run a bulk rename over docs describing other projects.**
