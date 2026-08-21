# DRIFT — where the docs disagree with the code

> ⚠⚠ **THE CODE IS THE SOURCE OF TRUTH. Every row below is a doc to fix, never a
> code change to make.** If a row looks like the code is wrong, that is a
> separate finding and belongs in [`TODO.md`](TODO.md) — do not "fix" the code to
> match a sentence.

⚠⚠ **STATUS 2026-08-21: §1 RECURRED at v4 and §3 was only half-fixed.** Both had
been marked ✅ FIXED on 2026-08-15 and neither held. §1 came back in the same
file (`API.md`) at the same lines ±1, because its check was pinned to the literal
version it was written for. §3's number was corrected in the sentence while the
list beneath it still showed five. §4 remains open; §5 is at 32 near misses.

⚠ **A ✅ in this file means "was true when written", exactly like every other
claim here.** Re-run the command in the row. The two rows that recurred are the
argument: **the fix was applied to the instance, and the thing that would catch
the next instance was not.** Contract changes are tracked forward in
[`CHANGELOG.md`](CHANGELOG.md), which caught neither, because it records what
changed and nothing reads it back against the docs.

**Generated 2026-08-15 at the v3 merge; §1, §3 and §8 revised 2026-08-21 at v4.**
This file goes stale the moment code moves; **re-derive it, do not trust it.**
Every row states how to re-check it in one command.

## Why this exists

Docs are **12,651 lines across 77 files** against **5,529 lines of code** — 2.3×,
and 55 of the 77 files are `BUILD-*.md`. That volume cannot be kept true by
reading. The rows below are the divergences that mechanical checks and targeted
greps actually found, ranked by whether someone can be misled into wrong work.

---

## 1. ⚠ RECURRED at v4, fixed again 2026-08-21 — was: the wire is v3, seven docs said v2

⚠ **This row was marked ✅ FIXED and then happened again, one version later, in
the same file at the same lines.** Build 73 took the wire to v4/256 and updated
`HLD.md` alone. On 2026-08-21 `API.md` still said `v: 3` and "191-byte header" at
lines 13, 22, 26, 167, 250 — the v3 fix had touched 13, 21, 25, 166, 249. It also
still called `v` *"Always `2`"* in the field table, which means that line survived
**both** corrections. `CONTRACTS.md:101` said "hard v3" and `DESIGN-layers.md`
said `raw[:191]`.

⚠ **v4 additionally added two client-visible keys, `ttl` and `hops`**, so
`API.md`'s "same eight keys" was wrong in a way that breaks a client validating
against a closed schema — the first time this row's drift was more than a label.

**Why it recurred:** §8's check was `rg -l '"v": ?2' docs/`, hardcoded to the
version it was written for. It has been made version-derived. **The lesson is not
"re-read the docs" — it is that a check containing a literal of the thing it
guards stops guarding it at the next bump.**

**Code today:** `bus/envelope.py` — `VERSION = "4"`, `HEADER_WIDTH = 256`,
`TTL_START = 191`. `build()` returns `{"v": 4, …}` with `ttl` and `hops`.

**The v3 round, kept because the shape of the recurrence is the point:**

**Code (then):** `bus/envelope.py` — `VERSION = "3"`, `HEADER_WIDTH = 191`. `build()`
returned `{"v": 3, …}`. Verify:

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

**Code:** `parse_for_switch` (`bus/envelope.py:217`) slices `raw[:HEADER_WIDTH]`
and decodes only those bytes; `_header_text` (`:189`) does that decode **before**
any other. ⚠ **This row said `raw[:191]` until 2026-08-21** — the width is 256 at
v4, and writing the literal instead of the constant is the §1 mistake in
miniature. Verify:

```bash
rg 'json\.' src/flock/switch/service.py      # must be empty
```

| doc | says | fix |
|---|---|---|
| `DESIGN-layers.md:449` | "`parse_for_switch` decodes the whole JSON — L3 and payload included" | ⚠ **now false.** This was the standing open item; build 72 closed it |
| `DESIGN-layers.md:424` | "the switch still decodes the whole frame to reach L2" | same |

⚠ **§6 marks the switch ✅ done with the caveat "approximately header-independent,
not truly so."** The caveat is now discharged — say so, and record that the test
it named (frames growing substantially) was run and is what produced v3.

## 3. ⚠ FIXED IN THE SENTENCE ONLY — three different custody-record counts, and the code said neither

⚠ **Closed on 2026-08-21, and the six-month lesson is in how it half-closed.**
`LLD-bus-and-switch:707` was corrected from "five" to "**six** transport records"
— and **the code block directly beneath it still listed five**, missing
`kick_started`. The file contradicted itself in adjacent lines and read as fixed
because the sentence the table below cites was the part that got edited.

⚠ **The broadcast asymmetry this row identified was never written down anywhere
until the same day.** It is now in `LLD-bus-and-switch` as a
`kick_started`/`received`/`opened` **triple** per recipient, cited to
`switch/service.py:173`.

**Checking a count means counting the list, not reading the number in front of
it.** Nothing mechanical catches this; see §8.

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

# §1 — read the version from the code, derive the superseded ones, find docs
# still showing them. Self-updating: at v5 it looks for 2|3|4 with no edit.
V=$(python3 -c "import sys;sys.path.insert(0,'src');from flock.bus.envelope import VERSION,HEADER_WIDTH;print(VERSION)")
W=$(python3 -c "import sys;sys.path.insert(0,'src');from flock.bus.envelope import VERSION,HEADER_WIDTH;print(HEADER_WIDTH)")
OLD=$(python3 -c "print('|'.join(str(i) for i in range(2,$V)))")
echo "current wire: v$V, ${W}-byte header — looking for v($OLD)"
grep -rnE "\"v\": *($OLD)" docs/ --include='*.md' | grep -vE 'BUILD-|VERIFIED-|CHANGELOG'
```

⚠ **The range starts at 2 on purpose. `"v": 1` is NOT drift** — the activity and
alert event streams are a *separate* schema that is legitimately still v1
(`LLD-watchdog:77`, `LLD-api:133`, `API.md:541`). A check written as "anything
that is not the current version" flags nine correct lines, and a check that
cries wolf nine times is one nobody runs. **The wire-frame versions and the
event-stream version are different numbers that happen to share a key name.**

⚠ **The §1 check used to read `rg -l '"v": ?2' docs/` — pinned to v2.** When the
wire went to v3 and then v4 it kept looking for v2, found nothing, and reported
clean while `API.md` documented the wrong version to external developers **twice
in a row**. A check written against a literal version expires the moment that
version does; derive it from the code instead. **That single hardcoded `2` is the
whole reason §1 recurred**, and it is the most useful thing in this file.

⚠ **There is still no check for §3 or §4** — prose claims about counts and
numbers are invisible to tooling, which is how `LLD-bus-and-switch` came to say
"six" above a list of five. That is the actual gap, and it is why this file is a
snapshot rather than a gate.
