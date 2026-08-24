# Build 111 — measure the three layers the README conflates

**Lane: `bus`. Base: `main` at `9c3d741`.**
⚠ **Host: `h-oracle` — PERFORMANCE ONLY.** `BUILD-CONVENTION` §3.0: the lab reads
**6.5/s** where h-oracle reads **853/s** on identical scripts. **A throughput
figure from the lab is wrong by two orders of magnitude and looks plausible.**

⚠⚠ **Do not touch `h-flock-office` or `h-flock-demo` on that host.** The office
runs in one of those containers. Name your own tenant and project, one per run.

## Why this exists

`README.md:314-316` states three numbers as one measured profile:

> *100 envelopes at 10/s with none lost … ~500 ms per delivery of which startup
> is the larger half.*

⚠ **They are three different layers, and one of them is a constant we chose.**
`src/flock/tmux/ops.py:15` sets `ENTER_DELAY = 0.5` and `:464` sleeps it between
paste and Enter. **"~500 ms per delivery" is very close to our own sleep**, and
the README attributes it to *startup*.

## The three numbers, measured separately

**1. Switch only — the fabric's real speed.** `sent → popped → forwarded`, no
tmux, no paste. This is what "the speed of the switch" means and no port
behaviour belongs in it.

**2. End-to-end delivery at the default `PASTE_ENTER_DELAY=0.5`.** What an
operator actually experiences.

**3. End-to-end delivery at `PASTE_ENTER_DELAY=0`.** ⚠ **The point is the
DIFFERENCE between 2 and 3**, which is what the delay costs — not number 3 on its
own.

## ⚠⚠ The trap, and it is the whole risk of this build

**`ENTER_DELAY` exists because without it Enter gets swallowed.**
`docs/LLD-port-tmux.md:197-208`: the Enter is coalesced into the paste, *"the
message sits unsubmitted, and the agent looks idle."* 0.5 s is the margin chosen
across Claude Code's Ink, codex and agy.

⚠ **So measurement 3 will be fast, and some of those deliveries may never have
been submitted.** **A fast number for a broken path is worse than no number.**

**Every delivery must be VERIFIED ARRIVED, not merely timed.** Confirm the text
actually reached the pane — a marker per envelope, counted at the destination.
**Report the arrival rate beside the latency for every configuration**, and if
`delay=0` loses submissions, **that is the headline result**, not a footnote.

## Method

Per `BUILD-CONVENTION` §3.0: **medians, not means** · **interleave the
configurations per iteration** rather than running them in blocks · **same
container, same run, same method** · **redirect to a host-local file** · ⚠
**`docker exec` output does not reach `docker logs`**, and a control must travel
the same path as the thing it controls for.

Record `free -h`, `df -h /`, the host, and the base image digest.

## What this build does NOT do

⚠ **Do not change `ENTER_DELAY`, and do not propose changing it.** It is the
mitigation for a documented silent failure. **This build measures its cost so the
README can state it honestly** — the tradeoff is deliberate and stays.

⚠ **Do not edit `README.md`.** The correction is the next build and it needs
these numbers first.

## Done means

Pushed. `TEST-SIGNOFF` with the host and digest named. ⚠ **Evidence at an
immutable path, bound to the tenant the accepted run created, and fail the run if
a capture is empty or missing what you quote.** ⚠ **Verifier assigned by me.**
