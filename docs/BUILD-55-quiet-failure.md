# Build 55 — the harness reports failure and exits 0

> **Base on `main`.** Branch `bus/build-55-quiet-failure`, push to origin.
> Owner: `bus`. ⚠ **Do this BEFORE resuming build 53.**

## 1. The defect

`plumbing-check` prints `FAIL=1` and **exits 0**. `accept.sh` reads the exit
code, prints `passed`, and exits 0. **A failing acceptance run reports success.**

Found by `bus` during build 53, when a genuine failure — the plumbing fixtures
still asserting the v1 flat wire — was reported as a pass.

## 2. ⚠ Why this is split out of build 53 and goes first

**We do not currently know whether `main` is green.** Every gate today —
builds 47, 48, 50, 51 — was stated as "accept.sh green, PASS=25 FAIL=0". Those
numbers were read out of the printed summary by a human, which is why they were
trustworthy. The **exit code** was never evidence and we did not know it.

⚠ **Fixing this inside build 53 would mean build 53's evidence was produced by a
harness repaired in the same commit.** The pass criteria and the thing being
tested cannot change together.

⚠ **This is the fourth green-signal-that-wasn't today**, and they share a
shape: torn log lines read as complete custody; 345 tests passing on aliases
that hid a half-done rename; web client tests passing against a mock of the old
wire; and now a harness exiting 0 on failure. **In every case the signal was
produced by something other than the thing under test.**

## 3. What to do

1. `plumbing-check` exits **non-zero when `fail > 0`**. Same for `sim-blocked`
   and anything else `accept.sh` shells out to.
2. `accept.sh` fails when any stage fails, and its final line says which.
3. ⚠ **Audit the other scenario scripts** — `container/scenarios/*.sh` — for the
   same pattern. A script that counts failures and returns 0 is the bug; find
   every one.
4. ⚠ **Then run it on unmodified `main` and report what it says.** That is the
   real deliverable: it tells us whether anything has been failing quietly while
   we merged five builds today.

## 4. Done when

- a deliberately failing check makes `accept.sh` exit non-zero — **prove it**,
  by breaking one on purpose and showing the exit code
- `main` runs clean, or the failures it exposes are reported and **not fixed in
  this build**
- `python3 -m pytest -q` green (350 on `main` at the time of writing)
- ⚠ one h-flock tenant at a time on the lab, output to a **lab-local file**

## 5. Reporting

`jira done`, then message `architect` with the commit, the proof that a failure
now exits non-zero, how many scripts had the pattern, and — most importantly —
**what unmodified `main` reports once the harness is honest.**
