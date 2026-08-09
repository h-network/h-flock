# Build 30 — what the live run found

> `container/sim-blocked.sh` was reported done on unit tests. Run against the lab
> tenant it scores **PASS=3 FAIL=3**, and the three passes are the window-cleanup
> checks. Every assertion the simulator exists to make fails.

## 1. Case 1 does not wedge anything

```
  pane=39003   (SIGSTOP sent)
  polled presence for 60s → never blocked
  final=idle
```

⚠ **`pane_pid` is the pane's shell, not the CLI.** claude runs as its *child*, so
`kill -STOP $PANE_PID` stops bash and leaves claude consuming input normally. The
delivery then verifies correctly — the agent was never wedged.

Stop the **CLI** process: walk to the descendant whose command matches the
launch, or signal the process group. Then assert it is actually stopped (state
`T` in `/proc/<pid>/stat`) **before** sending the envelope. A simulator that
silently simulates nothing is worse than no simulator.

## 2. Fixed sleeps, which the spec ruled out

`sleep 4` after StartAgent and `sleep 12` for the verification pass, five times
over. [`BUILD-30`](BUILD-30-unverified.md) §2 said poll, never sleep, and named
the three flakes in this repo that came from sleeping.

`VERIFY_AFTER_SECONDS` is **10** and the router judges on its own pass, so 12 s
is inside the margin even when the case is set up correctly. Poll for the
condition with a deadline, and fail with what it saw.

## 3. Case 3 asserts the wrong thing

```
  ck "blocked is NOT set" "$BLOCKED_STATE" "idle"
```

The gap is that **the `blocked` key is absent**, not that presence reads `idle` —
a CLI at a login prompt can legitimately read `working`. Assert the key directly
(`HGETALL …:agent:<n>:blocked` empty). As written it fails for the right
behaviour and passes for the wrong one.

## 4. The trust file — fixed, but the approach is still wrong

`6617732` added backup/restore with a `trap`, which is the right instinct and
came after the run. For the record of what the original cost:

⚠ **`rm -f /home/ubuntu/.claude.json` deletes the tenant-wide claude config**, and
the live office was using it. It came back rebuilt by claude with only the sim
agents' entries — **the trust for `architect`, `sme-2`, `sme-3` and `networking`
was gone.** Running agents survived because trust is held in memory; any restart
would have landed every one of them at the picker. I re-seeded them by hand.

⚠ **Do not mutate shared tenant state to simulate a per-agent condition.** Give
the sim agent its own `HOME` or profile and leave the tenant's config untouched.
Backup-and-restore still fails if the container is killed mid-run, and it makes
the whole tenant unsafe for the duration.

## 5. Done when

`bash container/sim-blocked.sh` reports **FAIL=0 against the lab tenant**, with
the run pasted into the report — not unit tests. Case 3 still asserts the gap.
