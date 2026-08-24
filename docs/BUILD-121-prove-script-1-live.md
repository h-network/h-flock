# Build 121 — prove script 1 actually works, live, on current `main`

**Lane: `acceptance`. Base: `main` at `228cee0`.** ⚠ **Host: the lab.**
**Do not quote a throughput rate.**

## Why this exists

⚠⚠ **Script 1 has had four live outings and TWO of them produced false reds** — a
phantom five-envelope loss (build 114, judged before the queues drained) and a
stray that was really `accept.sh`'s own traffic (build 118). A third defect made
it report `status=incomplete` on **every** non-zero run.

**All three are fixed. None of the fixes has had a live run.** Build 119's scoping
was proven by controls, and the `NO_NONEMPTY_QUEUES` marker reached `main` only
just now, on its own, because the branch it was written on has been halted.

⚠ **So the current state of script 1 is: believed working, never demonstrated.**
This build closes that and nothing else.

## The four checks

**1 — clean run is clean.** Steady and burst (100 × 2) on an otherwise idle
tenant. **Both `rc0`.**

**2 — ⚠⚠ THE ONE THAT MATTERS: it survives OTHER TRAFFIC.** Run it against a
tenant that is **also carrying real `accept.sh` traffic** — the exact build 118
scenario that produced the false stray. **It must return `rc0`, and
`PACKET_SCOPE … ignored_out_of_scope` must be NON-ZERO.**

⚠ **A zero there means the scoping was never exercised and the check proved
nothing.** Report the number.

**3 — the gate still fires inside its own scope.** Inject a loss, a duplicate and
a stray **among `bench-*` participants**. ⚠ **Still `rc1`, `rc2`, `rc3`.**
**Scoping must not have removed the gate** — that is the risk of every narrowing
fix and it is why this check is here.

**4 — a non-zero run reports `status=complete`.** On any red from check 3,
confirm `PACKET_DIAGNOSTICS status=complete` and that
`diagnostic-queues.tsv` carries the `NO_NONEMPTY_QUEUES` marker rather than being
empty. ⚠ **That is the fix that reached `main` thirty minutes ago and has never
run.**

## Out of scope

⚠ **Do not touch script 2 or the `bus/build-120-script-2` branch** — that work is
halted by the operator. ⚠ **Do not wire anything into `accept.sh`.** ⚠ **Do not
fix what you find — report it.**

## Done means

Pushed. `TEST-SIGNOFF` naming host and image digest. ⚠ **State plainly, in one
sentence, whether script 1 is trustworthy** — that sentence is the deliverable.
⚠ **Scan evidence for secrets before pushing.**
