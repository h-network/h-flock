# Build 94 — acceptance after build 91

**Base: `main` at `0d8379a`.** Method is
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md); two parts
and two verdicts, as in build 90.

⚠ **Build 91 has never been through an acceptance run.** It changed the control
openers — the path that creates, stops, pauses and resumes agents.

## Part 1 — regression

Fresh tenant, `PATH=~/pw-venv/bin:$PATH`, `EXIT:$?` into the log, teardown check,
network check. Same as build 90.

⚠ **The control path IS exercised this time, unlike `office usage` was.**
`container/plumbing-check.sh:147` posts a `StartAgent` for `telegram`, and
`clients/web/flow-check.py:82` and `clients/web/flow-check.py:103` post
`StartAgent` through the console flows. So a regression in build 91 should
surface here — which is the first thing worth knowing.

## Part 2 — the records, which nothing checks

⚠ **Exercising a code path is not verifying its claim.** Build 90 proved that:
`office usage` was never invoked by the harness at all, and only a by-hand check
established anything. Here the path runs and **nothing asserts what it emitted.**

Against the tenant, after the run has hired something:

1. **Find the control records in the custody log.** Build 91 emits
   `start_agent_accepted` and the `stop` / `pause` / `resume` equivalents. Confirm
   a `StartAgent` that succeeded produced `start_agent_accepted`, naming the agent
   and carrying a `correlation_id`.
2. ⚠ **Establish which control kinds the run actually reaches.** `StartAgent`
   is posted; **whether `StopAgent`, `PauseAgent` or `ResumeAgent` run at all is
   unknown to me.** If a kind is never exercised, **say so** — an unexercised
   record is an unverified claim, and naming it is the deliverable.
3. **Try a hire that must be refused** — `office hire x --profile <an account that
   does not exist>`. Build 91 validates against configured accounts now. Expect a
   client-side refusal **naming the accounts that exist**, and check whether a
   record was emitted or the refusal happened before the envelope was sent. Both
   are legitimate; which one happened is the finding.
4. **`_accepted` does not mean the window exists.** Note whether the window
   appeared, and how long after. ⚠ **That gap is by design** — `tmuxhost`
   reconciles asynchronously, and the confirmation is a separate row on
   `TODO.md`. **Measuring the gap is useful data for that build.**

⚠ **Do not synthesise records.** If a kind is not reached, that is the result.

## Report

Two verdicts. Part 1's exit code does not stand for part 2. Per
`BUILD-83-acceptance-seat.md`, and — as you have done unprompted three runs
running — **name what you could not reach.**
