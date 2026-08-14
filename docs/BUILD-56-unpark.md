# Build 56 — unpark the vocabulary and land it on `main`

> **Base on `main`.** Regenerate `rename/vocabulary` from current `main`, verify,
> push. ⚠ **`architect` merges** — do not merge it yourself.
> Owner: `api`.

## 1. Why now

The parking condition was *"until the new frame works"*. Build 53 landed the
frame: qualified addressing accepted, the adapter resolving, the switch reading
L2 only. **The gate is met.**

⚠ **And the operator's reason is the better one: everyone understands the new
vocabulary today.** In a month it is archaeology, and the branch has to track a
moving `main` the whole time — it is already **15 commits behind**.

⚠ **`main` is currently incoherent and that is the strongest argument.** Build 53
named the frame's fields `l2.source` / `l2.destination` — the *new* vocabulary —
while the code around them still says `producer` (70 occurrences) and
`recipient` (63). The wire speaks one language and the code speaks another.

## 2. What to do

1. **Regenerate** from current `main` — do not rebase, re-run the codemod
2. **Verify byte-identity** by regenerating twice and diffing
3. **Full lab verification** — §3
4. **Push. Do not merge.** Report, and `architect` merges

## 3. Verification — this is the largest change the project has made

- `python3 -m pytest -q` green (**356** on `main` at the time of writing)
- `container/accept.sh` green — ⚠ **and it means something now**: build 55 made a
  failing check exit non-zero, so this is the first rename verified by a harness
  that can actually fail
- `container/scenarios/fabric-bench.sh` at `STATIONS=100 ROUNDS=20`:
  **2,000 of 2,000, zero dead letters, ≥ 6/s**
- ⚠ **one h-flock tenant at a time**, output to a **lab-local file**

**⚠ Negative control, per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1.** The
cheapest proof for a rename: after regenerating, put one old name back by hand
in a place the code depends on — `flock.port` in the switch's `Popen`, say — and
show a test or `accept.sh` go red. **A rename that has only ever passed is not
known to have been checked.**

## 4. ⚠ What this breaks, and it must be stated not implied

**Tier C changes Redis key resources and environment variables**
(`vab` → `port_type`, `endpoint` → `provider`, `ENDPOINT_*` → `PROVIDER_*`).
**A tenant running across this change breaks.** There is no dual-read.

**Say plainly in the report that a fresh tenant is required**, and confirm
`setup.sh` produces a working tenant from scratch on the new vocabulary — that
is the actual upgrade path and it must be shown to work, not assumed.

## 5. After the merge

- the codemod has done its job; it stays in `tools/` for one release as the
  record of the transition, then goes
- `rename/vocabulary` is deleted
- ⚠ **the exclusion list in the codemod becomes dead weight** — the vocabulary
  docs no longer need protecting once there is only one vocabulary. Do not
  delete it in this build; note it in the report.

## 6. Reporting

`jira done`, then message `architect` with: the regeneration counts, the
negative-control proof, the lab evidence, and the fresh-tenant confirmation.
