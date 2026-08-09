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
over. **the build 30 spec** §2 said poll, never sleep, and named
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

---

# Run 3 — `PASS=7 FAIL=3`, and the harness finally earns its keep

Every case now proves its setup and aborts if it fails. The suite stopped lying,
and immediately produced two findings — one real product bug, one about the gap
we thought we had.

## 9. The api never surfaces `blocked` — clients cannot see it at all

⚠ **`GET /agents/<name>` can never return `blocked`.** `api/app.py` builds
`presence.state` from the presence hash alone (line ~552) and never reads
`…:agent:<n>:blocked`. Only `office/cli.py` §192 folds it in, so the state exists
for the CLI and is invisible over HTTP.

⚠ **`API.md` documents it as a presence value and says "`blocked` is the one to
act on".** Both clients in `clients/` implement that path. It is dead code — the
Telegram bot's *"not accepting messages"* branch, a stated done-when of build 29,
can never fire.

This is the state the entire verification path exists to produce, and the only
consumers that matter cannot observe it.

## 10. The login-prompt gap did not reproduce

Case 3 **proved its precondition** — the login prompt was on screen — and
`blocked` was set:

```
  ok    sim-nologin precondition proved (login prompt shown)
  FAIL  known gap: blocked key is empty : got [since … stream_id …]
```

⚠ **The documented gap is at least too broad.** For codex at a login prompt the
delivery was judged unverified and `blocked` was set — caught, not missed.
`HLD` §8a and `TODO` both say this case is missed.

⚠ **Nothing changes in `HLD` or `TODO` yet.** One CLI in one state is not the
claim either file makes, and cases 1 and 2 still cannot set up. The gap was
originally seen with claude, and that is the case still unproven.

## 11. Why cases 1 and 2 cannot set up

⚠ **The pane process *is* the CLI.** Measured on a live agent:

```
  PID  PPID STAT COMMAND
   33    32 Ssl+ claude --dangerously-skip-permissions --tools Bash Read …
```

`pane_pid` is claude itself — there is no shell child. `get_cli_pid` walks
*descendants*, so it stops one of claude's own subprocesses and leaves claude
running. **Check the pane process first** and only walk down if its `comm` does
not match the launch value.

⚠ **Cases 1 and 2 poll `presence.state` for `blocked`, which §9 shows is
impossible over the api.** Assert the key directly, as case 3 already does. Both
would have failed even with a perfect setup.

Case 2 additionally needs to prove *why* no picker appeared — whether claude in a
fresh profile shows onboarding before trust, or the cwd was trusted by another
path.

---

# Runs 4–7 — `PASS=13 FAIL=1`, and the race that produced our beliefs

I took the harness over at this point. Three findings, and the first one
undermines evidence we had been reasoning from.

## 12. Asserting an absence was a race, and it invented a gap

Case 3 asserts that `blocked` is **not** set. It did that by polling the key for
20 s and calling an empty result a verdict. But an empty key also means *the
router has not judged yet*, so the assertion passed whenever the pass was slow.
That is why run 3 and run 4 disagreed with the same proven precondition.

⚠ **The deterministic signal is the marker.** The router drops a `pending.verify`
entry once it judges, so the verdict exists when the stream empties — with the
same trap: an empty stream before the adapter writes is not a verdict either.
`poll_judged` waits for the marker to **appear**, then to **go**. A probe without
that reported *"judged after 1s"* with nothing delivered.

⚠ **Prefer asserting a presence over an absence.** Every timing bug here lived in
an absence check.

## 13. The login-prompt gap did not reproduce

With the race gone, `sim-nologin` — precondition proved, login prompt on screen —
is **caught**: `blocked` is set.

⚠ **`HLD` §8a and `TODO` both say this case is missed.** On this evidence, for
codex at a login prompt, it is not. The claim needs re-testing for claude before
either file changes, and **neither has been changed.**

## 14. `blocked` fires on a healthy agent that is still starting

The one remaining failure, and it is the product, not the harness:

```
  ok    sim-trust started without a trust picker (seeding works)
  ok    sim-trust marker judged
  FAIL  sim-trust delivery verified (blocked key empty) : got [since … stream_id …]
```

A fully trusted, correctly credentialed claude agent, delivered to shortly after
`StartAgent`, is judged **unverified**. `VERIFY_AFTER_SECONDS` is 10 and a cold
claude does not record an input event that fast, so the verdict lands before the
CLI is ready.

⚠ **This is a false positive on the one state clients are told to act on.** Over
the api a user hiring an agent and messaging it immediately is told *"not
accepting messages"* for a healthy agent — and after build 30's decision there is
no retry behind it. Whether the paste itself survives a cold start is a separate
question this run does not answer.

## 15. Where the simulator ended up

| case | how it is simulated | result |
|---|---|---|
| wedged CLI | pane respawned with a non-consuming process, `launch` left as claude | `blocked` set ✓ |
| trust seeding | a normal profiled agent, asserted to show no picker | delivery **unverified** ✗ §14 |
| login prompt | codex in a credential-free profile, prompt proved on screen | `blocked` set — gap not reproduced §13 |

⚠ **SIGSTOP cannot wedge a tmux pane process here.** A plain `sleep` from a shell
reaches state `T`; the same `sleep` as a tmux pane never does, and the
process-group form fares no better. Three runs of case 1 silently simulated
nothing on top of that.

---

# Build 31 verified — `PASS=19 FAIL=0`, and the gap does not stand

Reproduced independently on the lab, not taken from the lane's report.

## 16. The documented login-prompt gap is not real for either CLI

| case | result |
|---|---|
| wedged CLI (pane consumes nothing) | `blocked` set ✓ |
| healthy fresh agent | **not judged**, `blocked` empty ✓ — build 31's rule |
| codex at a proved login prompt | `blocked` **set** — caught |
| claude at a proved login prompt | `blocked` **set** — caught |

⚠ **`HLD` §8a and `TODO` both claim this case is missed. On this evidence it is
caught, for both CLIs we run.** Neither file has been changed — see §17.

⚠ **The case tested is the one that matters:** an agent with activity history
that is *now* at a login prompt — a credential expiring under a working agent,
which is what ended a live session at 15:30. An agent that starts at a login
prompt and never speaks has no history, so under build 31 it is `unknown` and
never judged. Both are correct; they are different states.

## 17. Rebuilding a tenant destroys runtime enrolments

`bus` rebuilt the tenant to run its branch, which restarted the container. Agents
in the tenant's configured roster came back — `architect`, `sme-2`, `sme-3`.
Everything **hired or enrolled at runtime did not**: the `networking` agent, and
the `telegram` and `web` client enrolments.

⚠ **The clients kept running against a tenant that no longer knew them.** No
error surfaces to the user of a chat app; the bot simply goes quiet. I re-enrolled
both. `networking` is gone and would have to be hired again.

⚠ **Say this in `LLD-container`.** A rebuild is not a restart of the same office —
it is a new office wearing the same name, and anything not in configuration is
lost. Anyone testing against a live tenant needs to know that before they do it.
