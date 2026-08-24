# Build 109 — the gate before a live session

**Base: `main` at `0c42702`.** Method is
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md).

⚠ **Seven builds have merged since the last acceptance run** (98): 100, 101,
102, 103, 104, 105 and 108. **This is the check before the operator stands up a
fully-authenticated tenant for a feedback session**, so a failure here is worth
far more than a failure discovered during that session.

## Part 1 — regression

Fresh tenant on current `main`. `EXIT:$?` into the log, teardown, network check.

Per `BUILD-CONVENTION` §3.0: record `free -h` and `df -h /`, and **if a default
port is unavailable, name what holds it** before working around it. ⚠ **The lab
was cleared of our own litter yesterday** — 35 containers and two leaked
consoles — so it should be quiet. **If it is not, that is a finding in itself.**

⚠ **Build 101 changed `accept.sh`.** If you use `--keep`, the `kept:` line should
name the console PID, and `ps` for that process should show **no `--token` and no
`--secret`**. Build 98 proved it once; confirm it survived seven builds.

## Part 2 — the three surfaces that changed

**1. `office peers -v`.** ⚠ **You do not need authenticated CLIs for this** —
`peers -v` reads the `launch` key, which is set at hire, not at login. So hire
agents with **different `--cli` values** and confirm the framework column
distinguishes them, **including `framework=agy`** rather than `unknown`.

⚠ **Also confirm plain `office peers` is unchanged** — same comma-separated
string, and `telegram` still absent, since two acceptance gates depend on that.

**2. The agy label.** `office status` should read `not collected (agy)`, and
`office usage` `not collected` with `"collected": false` in `--json`. ⚠ **The old
key was `measurable`** — check whether it still appears anywhere in the output,
since the renderer was written to accept both.

**3. The credential retraction.** A recovered credential now emits
`status=present` instead of silently clearing. ⚠ **This may not be reachable on a
fresh tenant** — it needs a credential to go absent and then present. **Try; and
if you cannot reach it, say so plainly rather than manufacturing one.** That
list of what a run could not exercise has been the most useful thing in your last
four reports.

## Report

Two verdicts. Part 1's exit code does not stand for part 2. ⚠ **Hash the run log
and push the significant evidence**, as you have since build 97.

⚠ **State plainly whether main is fit for a live multi-agent session**, and name
anything an operator standing up an authenticated tenant should know first. That
judgement is the deliverable, not the exit code.
