# Build 59 — the lifecycle gate races, and a longer wait may be the wrong fix

> **Base on `main`.** Branch `bus/build-59-flaky-gate`, push to origin.
> Owner: `bus` (found it). ⚠ Touches `container/`, which `tmux` owns — told.
> **Do this before resuming build 54.**

## 1. The symptom

`accept.sh` lifecycle check: **fixed `sleep 5`**, then asserts `dave`'s window
exists — got 0. Container evidence shows `tmuxhost` logged
`window_created destination=dave` at 11:40:12, and the harness's own `StopAgent`
then removed it. The `StopAgent` side of the same check **already polls up to
15 s**; the `StartAgent` side does not.

## 2. ⚠ Establish the cause BEFORE extending the wait

**A longer timeout is how a real slowdown gets buried.** Build 54 adds a policy
lookup to the send path. If `StartAgent` got slower and tipped a marginal
5-second sleep, the poll is treating the symptom.

**Answer this first, with timestamps:**

1. When did the check sample, and when did `window_created` land? If the check
   sampled **before** 11:40:12, it was simply too early → a poll is correct.
2. **Is `StartAgent`-to-`window_created` slower under build 54 than on `main`?**
   Measure it on both, same container, same method, medians. ⚠ If it is slower,
   say so — the poll still goes in, but we would know 54 has a cost nobody
   costed.

⚠ **Report the number either way.** "It was a race" and "it was a race *and* 54
made it 40% slower" are different findings and only one of them is finished.

## 3. The fix

Poll up to 15 s on the `StartAgent` side, matching the `StopAgent` side that
already does. **Symmetry is the argument** — one half of the same check polling
and the other sleeping is the defect, independent of timing.

⚠ **Audit the rest of `container/` for fixed sleeps used as gates.** Build 55
found exactly one script counting failures and returning 0; this is the same
question asked of waits. A `sleep` followed by an assertion is a gate that
passes on a fast day.

## 4. Done when

- the cause in §2 is answered **with timestamps**, and the `main`-vs-54 timing
  comparison is reported
- `StartAgent` side polls; the count of other fixed-sleep gates found is reported
- ⚠ **negative control** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: make
  the window genuinely fail to appear and prove the check still goes red. **A
  poll that always succeeds is indistinguishable from an assertion that never
  runs.**
- `accept.sh` **25/0** on unmodified `main`, exit 0
- `python3 -m pytest -q` green (356 at the time of writing)

## 5. Reporting

`jira done`, then message `architect` with the timestamps, the timing
comparison, the count of fixed-sleep gates, and the negative-control proof.

---

## 6. ⚠ URGENT, same file, separable gate: accept.sh can destroy the office

**It just did.** The office container was killed and had to be restarted by the
operator.

```bash
PROJECT="h-flock-${TENANT}"                                   # accept.sh:52
docker compose -p "$PROJECT" ... down -v                      # accept.sh:63
```

Our office is **`h-flock-office`**. `TENANT=office` — set deliberately, leaked
from the environment, or defaulted — resolves `PROJECT` to the live office and
`down -v` **destroys it and its volumes**.

⚠ **`accept.sh:62` has the same shape in miniature:**
`pkill -9 -f "[s]erver\.py --listen 0.0.0.0 --port $CONSOLE_PORT"` is an
unscoped host-level `pkill -f`. That pattern killed my own SSH shell twice this
week. It matches on any host, in any directory, owned by anyone.

### The rule

**Never destroy what you did not create in this run.** Record the project at
creation; tear down only that. Belt and braces:

1. **Refuse** if `$TENANT` names the live office (`$AGENT_OFFICE`), unless
   `FORCE=1` — `soak.sh` already sets this precedent and its comment explains
   why: *"the guard exists so it never happens to somebody's office by reflex."*
2. **Refuse** to `down -v` a project this invocation did not `up`.
3. **Scope the `pkill`** to the container, or drop it for a PID recorded at
   start.

### ⚠ Negative control

Run `accept.sh` with `TENANT` set to the office name and **prove it refuses**.
A guard that has never refused is not known to guard.

⚠ **This is separable from §1–5 and must be its own commit** so the flaky-gate
fix and the destructive-scope fix can be reviewed apart. It is in the same file
only because two lanes editing `accept.sh` concurrently would be worse.
