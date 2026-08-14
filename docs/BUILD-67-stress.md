# Build 67 — the stress test: faults nobody has ever injected

> **Base on `main`.** Branch `tmux/build-67-stress`, push to origin.
> Owner: `tmux` — you built `conservation.sh` and this extends it.
> ⚠ **After build 66 merges.** Its drain changes the behaviour under test.

## 1. ⚠ What this can and cannot test

The operator asked for a stress test of "core switch and watchdog functionality".

**The watchdog does not do any of this yet.** `DESIGN-layers` §8 is BLOCKED — the
recovery design does not compose, and `watchdog/service.py` never inspects
ingress, never re-kicks and never dead-letters, as its own docstring says.

**So this build tests the SWITCH and the PORT under faults, and characterises
what a watchdog would need to see.** That is the honest scope, and it is the
right input to designing one. ⚠ **Do not build watchdog behaviour here.**

## 2. The faults, none of which has ever been injected

Build 58 injected switch kills and port kills. These are different, and each was
surfaced by a review rather than by a test.

**A. Case B — a destination that is enrolled, permitted, and cannot consume.**
⚠ **Ingress is unbounded**: retention trims only `dead` and `tasks.done`, and
every `maxlen` in the tree is on a stream, never a list. Nothing caps depth,
nothing dead-letters on full, nothing alerts.
- **Measure**: depth over time, Redis memory, and CPU — every forward still
  spawns a port that achieves nothing (~230 ms each)
- ⚠ **Report the ceiling**: at a steady send rate, how long until memory becomes
  a problem? A number, not "unbounded"

**B. The stale `delivering` tag.** `run_port` acquires with `HSETNX` and clears
only in `finally`, which `SIGKILL` skips. Audit row 16 recorded non-expiry and
non-takeover as **deliberate** — it prevents two ports delivering the same agent,
which protects at-most-once.
- Kill a port **after** it holds the tag, then send to that agent
- ⚠ **Expected: the destination is wedged permanently and every later kick
  spawns a process that waits forever.** Confirm it, and **count the processes**
- ⚠ **This is worse than a strand** — a strand loses one frame; this wedges the
  destination *and* accumulates processes

**C. `api` and `control` participants.** `Watchdog._agents()` filters
`port_type == "tmux"` (`bus`'s review). Whatever a watchdog watches later, it
would not see these today.
- Strand an **api** client and a **control** participant; confirm both can strand
  and that nothing observes them

**D. The `blpop`-to-`emit` gap**, now understood: `service.py:68` removes the
frame before any record exists, so a switch killed there loses it with **zero
records**. Build 66 hit this twice.
- ⚠ **Use FIFO bracketing to attribute** (`BUILD-CONVENTION` §3) — a frame's own
  timestamps do not exist, but its same-source neighbours bound when it was at
  the head

## 3. ⚠ What must NOT regress

**Zero duplicates.** That is the absolute half of at-most-once and it has held
through every run. Loss is permitted and must be **attributable**; a duplicate
is a defect at any count.

## 4. Done when

- each fault in §2 injected, with numbers rather than adjectives
- ⚠ **negative controls** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1 — for
  each fault, show the harness detects it **and** show it reports clean when the
  fault is not injected. **A stress test that always finds something is as
  useless as one that never does**
- for each fault, one line: **what would a watchdog have to observe to catch
  this?** That is the deliverable that unblocks §8
- `python3 -m pytest -q` green
- ⚠ one h-flock tenant at a time, lab-local output, checksummed evidence

## 5. Reporting

`jira done`, then message `architect` with the numbers per fault, the case-B
ceiling, the wedged-agent process count, whether api/control strand, and the
per-fault "what would a watchdog need to see" list.
