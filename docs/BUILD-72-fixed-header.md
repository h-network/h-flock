# Build 72 — v3: a fixed-width L2 header the switch reads without parsing

> **Base on `main`.** Branch `bus/build-72-fixed-header`, push to origin.
> Owner: `bus` (`flock/bus/envelope.py`, `flock/switch/service.py`, `flock/port`).

> ⚠ **A trial, like builds 43 and 46. "No" is a successful outcome.** What fails
> this build is a half-migration nobody wants to throw away. If the measurement
> in §5 says the cost is invisible at our frame sizes, **say so and stop** — that
> is the build succeeding, not failing.

## 1. What this is, and why it is not new

`DESIGN-layers.md:433` already records the problem, the remedy and the test:

> ⚠ **It is *approximately* header-independent, not truly so.**
> `parse_for_switch` decodes the whole JSON — L3 and payload included — to read
> L2. A real switch reads fixed-offset bytes and never touches the payload. At
> +77 bytes that is invisible against a 1.7 ms Redis round trip, which is why
> the number did not move. **If frames grow substantially the switch starts
> paying for headers it does not read**, and the fix is framing that exposes L2
> without parsing the rest. That, not throughput, is what would falsify "the
> switch is done".

This build runs that test and, if it fails, applies that fix. ⚠ **The switch is
currently marked ✅ done in `DESIGN-layers` §6 on the strength of a measurement
taken at +77 bytes.** This is the criterion that claim was published with.

## 2. The header

Fixed width, ASCII, **space-padded on the right**. Total **191 bytes**, then the
body.

| offset | width | field | contents |
|---:|---:|---|---|
| 0 | 1 | `v` | `3` |
| 1 | 32 | `stream_id` | `uuid4().hex` |
| 33 | 32 | `correlation_id` | `uuid4().hex` |
| 65 | 63 | L2 `source` | agent name |
| 128 | 63 | L2 `destination` | agent name, or `all` |
| 191 | — | body | JSON: `kind`, `ts`, `l3`, `payload` |

⚠ **63 is not a new limit.** `bus/keys.py:5` already enforces
`^[a-z0-9][a-z0-9-]{0,62}$` on every name, because it is also the Redis key
contract. Fixed width costs nothing that is not already committed to.

⚠ **Space padding, not nulls** — `redis-cli LRANGE` stays readable and the
columns line up. That readability is the only thing this build trades away, so
do not trade it for nothing.

## 3. The switch stops parsing

```python
src = raw[65:128].rstrip()
dst = raw[128:191].rstrip()
```

No `json.loads`. The body after byte 191 is **opaque bytes** the switch never
decodes, validates or re-encodes.

⚠ **Still validate the two names** against `SEGMENT_REGEX` after `rstrip` — a
malformed name reaches a Redis key otherwise. A regex over ≤63 bytes is constant
and is not what this build is removing.

⚠ **The source stamp becomes a splice.** `switch/service.py:144` currently does a
full `json.dumps` of a frame it never read. It becomes a 63-byte in-place write.
**The body must come out byte-identical** — that is a gate in §5.

## 4. ⚠ One behaviour change, and it must be reported not hidden

Today the switch dead-letters an unparseable frame at `switch/service.py:134`. In v3 it
can only judge the **header**. A frame with a valid header and a corrupt body
will be forwarded and dead-lettered at the **port** instead.

⚠ **This is a real move of the `dead_lettered` stage between components**, not an
implementation detail. It is arguably correct — a switch should not adjudicate a
payload — but it changes what a custody log looks like for that fault, and
`analyse-run.py` joins on `(stream_id, recipient)`. **Say what it does to that
join.**

## 5. Measure first, and the sweep is the point

⚠ **Run §5.1 BEFORE writing any code.** If the answer is "invisible", this build
stops there and that is a result worth having.

### 5.1 Baseline sweep on the CURRENT code

