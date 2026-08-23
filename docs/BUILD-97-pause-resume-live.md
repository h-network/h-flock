# Build 97 — run the two control kinds nothing has ever run

**Base: `main` at `60f329d`.** Method is
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md).

⚠ **You established the reason this ticket exists.** Build 94's coverage table
counted **11 `start_agent_accepted`, 15 `stop_agent_accepted`, and ZERO of
`pause_agent_*` or `resume_agent_*`** across 284 records — and zero of **any**
`*_incomplete` or `*_failed`, for all four kinds. Nothing in the harness runs
them.

⚠ **This ticket was deliberately held until build 95 landed**, because 95 rewrote
the resume path: `_kick` no longer swallows a `Popen` failure, and a fourth
outcome `{kind}_partially_failed` now exists. Running it before would have tested
code about to change.

## Part 1 — regression

As build 94. Fresh tenant, `PATH=~/pw-venv/bin:$PATH`, `EXIT:$?` into the log,
teardown, network check.

⚠ **Per `BUILD-CONVENTION` §3.0, which changed on your evidence**: record
`free -h` and `df -h /` in the results, and **if a default port is unavailable,
name what holds it** before working around it.

## Part 2 — pause and resume, for the first time

Against the kept tenant, on a real hired agent:

1. **`PauseAgent`** — pause an agent and find the record. Expect
   `pause_agent_accepted` naming the agent with a `correlation_id`. Confirm the
   agent is actually paused, not merely recorded as paused.
2. **`ResumeAgent`** — resume it. Expect `resume_agent_accepted`. ⚠ **Resume
   kicks once per queued ingress envelope**, so a resume with mail waiting
   exercises more of the path than an idle one. **Queue something first** — send
   the agent a message while it is paused, then resume.
3. **Report what the records say versus what the tmux session shows.** `_accepted`
   means desired-state writes were acknowledged; it does **not** claim the CLI is
   running. Measure the gap if there is one, as you did for `window_created`.

## ⚠ Part 3 — do NOT manufacture a failure

Every `*_incomplete`, `*_failed` and `*_partially_failed` shape remains
unexercised, and **that is not this ticket.** Producing one needs a Redis write
to lose its reply, or `Popen` to fail — conditions you cannot create on a live
tenant without breaking it.

**Report which shapes are still unexercised after this run.** That list is a
deliverable. ⚠ **Do not stage a fault to tick a box** — a synthesised failure
proves the code path runs, which is what the unit tests already prove, and it
would put a fabricated record in a real custody log.

## Report

Per `BUILD-83-acceptance-seat.md`. Two verdicts. ⚠ **And per your own alignment
answer: sha256 each run log and state the hash**, then copy the significant ones
into `docs/evidence/`. Anything a row or a results doc will cite is significant —
your `4.091 s` figure was, and nothing in the tree can regenerate it.
