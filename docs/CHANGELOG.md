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
