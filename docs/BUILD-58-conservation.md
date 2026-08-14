# Build 58 — prove the framework holds: conservation under stress

> **Base on `main`.** Branch `tmux/build-58-conservation`, push to origin.
> Owner: `tmux`. ⚠ The harness can be written without the lab; `bus` has the lab
> for build 54. **Write first, run when it is free.**

## 1. What has never been tested

Everything we have proved is a happy path. The longest run in the project's
history is **six minutes**; the largest is **2,000 envelopes**; and **no test
has ever injected a failure while traffic was flowing.**

`accept.sh`'s simulator injects failures, but into an *idle* tenant, and it tests
whether an agent is stuck — not whether envelopes survive.

⚠ **Nothing has ever checked for duplicates.** `fabric-bench` counts `opened`
events and compares to a total. Two deliveries of the same envelope and one loss
would net to the right number and pass.

## 2. The claim to prove

**h-flock is at-most-once with zero retries.** Stated precisely, that is two
separate promises, and only one of them is absolute:

| | promise | strength |
|---|---|---|
| **no duplicates** | an envelope is delivered **at most once**, ever | ⚠ **absolute — a single duplicate is a defect** |
| **loss** | an envelope may be lost | **permitted**, but must be **countable and attributable** to a specific injected failure |

⚠ **Do not "fix" a loss you injected.** Loss is allowed by the design. An
unexplained loss with no injected cause, or **any duplicate at all**, is the
finding.

## 3. The harness — `container/scenarios/conservation.sh`

**Every envelope carries a unique sequence number in its payload.** That is what
makes reconciliation possible and it is the whole trick.

1. **Scale** — 100 stations × 100 rounds = **10,000 envelopes** (~26 min at the
   current 6.4/s). ⚠ Not more: throughput bounds this, and a run nobody waits
   for is a run nobody repeats.
2. **Inject, while traffic flows** — at intervals, and **log exactly when**:
   - kill the switch process
   - kill a port mid-delivery
   - ⚠ **these two matter most**: the switch pops from egress and then pushes to
     ingress, and a port pops from ingress and then delivers. **Dying in that
     window is precisely where at-most-once is decided.**
3. **Reconcile at the end**, per sequence number:
   - delivered **exactly once** → good
   - delivered **more than once** → ⚠ **DEFECT, absolute**
   - not delivered and in a dead queue → accounted for
   - not delivered and not dead → **lost**; must line up with an injection window
4. **Sample over time** — Redis `used_memory`, queue depths, RSS, throughput per
   minute. A stream that grows to its cap and stops is correct; the *shape* is
   what a human reads.

## 4. ⚠ Negative controls — two, per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1

A reconciliation that has only ever balanced proves nothing.

1. **Inject a duplicate on purpose** — deliver one envelope twice — and prove the
   harness reports a duplicate.
2. **Drop one on purpose** — remove an envelope from a queue mid-flight — and
   prove the harness reports it lost and unaccounted.

⚠ **If either passes silently, the harness is worthless and that is the build's
result.** Report it as such rather than continuing.

## 5. Done when

- the harness exists, and both negative controls in §4 are demonstrated
- a clean 10,000-envelope run with **zero duplicates**, and every loss attributed
  to an injection window
- the growth samples are in the report, as numbers over time
- `python3 -m pytest -q` green (356 at the time of writing)
- ⚠ one h-flock tenant at a time, output to a **lab-local file**

## 6. What this is NOT

Not a benchmark — throughput is incidental here. Not a soak; hours come later if
this passes. **Not an attempt to make h-flock lossless.** If the honest result is
"envelopes are lost when the switch dies mid-forward, here is the count and the
window", that is a **successful build** and exactly what I want to know before
anyone builds anything else on top of it.

## 7. Reporting

`jira done`, then message `architect` with: the duplicate count (expect zero),
the loss count with its attribution, both negative-control proofs, the growth
samples, and anything the reconciliation could not explain.
