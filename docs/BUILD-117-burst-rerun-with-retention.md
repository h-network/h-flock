# Build 117 — reproduce the burst loss, with the evidence kept this time

**Lane: `bus`. Base: `main` at `14c86e1`.** The harness is merged; this is a
**run**, not a change.

## ⚠⚠ Read this first: you are not diagnosing, you are capturing

Build 114's burst lost **five envelopes in 200**, all carrying only a `sent`
record. **Five hypotheses have died** — tail truncation, static watch list,
socket framing, TTL/eviction, and a second switch instance. The diagnosis stopped
because **teardown destroyed the artifacts**, not because we ran out of ideas.

⚠ **So do not theorise in this build and do not change the fabric.** Reproduce,
retain, report. **The diagnostic bundle is the deliverable** — analysis is the
next build, with the evidence in hand.

## ⚠ Name the host, because build 114 did not

`BUILD-114-results.md` records **no host**, so that run is not reproducible from
its own record. That is a `BUILD-CONVENTION` §3.0 miss and it is the reason this
build has to ask you rather than read it.

⚠⚠ **Run on the SAME host build 114's burst ran on, and name it explicitly this
time** — host, base image digest, `free -h`, `df -h /`. **Changing the host
changes the experiment**; a loss that is load- or timing-dependent may not
survive a move, and we would learn nothing from a clean run on different iron.

## The run

**Same recipe: 100 destinations × 2 rounds, burst mode.** Fresh tenant and
project per attempt, as before.

⚠ **Up to three attempts. Stop at the first reproduction** — the goal is one
fully-captured failure, not a failure rate.

**The retention is already automatic**: non-zero retains the diagnostic set
before teardown, `rc0` skips it, and `rc100` now retains too. **Confirm
`PACKET_DIAGNOSTICS status=complete` on any non-zero run** — if it says
`incomplete`, say so loudly, because that is the capture failing at the one
moment it matters.

## What to report

**If it reproduces:** the count lost, their stream_ids, their source queues, and
⚠ **the full diagnostic bundle pushed** — that is the point of the build.

⚠ **If three attempts come back clean, that is a REAL RESULT, not a failed run.**
It would mean the loss is intermittent, which is itself a finding and changes what
the next step should be. **Report it as a result and do not keep running until it
fails** — that is fishing, and it burns the host.

## ⚠ Before you push the evidence

**Scan it for secrets.** `docker inspect` now redacts env values on a documented
denylist, but the denylist is incomplete by design and `diagnostic-processes.txt`
is `ps -ef`, which carries **argv**. ⚠ **h-flock is PUBLIC and we nearly committed
a live token from this exact harness two hours ago.** Grep for long hex strings
and secret-shaped assignments before pushing, and say in your report that you did.

## Out of scope

⚠ **Do not fix anything you find.** ⚠ **Do not wire the harness into
`accept.sh`.** ⚠ **Do not touch `h-flock-office` or `h-flock-demo`** if you are on
h-oracle — the office runs in one of those.

## Done means

Pushed, with the host and digest named, and `TEST-SIGNOFF`.
