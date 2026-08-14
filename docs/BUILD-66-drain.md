# Build 66 — the port drains until empty

> **Base on `main`.** Branch `bus/build-66-drain`, push to origin.
> Owner: `bus` (`flock/bus/doors.py`, `flock/port`).
> ⚠ **Small, and a prerequisite for the watchdog** — it removes most of what the
> watchdog would otherwise spend its time on.

## 1. Why

`receive()` handles **exactly one** envelope per invocation and returns. That is
why a kicked port dying before it pops strands a frame: the next kick drains the
*old* one and strands the *newest* instead — a permanent off-by-one, measured in
build 58 as 2 of 5 port kills.

**Draining until empty removes it.** A kick that dies costs nothing, because the
next port to run clears the backlog including the frame the dead one was kicked
for.

⚠ **The residual, which stays and is the watchdog's:** if the port handling the
**final** envelope dies and no further kick arrives, that frame strands. Build 58
hit exactly this because its producer had stopped. **Do not try to fix that
here** — it needs an observer and that is `DESIGN-layers` §8.

## 2. What to change

The kicked path drains: pop, deliver, pop again, until the queue is empty.

⚠ **Non-blocking only.** Build 51 put the kicked path on `LPOP` deliberately.
Draining must not reintroduce a blocking wait — pop until empty, then **exit**.
A port that lingers waiting for more work is a long-lived process, and that is a
different design with a supervision problem attached.

⚠ **Bound the loop.** A port that drains forever is a port that never exits, and
under a fast producer it would never catch up. Cap iterations or elapsed time,
exit, and let the next kick continue. **State the cap you chose and why.**

⚠ **At-most-once is untouched** — each envelope is still popped exactly once by
exactly one port. This changes how many envelopes one invocation handles, not
how many times any envelope is delivered.

## 3. Done when

- the kicked path drains; other callers unchanged and named in the report
- ⚠ **negative control** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: put
  **two** envelopes in an ingress queue, issue **one** kick, and prove **both**
  are delivered. Then revert to single-pop behaviour and show the test go red —
  **a drain that has never been shown to beat single-pop is not known to drain**
- `python3 -m pytest -q` green (371 at the time of writing)
- `container/accept.sh` green
- `fabric-bench` 100×20: 2,000/2,000, zero dead letters, **≥ 6/s**. ⚠ Compare
  against the current baseline of **6.45/s** — draining should help or do
  nothing, and **if it makes throughput worse I want to know why before it
  merges**
- ⚠ one h-flock tenant at a time, output to a lab-local file

## 4. Report explicitly

Whether the **strand rate changes**. Re-run build 58's `conservation.sh` at
`STATIONS=100 ROUNDS=100` with its injections and compare strands against
attempt 4's **two**. ⚠ **The prediction is that port-kill strands go to zero and
only a terminal strand can survive.** If that is not what happens, the model in
`DESIGN-layers` §8 is wrong and that is worth more than the build.
