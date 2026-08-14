# How a build spec is written

Short, because the format has worked for 50 builds implicitly. This records the
one rule that was learned expensively, plus the structure already in use.

## 1. ⚠ The rule: a new gate must be shown to FAIL

**Any check a build introduces as its pass criterion must be demonstrated going
red.** Break the thing on purpose, show the gate fail, and put that in the
report. Five minutes per gate.

⚠ **This exists because of four separate incidents on one day, all the same
shape: the green signal was produced by something other than the thing under
test.**

| what looked green | what was actually true | what a negative control would have done |
|---|---|---|
| custody log complete | two records shared a torn line; the parser silently dropped both | write two records concurrently, prove the parser notices |
| 345 tests passing after a rename | passing on `vab = port_type` aliases that hid a half-done rename | delete the alias, prove the suite goes red — **it would not have** |
| web client tests passing | passing against a mock returning the **old** wire shape | point the mock at the real shape, prove the client fails |
| `accept.sh` exit 0, "passed" | `plumbing-check` printed `FAIL=1` and exited 0 | break one check, prove non-zero exit |

⚠ **More tests would have caught none of these.** The failure was never
insufficient coverage — it was gates that could not fail. Spend the effort on
falsifiability, not on volume.

⚠ **A fix for a false-pass that is itself only tested by passing is not proof.**

## 2. The structure that has been working

- **base and branch** named in the first line — `main` unless stated, so a lane
  does not start from whatever it had checked out
- **what is NOT in scope**, explicitly. The most useful section in every spec so
  far, and the one that stops a build growing a router it did not need
- **what would make this a "no"** for a trial or spike, written **before** the
  work, so a negative result is a result and not a failure
- **done when** — the gates, each one falsifiable per §1
- **reporting** — `jira done`, then message `architect` with the commit, the
  evidence, and status

## 3. ⚠ Measurement, if the build claims a number

- **medians, not means.** The lab's loopback Redis averages 1.7 ms with 26 ms
  spikes; a mean measures the spikes
- **interleave A/B per iteration**, or drift measures the drift
- **same container, same run, same method** on both sides. Host-wall against
  inside-container is not a comparison
- **redirect to a lab-local file.** An SSH detach has already cost one run's
  evidence
- ⚠ **`docker exec` output does NOT reach `docker logs`.** `docker logs` shows
  PID 1's streams; a process started by `docker exec` writes to the exec session
  instead. **Records emitted by an exec'd process are invisible to anything
  reading the container log.** Three occurrences: `fabric-bench` reported
  `sent: 54` against `popped: 553`; `bus` flagged it in build 47's evidence and
  declined to present those counts as a custody audit; build 58's duplicate
  control injected a real duplicate that reconciliation then scored as a *loss*.
  ⚠ **A control must travel the same path as the thing it controls for** — do
  not teach the reader about a second evidence source, make the control use the
  first one
- ⚠ **`docker exec` with a heredoc needs `-i`.** Without it the program reads
  empty and exits 0 — silently, successfully, having done nothing. Also three
  occurrences
- **one h-flock tenant at a time** on the lab
- ⚠ **to attribute an INVISIBLE loss, bracket it by FIFO position.** A frame that
  vanished with no records cannot be attributed by its own timestamps — it has
  none. But a per-source queue is FIFO, so the frames **before and after it from
  the same source** bound when it must have been at the head. If an injection
  window falls between those two pops and the frame has no `popped` record, it is
  attributable. `bus` used this on build 66's two vanished frames where
  "sent before a kill" would have proved nothing
- ⚠ **state the prediction before measuring.** Four claims were retracted in one
  day because a measurement was read as confirming what was expected

## 4. ⚠ Specs are fallible; the base is not

Two spec errors in one day were caught by lanes reading the **base branch**
rather than the prose: `vab` tiered as an internal rename when it is a wire
field, and an allow-list table written in the post-rename vocabulary that would
have broken every current caller.

**A lane that finds the spec contradicts the code should say so and stop, not
implement the spec.** Both catches were worth more than the builds they
interrupted.
