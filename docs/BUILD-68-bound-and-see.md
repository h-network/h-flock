# Build 68 — bound the queue at forward time, and see the pop

> **Base on `main`.** Branch `bus/build-68-bound-and-see`, push to origin.
> Owner: `bus` (`flock/switch`, `flock/bus`, `CONTRACTS.md`).

## 1. Bound ingress at forward time — and it fixes CPU, not memory

`api` proposed this in review; **build 67's measurements changed why it matters.**

| case B, measured | |
|---|---|
| 1 GiB of Redis | **82.3 hours** / 2,929,238 frames |
| CPU | **median 1084%, peak 1366%** |

⚠ **Memory was never the problem — three and a half days is not an outage. The
CPU is.** Ten to thirteen cores burn continuously on ports spawned for a
destination that cannot consume, and **every one of those spawns is caused by a
forward that should not have happened.**

**So bounding ingress stops the spawns, not just the growth.** A full queue
means the switch dead-letters instead of forwarding — and a dead-letter issues
**no kick**, so no port spawns. That is the fix for 1084% CPU.

⚠ **And it is free.** `RPUSH` **returns the new list length**. The switch already
calls it (`switch/service.py:105,120`), so the bound is a comparison on a value
it is handed — no `LLEN`, no extra round trip, no new read.

- `INGRESS_MAX`, env-overridable. ⚠ **State the default you chose and why.**
  Build 67 says ~10 forwards/s and 366.56 bytes/frame, so pick a number against
  a stated horizon rather than a round one
- over the bound → dead-letter with a reason naming the destination and the depth
- ⚠ **This is synchronous attribution**: a record at the moment, not a watchdog
  culling later while racing a live port

## 2. Emit `popped` immediately after `BLPOP`

`switch/service.py:68` removes the frame from egress before any record exists, so a
switch killed there loses it with **zero** records. Build 66 hit this twice;
build 67 reproduced it deliberately.

⚠ **This is a BOUNDED improvement and the spec says so.** `bus` established the
residual: a joinable `popped` needs `stream_id`, which needs parsing raw that has
not been validated; and `SIGKILL` can still land between `BLPOP` and the stdout
write. **It shrinks the invisible window. It does not close it.**

⚠ **Do not close it with a reliable-queue pattern.** `BLMOVE` to a processing
list would convert at-most-once toward at-least-once, and that guarantee is not
to be acquired as a side effect of an observability fix.

State in the report what remains invisible after the change.

## 3. `CONTRACTS.md` — your own review findings

- §4 says a kick keeps no record; **build 65 added `kick_started`**
- `flock.port.runner` does not exist — it is `flock.port.deliver`
- the five-versus-six custody count (line 250 against 258–264 and 273)
- the throughput arithmetic is stale: with the 500 ms paste delay, paste is the
  larger component and the total is nearer 1/s than 2/s
- ⚠ **malformed-frame `dead_lettered` emits `stream_id: unknown`**, so that path
  is **not joinable** although `CONTRACTS` calls `stream_id` the join key. Say
  what is knowable about such a frame instead of implying a join that cannot
  happen

## 4. Done when

- ⚠ **negative controls** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: drive
  a queue over `INGRESS_MAX` and show the dead-letter **and the absence of a
  kick**; then show a normal send still forwards. And show `popped` present for a
  frame that previously had no record
- ⚠ **re-run build 67's fault A** and report CPU. **The prediction is that CPU
  falls sharply once forwards stop spawning ports.** If it does not, bounding
  fixed memory only and the spawn cost is elsewhere — say so
- `fabric-bench` 100×20: 2,000/2,000, zero dead letters, **≥ 6.45/s**. ⚠ The
  script now prints two decimals; **quote the exact figure**
- `python3 -m pytest -q` green (375 at the time of writing)
- `container/accept.sh` green; one tenant at a time; lab-local output

## 5. Reporting

`jira done`, then message `architect` with the chosen `INGRESS_MAX` and its
horizon, the CPU before and after on fault A, what remains invisible after §2,
and the exact bench figure.
