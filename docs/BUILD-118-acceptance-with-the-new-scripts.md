# Build 118 — an acceptance round with the new test scripts in it

**Lane: `acceptance`. Base: `main` at `e4fb3f1`.**
⚠ **Host: the lab.** Correctness. **Do not quote a throughput rate** — that is
h-oracle's job and those numbers already exist.

⚠⚠ **This is a RUN, not a change.** Nothing in this build modifies a script.

## What to run, in this order, against ONE tenant

**1 — the existing gate, unmodified.**

```
bash container/accept.sh --tenant <yours> --keep …
```

⚠ **`--keep` matters** — it leaves the tenant up so step 2 runs against the same
live container. Take the ports and tenant naming from the script's own arguments.

**2 — the packet harness against that same container**, both modes:

```
bash container/scenarios/packet-switching.sh --mode steady --count … --rounds …
bash container/scenarios/packet-switching.sh --mode burst  --count 100 --rounds 2
```

⚠ **Use the burst recipe `BUILD-117` used (100 × 2)** so the result is comparable
to three known-clean runs. Do not invent a new size.

## ⚠⚠ Report the two verdicts SEPARATELY — do not collapse them

**This is the whole discipline of this build.** `accept.sh` returns its verdict;
the harness returns `0`, `1`, `2`, `3`, `5` or `100`. ⚠ **Report both, side by
side, and do NOT combine them into a single pass/fail.**

**Combining them is the wiring decision, and it has not been made.** It turns on
what a `100` (ran-but-incomplete) or a `5` (`INDETERMINATE_FORWARD`) should do to
an acceptance verdict, and that argument needs these numbers first.

⚠ **But do answer the question this run exists to inform:** state plainly **what a
combined gate WOULD have returned** on this round, and what it would have returned
had the harness come back `100` or `5`. **That sentence is the deliverable** — it
is the input to the wiring decision, not the decision itself.

## ⚠ What is genuinely new here

**These two have never run in the same round.** `accept.sh` stands up a real
tenant with the API door open, a console, and a real `setup.sh` install; the
harness then bursts 200 envelopes through it. **New combinations find new
things** — if something breaks that neither found alone, that is the most
valuable result available today.

⚠ **Build 116 changed how three `api-*` scenarios obtain their token.** If
`accept.sh` reaches any of them, that path is now exercised in a real round for
the first time. Say whether it did.

## Out of scope

⚠ **Do not modify `accept.sh` or `packet-switching.sh`.** ⚠ **Do not wire one into
the other.** ⚠ **Do not fix what you find** — report it.

## ⚠ Before pushing evidence

**Scan it for secrets.** `docker inspect` redacts on a documented denylist that is
incomplete by design, and `diagnostic-processes.txt` is `ps -ef` with **argv**.
⚠ **h-flock is PUBLIC and this harness captured a live token once already.** Grep
for long hex and secret-shaped assignments, and say in the report that you did.

## Done means

Pushed. `TEST-SIGNOFF` naming the host and image digest, both verdicts stated
separately, and the would-have-returned sentence.
