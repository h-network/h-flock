# DRIFT — where the docs disagree with the code

> ⚠⚠ **THE CODE IS THE SOURCE OF TRUTH. Every row below is a doc to fix, never a
> code change to make.** If a row looks like the code is wrong, that is a
> separate finding and belongs in [`TODO.md`](TODO.md) — do not "fix" the code to
> match a sentence.

⚠ **STATUS: §1 and §2 were the blocking rows and BOTH ARE FIXED (2026-08-15).**
§3 fixed in `CONTRACTS.md` and `LLD-bus-and-switch.md`. §4, §5 and §6 remain open
and are ticketed. Contract changes are now tracked forward in
[`CHANGELOG.md`](CHANGELOG.md), which is the thing that would have prevented most
of this.

**Generated 2026-08-15, against `main` at the v3 merge.** This file goes stale the
moment code moves; **re-derive it, do not trust it.** Every row states how to
re-check it in one command.

## Why this exists

Docs are **12,651 lines across 77 files** against **5,529 lines of code** — 2.3×,
and 55 of the 77 files are `BUILD-*.md`. That volume cannot be kept true by
reading. The rows below are the divergences that mechanical checks and targeted
greps actually found, ranked by whether someone can be misled into wrong work.

---

## 1. ✅ FIXED — the wire is v3, seven docs said v2

**Code:** `bus/envelope.py` — `VERSION = "3"`, `HEADER_WIDTH = 191`. `build()`
returns `{"v": 3, …}`. Verify:

```bash
python3 -c "import sys;sys.path.insert(0,'src');from flock.bus.envelope import VERSION,HEADER_WIDTH;print(VERSION,HEADER_WIDTH)"
```

| doc | says | severity |
|---|---|---|
| **`API.md:13,21,25,166,249`** | `"v": 2`, "version 2 frame schema" | ⚠⚠ **worst** — this is the **public** contract and clients now receive `"v": 3` |
| `CONTRACTS.md:101` | "The Redis wire is **hard v2**" | high — it is hard v3 |
| `LLD-bus-and-switch.md:753` | `"v": 2` in the frame example | high |
| `DESIGN-layers.md` | v2 throughout §7 | medium |
| `BUILD-53-frame.md`, `BUILD-53-bus-results.md`, `BUILD-63-persistence.md` | v2 | low — historical build records, **correct as history** |

⚠ **Only the first three need changing.** A build doc describing what was true at
build 53 is not drift; it is a dated record. **Do not rewrite history docs** —
that is how `BUILD-46` got its dead URL.

## 2. ✅ FIXED — the switch no longer parses the frame

**Code:** `parse_for_switch` (`bus/envelope.py:190`) slices `raw[:191]` and
decodes only those bytes; `_header_text` (`:162`) does `raw[:HEADER_WIDTH].decode`
**before** any other decode. Verify:

```bash
rg 'json\.' src/flock/switch/service.py      # must be empty
```

| doc | says | fix |
|---|---|---|
| `DESIGN-layers.md:441` | "`parse_for_switch` decodes the whole JSON — L3 and payload included" | ⚠ **now false.** This was the standing open item; build 72 closed it |
| `DESIGN-layers.md:424` | "the switch still decodes the whole frame to reach L2" | same |

⚠ **§6 marks the switch ✅ done with the caveat "approximately header-independent,
not truly so."** The caveat is now discharged — say so, and record that the test
it named (frames growing substantially) was run and is what produced v3.

## 3. ✅ FIXED — three different custody-record counts, and the code said neither

**Code:** 13 envelope events; a delivered unicast leaves **six** stages —
`sent, popped, forwarded, kick_started, received, opened`. Verify:

```bash
python3 -c "import sys;sys.path.insert(0,'src');from flock.bus.logging import _ENVELOPE_EVENTS;print(len(_ENVELOPE_EVENTS))"
```

| doc | says |
|---|---|
| `CONTRACTS.md:225` | "two records per component and **five** across a delivered envelope's life" |
| `LLD-bus-and-switch.md:707` | "envelope leaves **five** transport records across its life" |
| `TODO.md:402` | flags LLD §4 as saying "**four** records" |
| `TODO.md:380` | "A delivered unicast envelope leaves **five** records, not four" |

⚠ **`kick_started` (build 65) made it six** and no counting doc was updated.
`analyse-run.py`'s `STAGES` is the operative list.

⚠ **Broadcast differs and no doc says so:** `forwarded` is emitted **once with
`count=N`** and `destination:"all"` (`switch/service.py:169`), while the kicks and
everything downstream are per-recipient. So a broadcast **cannot** be joined
across `forwarded -> kick_started`.

## 4. ⚠ Every throughput figure older than 2026-08-14 is a 4-vCPU number

**25 `BUILD-*.md` files quote a `/s` figure.** Identical scripts measured
**6.5/s on the lab and 832/s on h-oracle**; the switch read 7–9 ms there and 0 ms
here. `BUILD-CONVENTION.md` §3.0 now records the split; the older docs predate it
and name no host.

⚠ **Do not edit 25 historical documents.** Add one line to each **only** where a
figure is quoted as a *current capability* rather than as that build's evidence.
Everything else is correctly dated. Build 71's header is the model.

## 5. ✅ FIXED (partly) — citation drift, was 30 near misses, now 15

`tools/check_citations.py` finds `file:line` references whose symbol has moved
more than 3 lines. **0 hard failures** (no dead paths); 30 near misses:

| file | count |
|---|---|
| `NAMING-tmux.md` | **15** |
| `BUILD-65-results.md` | 4 |
| `DESIGN-layers.md` | 2 |
| `BUILD-44-tmux-report.md` | 2 |
| `AUDIT.md` | 2 |
| five others | 1 each |

⚠ `NAMING-tmux.md` is half the total and is a **living** reference, not history —
fix that one. Re-check with `python3 tools/check_citations.py`.

⚠ **The v3 merge drifted three citations by itself.** Any wire change does this;
it is a cost of citing lines, not a failure of the docs.

---

## 6. ✅ FIXED — one real code inconsistency found while reviewing

⚠ **This is the one row where the fix is in the code, not the doc.**

`port/deliver.py:51 deliver_unroutable` emits `received` and `dead_lettered` via
`emit()`, which takes `destination` from `envelope.l2.destination`. Every other
custody site uses `_emit_for_recipient` (`bus/doors.py:24`), which pins
`destination` to the **recipient**.

For a broadcast those differ: the record lands under `(stream_id, "all")` instead
of `(stream_id, agent)` — **not the join key build 69 established**, and the key
`analyse-run.py` uses. Narrow path (unroutable `port_type`), real inconsistency.

## 7. Checked and CLEAN — recorded so it is not re-derived

- **Module structure.** No import cycles. `bus` imports nothing; everything
  imports `bus`; `tmux` is the only second layer. 266 functions, **median length
  10 lines**.
- **`CONTRACTS.md` §3 log shape** matches `bus/logging.py` exactly — stdout for
  daemons, `FLOCK_LOG_FILE` for panes, switch tails the spool.
- **Switch branch coverage.** All ten exits from `step()` write a record; no
  silent path.
- **`API.md:89` 1 MB payload limit** is real and enforced at `api/app.py:640`.

## 8. How to regenerate this file

```bash
python3 tools/check_citations.py                       # §5
rg 'json\.' src/flock/switch/service.py                # §2, must be empty
rg -l '"v": ?2' docs/                                  # §1
```

⚠ **There is no check for §3 or §4** — prose claims about counts and numbers are
invisible to tooling. That is the actual gap, and it is why this file is a
snapshot rather than a gate.
