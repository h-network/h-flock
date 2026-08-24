# Build 115 — verify the packet-switching harness against its own spec

**Lane: `acceptance`. Base: `bus/build-114-packet-switching-harness` at
`f977869`** — ⚠ **not `main`.** The branch is not merged; that is what this
verification decides. ⚠ **Check out that exact commit** and name it in your
signoff; if the branch has moved past it, say so rather than testing the newer
head silently.

⚠ **Host: the lab.** `BUILD-CONVENTION` §3.0 — this is **correctness**, not
performance. Throughput on the lab is wrong by two orders of magnitude and looks
plausible. **Do not quote a rate.** h-oracle's numbers are already recorded and
are not yours to re-derive.

## What you are verifying, and against what

`docs/BUILD-114-packet-switching-harness.md` is the spec; `BUILD-114-results.md`
is `bus`'s account of meeting it. ⚠ **Verify against the SPEC, and treat the
results doc as a claim to check rather than a description to confirm.**

## The four checks

**1 — steady mode is clean.** Small run, your own tenant and project. `rc0`, no
losses, no duplicates, no strays.

**2 — ⚠ the three REDs, re-demonstrated by you.** The results doc reports `rc1`
for a removed `opened`, `rc2` for a duplicate, `rc3` for a stray.
⚠ **Reproduce all three yourself.** A gate that has not been *seen* to fail by
someone other than its author is not verified — `BUILD-CONVENTION` §1.

**3 — the failure capture actually fires.** On a non-zero run, confirm all six
`diagnostic-*` files are produced **before teardown**, the `sha256` manifest
covers them, and `PACKET_DIAGNOSTICS status=complete` is printed. ⚠ **Confirm
`rc0` skips the whole set** — retention on green is cost we do not want.

**4 — ⚠⚠ THE CHECK THAT MATTERS MOST, because it is the one that guards the
others.** Break a capture deliberately and confirm the harness **notices**.
Make one expected artifact empty, and separately make one contain a Python
traceback **at the END after valid content** — not at the top. **Both must report
`status=incomplete`.**

⚠ **That second case is the whole point.** A partial capture writes good lines
first and fails last, so a first-line-only check passes it and the evidence is
silently truncated at exactly the point it got interesting. **An evidence path
that can quietly produce nothing is what this build exists to prevent.**

## Out of scope — read this twice

⚠⚠ **DO NOT run the 100 × 2 burst.** It has an unexplained five-envelope loss and
reproducing it is **the operator's call, not ours**. Your job is the harness, not
the fabric's open question.

⚠ **Do not wire it into `accept.sh`.** Separate decision, separate build.
⚠ **Do not fix anything you find** — report it. You are the verifier.

## Done means

Pushed. `TEST-SIGNOFF` naming the **branch head you tested** and the host.
⚠ **If a check fails, say so plainly and stop** — a verification that reports
green because three of four passed is worse than no verification.
