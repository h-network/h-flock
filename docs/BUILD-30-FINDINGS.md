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

---

# Run 2 — `PASS=6 FAIL=4`, and a structural problem

The process walk, deadline polling, key-level assertion and profile isolation all
landed, and the shared tenant config is no longer touched. The cases still do not
reproduce, and the run says something more important than its score.

## 6. Only case 1 checks its own precondition — and it fails

```
  FAIL  CLI process is stopped (state T) : expected [0] got [1]
  ...
  FAIL  sim-wedged is blocked : [idle] lacks [blocked]
```

The precondition assertion is exactly right, and it reports that **the CLI was
never stopped**. `get_cli_pid` walks "first child, else first grandchild", which
is a guess: it takes the first branch it meets rather than the process whose
command matches the agent's launch. Resolve by **matching the launch value**
(`…:agent:<n>:launch`) against the descendants' `comm`, and stop that.

⚠ **A failed precondition must abort the case, not continue.** Having reported
the CLI was not stopped, the script went on to assert `blocked` anyway and
reported a second failure. That second line is noise — nothing was wedged, so
`idle` is the *correct* product behaviour. **A case whose setup did not happen
has no verdict to report.**

⚠ **Cases 2 and 3 assert no precondition at all.** Nothing checks that `sim-trust`
actually sat at a trust picker, or that `sim-nologin` actually reached a login
prompt. Their results therefore mean nothing in either direction.

## 7. What the run appears to say, and why we are not acting on it

| case | documented in `HLD` §8a | run 2 |
|---|---|---|
| trust picker | caught — `blocked` set | **not caught** — `idle` |
| login prompt | **missed** — the known gap | **caught** — `blocked` set |

That is the documented matrix inverted. ⚠ **Do not change `HLD` on this
evidence.** With no precondition checks, the likeliest explanation is that
neither agent was in the state its case is named for — a claude that started
fine, and a codex that exited rather than waiting at a prompt.

⚠ **This is why preconditions come first.** Without them a run cannot tell a
product bug from a simulator that set up nothing, and we came one step from
rewriting an architecture document to match an artefact.

## 8. Done when

Each case proves its own setup, aborts if the setup fails, and only then judges.
Then `FAIL=0` against the lab **with the run pasted in**. If a case proves its
precondition and still contradicts §8a, that is a real finding — report it and
change nothing until we have looked together.
