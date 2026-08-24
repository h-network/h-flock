# Build 114 — script 1: packet switching, conservation only

**Lane: `bus`. Base: `main` at `97e99dc`.** Register: `TEST-HARNESS.md` §1.

⚠ **First of several. The operator names each one** — do not generalise this into
a framework for the others, and do not build for a second script that has not
been specified.

## What it is

`bench-send` → bus → `bench-port`, judged by `reconcile-unicast`. **All three
already exist and you wrote two of them.** This build makes them **one runnable,
repeatable thing that can fail.**

⚠⚠ **The whole point is the last clause.** We already have scripts that record
and do not judge — `accept.sh` invokes **none** of the 32 scenarios, including
all six reconcilers. **A harness that produces numbers and cannot go red is what
we are trying to stop having.**

## Pure packet switching — no content inspection

⚠ **Do not read payloads and do not teach `bench-port` to stop discarding.** That
is a different script and a later one. **This counts envelopes, not bytes.**

**It must fail on:** an envelope lost · an envelope duplicated · a stray envelope
nobody sent · a stage count that does not conserve · an unresolved
`forward_unknown` left unclassified.

**It must report, per run:** envelopes submitted · each custody stage's count ·
duplicates · losses · indeterminate · throughput at the boundary you name.

## ⚠ Name the boundary, and say what is outside it

Build 111 measured `popped → forwarded` and the README read it as delivery.
**State in the output where the clock starts and stops**, and state plainly that
this covers **no port, no terminal and no application** — the very failure modes
build 113 found live. ⚠ **A reader who mistakes this for a delivery test draws
exactly the wrong conclusion**, and that has already happened once.

## Modes

**Steady** — a submission rate you can hold, throughput at the named boundary.

⚠ **Burst — and this has never been done at this layer.** Every burst result we
have came through tmux. Queue N envelopes to a destination whose receiver is not
running, then start it and let it drain back to back. **If the fabric loses or
duplicates under burst, that is a far more serious finding than any throughput
number**, and nothing has ever looked.

## Exit codes — a decision, not a detail

⚠ Acceptance means `1+` failed, `100` ran-but-incomplete, `0` clean.
`conservation.sh` exits **5** for `INDETERMINATE_FORWARD`. **Say what this script
returns for each outcome and how it composes with a caller** — an indeterminate
forward is neither a pass nor a loss, and collapsing it into either is the defect
build 92 was refused for.

## Out of scope

⚠ **Do not wire it into `accept.sh`.** That is its own decision with its own
argument about what a non-zero reconcile does to an acceptance verdict.
**Getting the script right comes first; wiring it is a separate build** — but
⚠ **record in `TEST-HARNESS.md` that it is NOT wired**, because that column is
the one that matters.

## Done means

Pushed. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Demonstrate it going red** —
inject a loss, a duplicate and a stray, and show a distinct non-zero outcome for
each. Per `BUILD-CONVENTION` §1, a gate that has not been shown to fail is not a
gate.