`switch-bench.sh` has `STATIONS` and `ROUNDS` but **no payload-size knob**. Add
one (`PAYLOAD_BYTES`, default keeps today's `{"text":"r0"}`), then sweep:

| payload | what it answers |
|---|---|
| ~16 B (today) | reproduces the published figure |
| 4 KB | a realistic agent message |
| 64 KB | a large paste |
| 1 MB | the API door's own limit (`api/app.py:640`) |

Report `popped -> forwarded` p50/p95 per size, **on h-oracle** — the lab's four
vCPUs turned an 11 ms artefact into a build we cancelled.

⚠ **Paired, same session** (`BUILD-CONVENTION` §3). Fresh tenant per run.

### 5.1b ⚠ The §5.1 trigger as written was WRONG — decompose before believing it

**Result of §5.1** (`bus`, h-oracle, 2000/2000 per run, zero dead/parse):

| payload | `popped -> forwarded` p50 / p95 |
|---|---|
| 16 B | 0 / 1 ms |
| 4 KiB | 0 / 1 ms |
| 64 KiB | 0 / 1 ms |
| 1 MiB | **1 / 2 ms** |

⚠ **This does not establish a slope, for three reasons, and all three are my
spec's fault rather than the measurement's.**

1. ⚠ **The instrument's floor is 1 ms.** `bus/logging.py:46` stamps `ts` with
   `timespec="milliseconds"`. Three of the four points read **0**, meaning
   "below what the log can see". A slope cannot be computed from censored data —
   `0 → 1` is one quantisation bucket and is consistent with anything from
   0.51 ms to 1.49 ms. **This is build 70's lesson again: the variance was the
   instrument.**

2. ⚠ **`popped -> forwarded` is not the parse.** It contains `json.loads`, the
   `json.dumps` on a source stamp, **and the `RPUSH` of the full bytes**.
   Framing removes the first two and **cannot remove the third** — moving a
   megabyte is what forwarding *is*. If the +1 ms is Redis carrying 1 MiB, this
   build buys nothing.

3. ⚠ **Payload shape matters as much as size.** `{"text": "<1 MiB of one
   string>"}` is a scan; 1 MiB of nested objects is allocation. They differ by
   an order of magnitude in `json.loads`, and only the second is what framing
   avoids. **State which was measured.**

**Do this before §5.2** — in-container, `time.perf_counter()`, n≥200, medians,
each operation timed *alone* at 16 B / 64 KiB / 1 MiB:

| | what it tells us |
|---|---|
| `json.loads(raw)` | **removable by framing** |
| `json.dumps(frame)` | **removable** (source-stamp path only) |
| `r.rpush(key, raw)` | ⚠ **NOT removable** — the floor this build cannot beat |

Repeat with **both** payload shapes: one long string, and nested objects.

⚠ **§5.2 proceeds only if `json.loads` alone is a material fraction of the
total.** If `RPUSH` dominates, the correct outcome is **"no", and the switch is
payload-independent in practice** — which the 16 B–64 KiB rows already suggest,
since 64 KiB covers essentially all real traffic.

### 5.2 If and only if the parse — not the byte movement — is the cost

Then implement §2–3 and re-run the identical sweep. Expect:

| | expect |
|---|---|
| `popped -> forwarded` | **flat across all four payload sizes** |
| end-to-end throughput at ~16 B | ⚠ **UNCHANGED** — the switch is ~1% of the path |
| frame size at ~16 B payload | **grows ~60 B** (191 fixed vs ~130 packed) — state it, do not bury it |

⚠ **If end-to-end throughput moves at small payloads, something unexpected
happened — report it, do not celebrate it.**

## 6. ⚠ v3 is a hard break, and that is already handled

`_decode` rejects any `v != 2` today; v3 rejects any non-`3`. There is no
dual-read window. ⚠ **This was already survived once** — `DESIGN-layers:442`
records that build 53 made v2 hard and build 63 resolved the persistence
coupling: `container/entrypoint.sh` runs `purge_transport` at boot, clearing
`ingress`/`egress`/`dead`/`delivering` while boards and streams survive. **Verify
that still holds for v3 rather than assuming it.**

## 7. Done when

- sweep from §5.1 reported **before** any code change
- if implemented: switch performs **no `json.loads`** on the forwarding path
- body **byte-identical** sender → port, including across a source stamp
- `python3 -m pytest -q` green (383 at the time of writing)
- `container/accept.sh` green; conservation unchanged: **zero duplicates**
- ⚠ **negative controls** per `BUILD-CONVENTION` §1: a bad header dead-letters at
  the switch; a bad body dead-letters at the port; both appear in the log
- one tenant at a time, ⚠ **fresh tenant per run** — a reused one produced 2100%
  coverage and nearly passed as clean

## 8. Reporting

`jira done`, then message `architect` with the §5.1 sweep table, whether you
implemented at all, the frame-size delta, what the dead-letter move did to the
`analyse-run.py` join, and confirmation that end-to-end throughput did **not**
move.
