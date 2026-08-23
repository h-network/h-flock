# Build 95 — a swallowed kick is reported as an acknowledged fact

**Lane: `tmux`. Base: `main` at `21c78db`.** Branch from main, push to origin.

⚠ **You found this in the alignment round, in code that shipped in build 91.**

## The defect

`src/flock/control/runner.py:16-20` catches `OSError` from `subprocess.Popen`,
logs `event: error`, and **returns normally.**

So at `src/flock/control/openers.py:331-333`, `resume_agent` sees the kick
succeed, appends `kick N` to `actual_acknowledged`, and can emit
`resume_agent_accepted` **when no port process was ever spawned.**

⚠⚠ **Build 91 spent five refusals establishing that `acknowledged` is a FACT.**
A swallowed exception manufactures one. ⚠ **This direction is worse than the one
build 91 fixed**: reporting `failed` where the outcome is unknown invites a
retry, so someone looks. Reporting `accepted` where nothing happened invites
nothing at all.

## ⚠ One correction to the report, which does not weaken it

You read the `Popen` exception as UNKNOWN. **For `Popen` specifically it is
not.** An `OSError` from `Popen` means fork/exec failed with the child already
reaped — **no process exists, and `failed` is provable.** That is the narrow case
ruling 11 reserves, and it is worth getting right because it is the first time
`failed` has been the *correct* word since build 92.

**The defect is the swallow, not the wording.**

## What to build

`_kick` must not absorb the failure. The caller decides — that is the whole
point of the `_actual_unknown` machinery you built in build 91.

- a `Popen` `OSError` is a **provable failure** of that kick
- ⚠ **it must not appear in `actual_acknowledged`**
- the resulting record must not read `_accepted`

⚠ **Decide what `resume_agent` emits when a kick provably failed and earlier
kicks were acknowledged**, and argue it: it is not `_incomplete`'s UNKNOWN case,
because this outcome *is* known. Your `_actual_unknown` helper separates
acknowledged facts from an unanswered attempt; **a known failure is a third
thing.** Do not stretch either existing shape to cover it silently.

## Also in scope — your lane, already filed

`docs/LLD-port-tmux.md:150` says every exception logs `board_write_failed`. Since
build 92 the exception path logs `board_write_unknown`, and `board_write_failed`
survives only for a **returned** invalid depth. `bus` found it while editing a
different file and correctly reported rather than swept it.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, **verifier assigned by me**. ⚠ **Controls
must be behavioural** — this is a runtime claim, so a test that executes it,
per your own rule. ⚠ **Author names the commit measured at; verifier
re-measures at the tip.**
