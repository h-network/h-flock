# Build 42 — test the framework, not the code

> Every audit so far was **reading**. This one is **running**. Fifty findings
> came from reading; the four that cost an operator an evening came from using
> the product, and no amount of reading would have produced them.
>
> **Base on `main`.** Branch `<lane>/build-42-scenarios`, push to origin.

## 0. First, find out whether you can run anything

⚠ **You have been reporting "Docker unavailable in this lane", and that was
true of your own container — but nobody ever told you a lab exists.** Check:

```bash
ssh -o ConnectTimeout=10 h-lab@172.16.0.14 'docker ps --format "{{.Names}}"'
```

⚠ **`api` ran this and it answered** — exit 0, listing `h-flock-w3-tenant-1` and
`h-cli`. So the capability is real; check yours rather than assuming it differs.

**Report the result in your first message back, either way.** It decides how the
rest of this build runs, and a wrong guess wastes a day:

- **it answers** → you run your own scenarios against your own tenant
- **it refuses** → you write the scenarios, I run them, you interpret the output

⚠ **Do not guess which.** "I assumed I could not" is what made every lab pass
this week serial through one pair of hands.

### If you can reach it, the house rules

| lane | tenant | ports |
|---|---|---|
| `bus` | `bus-lab` | 8100 / 8101 |
| `api` | `api-lab` | 8110 / 8111 |
| `tmux` | `tmux-lab` | 8120 / 8121 |

- ⚠ **`h-cli` is not ours. Never touch it.** It has been up for days and belongs
  to the operator.
- your own clone, your own compose project, and **`down -v` when you finish** —
  a stopped container still holds its ports
- **never run against another lane's tenant**
- `plumbing-check` needs `FORCE=1` on a tenant whose agents run CLIs, and the
  script explains why
- per-lane ports work **only because** wave 2 pinned the container-side bind;
  before that, publishing on a different port broke the tenant silently

## 1. What to produce

**One page of invariants** for your module: what must be true under real
conditions, and — the part that matters — **what observation would falsify it**.
An invariant nothing could disprove is not an invariant.

**Then scenarios**, as scripts in `container/scenarios/<lane>-<name>.sh`. Each
one prints **what it did and what it saw**. ⚠ **Do not print a verdict.** A
scenario that says `PASS` hides the output someone else needed to see; the whole
value of these is that a second reader can disagree with your conclusion.

## 2. What to test — the things reading cannot find

Not a checklist to complete; a set of directions. Pick what is dangerous in
*your* module.

- **Failure injection.** Kill Redis mid-delivery. `SIGKILL` the router with
  envelopes in flight. Kill a pane while an adapter is pasting into it. Restart
  the container with agents mid-task. Fill the disk the window-log spool writes
  to.
- **Time.** Hours, not minutes. Stream trimming, activity offsets, presence
  cost, session-door memory, spool truncation. ⚠ **Audit rows 14, 15 and 48 all
  live here and none of them fire in a five-minute test.**
- **Concurrency.** Two hires of one name at once. Pause during a delivery.
  Retire an agent while a client types into it. Two viewers on one pane.
- **Scale.** Ten agents. Broadcast storms. The 1 MiB payload limit at its edge.
- **The boundary.** An agent reaching for Redis, the token, or another agent's
  workdir. ⚠ **The last one succeeds** — `/workdir` is shared and every agent is
  the same user. Measure it rather than assuming it, and say whether the
  documented boundary still reads honestly.
- **Real work.** Credentialed agents doing a task through tickets and messages.
  That is the product, and it is the only way `blocked` gets exercised for real.

## 3. Rules that carry over, because they worked

- **Confirm before concluding.** A surprising observation is a claim until you
  have run it twice.
- ⚠ **"I could not make it fail" is a finding.** Write it down with what you
  tried. Three rows were correctly closed that way this week.
- **Report what you could not run**, and why.
- ⚠ **Do not fix anything in this build.** Findings first, ranked. We remediate
  in waves afterwards, as we did with the audit — mixing the two is how a
  finding gets quietly "fixed" into something nobody else can reproduce.

## 4. Cross-reading

When your scenarios have run, **read one other lane's raw output** and say where
you disagree with their reading of it. Two independent audits found two
different defects in the same four lines of `entrypoint.sh` this week; the same
effect applies to results.

## 5. Done when

- your invariants page exists, with falsifying observations
- your scenarios are committed and have been run **somewhere**, by you or by me
- the raw output is attached to your report — verbatim, including the dull parts
- ranked findings, each with what you observed and how to reproduce it

## 6. Reporting

`jira done`, then message `architect` with: whether you could reach the lab, what
you ran, what you saw, what you could not make fail, and your ranked findings.
