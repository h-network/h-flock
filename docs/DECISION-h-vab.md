# Decision — h-vab: no migration, three ideas taken

**Date:** 2026-08-13. **Status:** settled. **Trial:** build 46, run by `bus`.

⚠ **This record exists because the trial branch was deleted.** Without it, the
only trace of why h-flock is not built on h-vab would be absent from the
repository, and the question would be re-asked from scratch in six months.

## The verdict

**No migration.** The forwarding core fits and custody survives, but h-vab's
contract requires a **synchronous `port_congested` and `packet_too_large`**,
where h-flock's `office send` has never exposed a capacity outcome. An agent can
observe the difference. `BUILD-46-vabtrial.md` §5 named that as disqualifying
before the trial started — *"the edge has to change — that is the product, and
it is not on the table"* — and `bus` held to it rather than relaxing it.

⚠ **A second reason, weighted higher by me than by the trial:** h-vab has **no
`pod` level**. `domain/station` maps to tenant/agent and the third address level
does not exist — and that third level is the RD, which
[`DESIGN-layers`](DESIGN-layers.md) §4 calls the precondition for inter-pod
routing. As it stands h-vab cannot be the shared orchestration layer for h-flock
and h-cli without gaining one.

## Measured, not just reasoned

| | `main` | h-vab trial |
|---|---|---|
| end to end, 100×20, isolated | **2.64/s** | **2.24/s** (15% slower) |
| forwarding decision, 100-station roster | 498 µs | 957 µs |
| forwarding decision, 1,000-station roster | 1,646 µs | **5,623 µs** |

The trial rebuilt the forwarding table from a full roster read **per packet**
(`HGETALL` against `main`'s single-field `HEXISTS`), so it was slower than what
it replaced. ⚠ **That is the implementation, not the design** — see below.

## Taken, deliberately

1. ✅ **The derived FIB** — the switch reads a table holding only
   destination→ingress, never the roster. Recorded in `DESIGN-layers` §3.1.
   Arrived as much from the operator's MPLS LSP framing as from h-vab.
   **Design only; unbuilt.**

## Refused, or not taken yet

2. ⚠ **Bounded queues with synchronous backpressure** — the decisive blocker
   above. Worth doing **on its own merits as a versioned edge change**: the
   fabric submits at ~200/s and drained at ~3/s when measured, so backlog is the
   resting state, not an edge case. **Not started, not decided.**
3. ⚠ **Bound `Port` handles** for structural source attestation — the only way
   forgery becomes impossible rather than discouraged, but it changes every
   caller's interface. **Not started, not decided.**
4. ❌ **The three-program split** (adapter/switch/router as separate processes) —
   does not map to h-flock's process boundaries.
5. ❌ **Correction becomes rejection** — h-vab dead-letters a raw v1 envelope
   where build 36 corrects and stamps it. Losing that is a regression here.

⚠ **The risk this table exists to prevent:** taking 1, then 2, then 3 one at a
time and ending up h-vab-shaped without ever deciding to be — then discovering
it later as though it had always been intended. That is the same failure
`BUILD-44` warned lanes about with the gateway fork. **Anything moving from
"refused" to "taken" is a decision, and it gets written here.**

## Recovery

The branches were deleted after their contents were lifted here. If the trial
code is ever wanted again:

| branch | last commit |
|---|---|
| `bus/build-46-vabtrial` | `4c25929` "Report h-vab adaptation trial" |
| `vabtrial` (the task spec) | `51dcc5a` |

The trial added `src/flock/fabric/{packet,service,switch}.py` and compatibility
seams in `bus/doors.py` and `router/service.py`. It was anchored at `e0efde4`
and never merged; by deletion `main` had moved 24 commits past it, so it
predates builds 47, 48, 50 and 51.
