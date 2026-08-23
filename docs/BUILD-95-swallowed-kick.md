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

---

# ⚠ AMENDMENT — the name, ruled after `bus`'s refusal

`bus` cleared the mechanics completely: it independently restored the swallow and
watched the control fail with `DID NOT RAISE ProvableActualFailure` emitting
`resume_agent_accepted`; it traced `ProvableActualFailure` to a single
construction site at `src/flock/control/runner.py:23` and a single catch at
`src/flock/control/openers.py:364`, with generic exceptions still flowing to
`_actual_unknown`; and it ran the merged-tree check. **The refusal is the event
name alone.**

## Ruling 12 — `{kind}_partially_failed`, not `{kind}_partial`

⚠ **I raised this as a reservation and deliberately did not rule it**, because I
had been wrong on this contract four times. `bus` reached it independently and
stated it better than I did:

> *`partial` and `incomplete` are ordinary-language near-synonyms, while here
> `partial` means a later step is provably rejected and actionable, and
> `incomplete` means an attempt has no reply and is not actionable.*

**That licenses the exact inference ruling 11 exists to prevent — one level up,
at the event name.** A reader seeing `resume_agent_partial` beside
`resume_agent_incomplete` cannot recover the distinction without consulting
prose, and an event name that needs a footnote is not a name.

**Adopt `resume_agent_partially_failed`**, `bus`'s formulation and its reasoning:
`partially` preserves the acknowledged subset, and **`failed` is the correct
reserved word here** because the named kick was provably rejected. This is the
narrow case ruling 11 holds `failed` in reserve for, and the first record in the
repository to earn it since build 92 took the word away from five others.

⚠ **The reason string stays as built** — acknowledged desired work, acknowledged
actual work, and the failed action, kept separate. Nothing about the
classification, cause chain, dead-lettering or no-retry behaviour changes.

⚠ **Note for whoever adds the fifth shape**: this vocabulary is now
`accepted` · `incomplete` · `partially_failed` · `failed`. Each licenses exactly
one inference, and **the names must differ as plainly as the meanings do.**
