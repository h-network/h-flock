# Build 100 — make the failure shapes reachable

**Lane: `bus`. Base: `main` at `6c29b63`.** Branch from main, push to origin.

⚠ **This is the largest thing on the board, and it exists because of a number
you helped produce.** Across every acceptance run to date: `_incomplete`,
`_failed` and `_partially_failed` are at **ZERO occurrences, for all four control
kinds.** Six builds and eleven refusals argued those records into shape and
**nothing has ever produced one outside a unit test.**

They cannot be reached by running the system harder. They need a Redis write to
lose its reply, or `Popen` to fail.

## What this build is for

**Not** to prove the records are correct — the unit tests do that. It is to make
the *live* path reachable, so a real tenant can produce a real
`forward_unknown`, a real `_partially_failed`, and we find out whether the six
custody stages, the conservation check and `office status` behave as designed
when they meet one.

⚠ **Everything downstream of those records is also unexercised.** Build 92 taught
conservation to carry an indeterminate forward; **no live run has ever given it
one.**

## ⚠ The design constraint that matters more than the mechanism

**A fault-injection facility that can be enabled by accident is worse than the
gap it closes.** Argue your mechanism, but it must satisfy:

1. **Impossible to enable without meaning it.** Not a stray env var that a
   copied `.env` could carry.
2. **Loudly visible while active** — a tenant injecting faults must say so
   everywhere it reports, or someone will debug a synthetic failure for an hour.
3. **Inert in the shipped path.** ⚠ If the production code has to *check*
   whether injection is on, that check is on every write forever. **Prefer a
   mechanism that does not exist unless deliberately assembled** — a wrapper
   supplied at construction, a test-only client, a proxy in front of Redis.
4. **Refuses to arm against a tenant it did not create.**

**Argue the mechanism you choose against those four.** I am not specifying it;
you own the bus and the switch, and my record on specifying contracts here is
four-refusals-out-of-five.

## Scope

⚠ **Reaching ONE shape live is a complete build.** Do not attempt all of them.
A single real `forward_unknown` on a live tenant, with the conservation check
meeting it and reporting `INDETERMINATE_FORWARD`, closes more than the rest
combined — it is the path with the duplicate-delivery consequence.

**Say in your results which shapes remain unreachable** and what each would need.
`acceptance` has kept that list honest across four runs; keep it that way.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, **verifier assigned by me**. ⚠ **Behavioural
claims need executing controls** — your own narrowing. ⚠ **Author names the
commit measured at; verifier re-measures at the tip.**
