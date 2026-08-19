# CHANGELOG — what changed, and what it invalidated

> **Contract changes only.** Wire formats, event names, key shapes, endpoints,
> limits — anything another component or an external client can depend on.
> Refactors and fixes are in git; they do not belong here.

> ⚠ **Every entry names what the change made FALSE.** That is the point of this
> file. A change log that lists only what was added leaves the reader to discover
> which docs, scripts and assumptions just went stale — which is how
> [`DRIFT.md`](DRIFT.md) reached two blocking rows in nineteen builds.

---

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
  document. Found while reviewing for [`DRIFT.md`](DRIFT.md) §6.
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
  naming a host. See `DRIFT.md` §4.
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
