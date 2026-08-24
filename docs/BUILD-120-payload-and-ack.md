# Build 120 — script 2: does the payload survive, and can the receiver say so?

**Lane: `bus`. Base: `main` at `34e1b5e`.** Register: `TEST-HARNESS.md` §2.

⚠ **Script 1 is the precondition and it is met** — envelope conservation is now
independently proven, so a content failure here is unambiguously about content.

## What it is

**Origin sends a payload carrying a unique marker and a checksum. The destination
verifies the content it received and ACKS BACK OVER THE BUS. The origin verifies
the ack.** One adapter, two roles, a round trip.

⚠⚠ **Why the ack is the point and not a convenience.** Six custody stages end at
the port's handoff; nothing below it is recorded, and **that is deliberate** — a
switch that forwards by name and never reads content cannot know whether the
destination consumed anything. Build 113 measured the consequence: **four messages
`opened` and never received.**

**A test adapter closes that gap without violating the design, because the adapter
is an APPLICATION.** The fabric still never inspects content; **the receiver
testifies for itself.** ⚠ **That is the only honest way to get end-to-end receipt
in this architecture.**

## ⚠⚠ The ambiguity you must resolve, or the script is worth little

**If nothing comes back, two very different things could have happened:** the
payload never arrived, or it arrived and the ack did not come back.

⚠ **The custody records disambiguate, so use them:**

| outbound `opened` at destination | ack `sent` at destination | verdict |
|---|---|---|
| yes | no | **payload landed, receiver failed to ack** |
| no | no | **payload never landed** |
| yes | yes, but origin never received | **the ack leg lost it** |

**Report which of the three it was.** ⚠ **Collapsing them into "failed" is the
defect build 92 was refused for** — an indeterminate result is neither a pass nor
a loss.

## What must make it go RED

**Corruption · truncation · coalescing · reordering · a missing ack · an ack for
something never sent.** ⚠ **Distinct non-zero codes**, and demonstrate each per
`BUILD-CONVENTION` §1. **A gate not shown to fail is not a gate.**

## ⚠⚠ Carry in what today cost us — all four are requirements, not advice

**1 — Scope your universe.** ⚠ **Use a distinct participant prefix, NOT
`bench-`** — script 1 uses that, and the two must be able to run on the same
tenant without judging each other. **Print the scope and the ignored count.**
`BUILD-119` exists because a judge counted traffic that was never its own.

**2 — Drain before judging.** ⚠ **`sent` with no `popped` is the IN-FLIGHT
signature, not a loss signature.** Build 114 spent a day on that. Poll to zero,
and return `100` rather than judging if it does not drain.

**3 — Retain on non-zero, discard on green.** ⚠ **Capture enough to DIAGNOSE, not
merely to judge, and capture it BEFORE teardown.** A red run that destroys its own
evidence has cost more than it returned.

**4 — Redact at capture.** ⚠ **`docker inspect` dumps `Config.Env` and h-flock is
PUBLIC.** Script 1 already has the transform — reuse it, do not re-derive it, and
remember `ps -ef` carries **argv** which the denylist does not cover.

## Boundaries — say them in the output

**Covers:** content integrity end to end, **and receipt itself** rather than
handoff. **Also yields** round-trip latency and both directions under load, which
is what a real conversation between agents looks like.

⚠ **Does NOT cover the tmux port or any CLI.** The receiver is `bench-port`-shaped
— **no terminal, no input box.** ⚠ **A reader who mistakes this for a delivery
test draws the wrong conclusion, and that has already happened once** (build 111
measured a switch and was read as measuring delivery).

## Out of scope

⚠ **Do not wire it into `accept.sh`.** That is the NEXT build and it covers both
scripts at once. ⚠ **Do not change the fabric.** ⚠ **Do not re-run acceptance.**

## Done means

Pushed. `TEST-SIGNOFF`. ⚠ **Every red demonstrated**, the three-way ambiguity
resolved and reported, and **evidence scanned for secrets before pushing.**
