# Build 96 — the unicast conservation claim has no control

**Lane: `bus`. Base: `main` at `21c78db`.** Branch from main, push to origin.

⚠ **You found this in your own merged build, in the alignment round.** That is
worth recording: build 92's first submission was refused because the broadcast
reconciliation folded an ambiguous forward into known loss, and you then found
**the same uncontrolled-claim defect left on the unicast path.**

## The gap

`container/scenarios/conservation.sh:297` carries the indeterminate branch and
`container/scenarios/conservation.sh:316` prints `INDETERMINATE_FORWARD`. But
`tests/test_conservation_contract.py` executes only `analyse-run.py` and
`reconcile-broadcast.py` — **a different analyser, and the broadcast path.**

**No committed test drives the unicast heredoc.** The code reads correctly and
the claim is uncontrolled, which is precisely what got the first submission
refused.

## The fix, as you proposed it

Extract the unicast reconciler so it is executable, drive a synthetic
`forward_unknown` through it, and assert `rc5`, `lost=0`, `indeterminate=1`.

⚠ **Then mutate it**: removing the indeterminate branch must produce `LOSS` and
`rc1`. **A control that cannot go red is not a control** — that is the rule you
narrowed this afternoon, applied to your own work.

⚠ **`BUILD-92-results` line 10 makes a general conservation claim.** Either its
scope becomes accurate or the control makes it true. **Say which you did.**

## ⚠ Watch for the extraction changing behaviour

`reconcile-broadcast.py` was extracted from a heredoc and that went cleanly. This
one runs inside `conservation.sh` with its own surrounding state. **If extraction
changes what the unicast path sees, you have altered the thing you are trying to
control.** Prove the extracted reconciler and the in-script path agree before
trusting either.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, **verifier assigned by me**. ⚠ **This is a
behavioural claim** — reconciliation runtime behaviour — so source inspection
cannot control it, by your own narrowing. ⚠ **Author names the commit measured
at; verifier re-measures at the tip.**
