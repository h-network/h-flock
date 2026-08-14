# Build 54 — tags at the port, and the benchmark that tests the architecture

> **Not yet filed.** Follows build 53. Recorded now so build 53 is not scoped
> against a moving target.

## 0. ⚠ Measured priors — read before you assume the answer

I ran a standalone model of this decision against a real Redis
(`container/scenarios/policy-bench.py`). **It contradicts the design's stated
reasoning, and it contradicts my own prediction.**

| | µs per decision |
|---|---|
| policy read from Redis (what a **one-shot port** must do) | **28–46** |
| the same check from an **in-memory table** (what a long-lived **switch** can do) | **0.2** |
| switch: forwarding lookup only | 13.6 |
| switch: forwarding + policy **from memory** | **15.0** — a 10% cost |
| switch: forwarding + policy **from Redis** | 48.2 — a 254% cost |

⚠ **Roster size does not matter** — 30.6 / 28.3 / 29.5 µs at rosters of
10 / 100 / 1000. Cost tracks tag-set size, not participant count. That is the
O(1) property tags were chosen for, and it means the "pair ACLs are n²"
argument is about the **data model**, not about placement.

⚠ **The switch can cache; the port cannot.** The switch is long-lived, the port
is a one-shot process. That asymmetry runs **opposite** to `DESIGN-layers` §2.1,
which argues policy belongs at the port because the switch is serialized. On
cost, the switch wins by ~150×.

**So the performance argument for port-side placement does not survive.** Two
non-performance arguments do, and they are why this build still puts it at the
port:

1. **The error lands at the sender** — a port-side refusal is a real error in
   the agent's terminal; a switch-side refusal dead-letters
2. **No cache invalidation** — the port reads current tags every send; a cached
   switch table must be invalidated on every tag change

⚠ **Do not "fix" the numbers to agree with the design.** If the in-system
benchmark reproduces the standalone one, `DESIGN-layers` §2.1 gets rewritten to
say policy sits at the port for **feedback and freshness, not cost**. That is
the expected outcome.

## 1. Why this one carries the real benchmark

The whole layer design rests on an argument we have **asserted and never
measured**:

> long policy belongs at the port because ports are per-send and parallel; the
> switch must stay tiny because it is shared and serialized.

That is plausible, it is what hardware does, and it is **not evidence**. Build 54
implements the same policy check in both places and measures the divergence.
⚠ If port-side placement does not win as participants grow, the layer split
needs revisiting — and I would rather find that out from a graph than from
production.

## 2. What gets built

- **tags in a companion key per participant**, not in the roster hash
  (`DESIGN-layers` §3) — keeps hot forwarding data separate from policy data
- **`export[]` / `import[]`**, with "may `a` reach `b`?" as a set intersection
- **permit when absent** within a tenant (§7.5) — a switchport permits
- **the filter runs BEFORE assembly** (§2.5), and a refusal **emits a record**
  with source, destination and reason

## 3. The benchmark that matters

Same policy decision, two placements, rosters of **10 / 100 / 1000**, tag sets
of **1 / 5 / 20** per participant:

| placement | what is measured |
|---|---|
| **at the port** | per-send cost, paid by the sender, **N in parallel** |
| **at the switch** | per-envelope cost, paid once, **serialized through one process** |

Report both as **µs per decision** and as **achievable envelopes/second**, and
plot the second against roster size. ⚠ The port column will show a *higher total*
cost — N ports each doing a lookup is more work than one switch doing it once.
**That is expected and it is not the question.** The question is which curve
bends as N grows.

⚠ **Also measure the deny path.** Filter-before-assembly claims a refusal is
cheap because no frame is built. Verify it rather than trusting the argument.

## 4. Open, for the operator

Whether tags are also checked at the switch as a backstop. `DESIGN-layers` §2.3
says neither is a security control inside the container, so a backstop buys
defence against a buggy port and nothing else — at a permanent cost in the one
component that cannot be parallelised. **My inclination is no backstop**, but it
is a real trade and it is not mine to settle alone.

## 5. ⚠ Gates must be shown to fail

See [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1. Specifically: seed a
participant whose export tags do NOT meet the destination's import tags, and
prove the send is refused **and that the refusal emits a record**. A policy
engine that has only ever permitted is not known to deny.
