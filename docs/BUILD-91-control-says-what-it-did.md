# Build 91 — control says what it did

**Lane: `tmux`. Base: `main` at `633b4c4`.** Branch from main, push to origin.

**Sprint 2 of [`SPRINTS.md`](SPRINTS.md).** Files:
`src/flock/control/openers.py`, `src/flock/watchdog/service.py`.

All three loci re-verified against the tree on 2026-08-23 before this was
written.

## 1. A hire leaves no record of whether it worked

⚠ **`src/flock/control/openers.py` contains ZERO emit or log calls.** Verified by
count, not by reading. `StartAgent`, `StopAgent`, `PauseAgent` and `ResumeAgent`
take custody of an envelope and never say what they did with it.

**Measured:** two envelopes `architect -> host`, all six custody stages clean
through `opened`, and then silence. The only way to learn whether an agent had
actually been created was to attach to a pane.

⚠ **`LLD-bus-and-switch` states the contract as *"each component records that it
took custody and what it then did"*.** These four do the first half.

**The pattern already exists** — `src/flock/port/openers.py:211` emits
`board_write_confirmed` for `AddTicket`. Copy its shape: a confirmation per
control kind, naming the agent and the outcome.

⚠ **Failure is the case that matters.** A hire that refuses must say so in a
record, not only in a dead-letter. The two refused hires that produced
`opener failed: '2'` are the reason this row exists.

## 2. `--profile` is not validated against the accounts that exist

`src/flock/control/openers.py:71-73` validates the value as a **segment string**
via `prefix()`, not as a known account.

⚠ **Two different failures, and the quiet one is worse.** `--profile 2`
dead-letters with `opener failed: '2'` — a bare `KeyError` repr, naming neither
the problem nor the rule, arriving asynchronously one component away from where
it was typed. But `--profile typo` **passes**: `seedProfile` populates the
directory and the agent **starts cleanly against an account nobody configured**.
A clean start on the wrong account beats a crash for damage.

`--cli` got `choices=` on 2026-08-23. This did not.

⚠ **Validate at the client too, not only in the fabric.** The fabric was correct
to reject it; the client should never have sent it. Say which accounts exist in
the error.

## 3. A token-authenticated agent alerts `absent` forever

`src/flock/watchdog/service.py:264` tests for
`<home>/<directory>/.credentials.json`.

⚠ **`CLAUDE_CODE_OAUTH_TOKEN` shipped on 2026-08-23 and is proven to
authenticate.** An agent using it has **no credentials file at all** — correctly,
by design. The watchdog reads that as `status: absent`, raises a credential
alert, and **credential alerts never clear**, so the console renders a fault that
will never be true and never retract.

**An agent whose window carries a token is authenticated.** The check has to
know that.

⚠ **Do not "fix" this by removing the check.** A genuinely logged-out agent is
what it exists to catch, and that agent is silent in exactly the same way. The
difference is the token, and the token is per-profile in the window
environment — see how `src/flock/tmux/ops.py` injects it.

---

# ⚠ AMENDMENT — rulings after `bus`'s refusal, 2026-08-23

`bus` re-executed all five mutations independently: all five exit 1 at the
claimed loci, so **the controls are genuine and the snapshots match**. The
refusal is on product behaviour, and both findings are upheld. Two rulings were
asked for.

## Ruling 1 — accounts have a canonical record, and it is not the filesystem

⚠ **`available_profiles()` is wrong in both directions**, which is worse than the
gap it was closing. `bus` probed it exactly: token-only account →
`('default',)`, so a **legitimately configured account is refused**; after
`mkdir ~/.claude-typo` → `('default', 'typo')`, so **the artifact of the very bug
this validates against becomes proof the input was valid.**

**Config directories are derivative state.** `seedProfile` creates them, a
previous bad hire creates them, and nothing removes them.

**Ruling: persist what `setup.sh` configured, as tmux proposed.** `setup.sh`
already knows the complete account list at configure time; it currently exposes
only assignments and only non-empty tokens. Record the whole list, seed it into
Redis from the entrypoint before the startup environment is unset, declare the
key in `bus/resources.py`, and have **both** the office client and the fabric
read that one set.

⚠ **Absent key means DO NOT VALIDATE.** A tenant created before this key exists
must not have every profile refused. `src/flock/bus/policy.py` already sets this
precedent — `allows()` permits when policy is absent — and this follows it. Say
so in a comment at the check, because the permissive branch is the one a later
reader will mistake for a bug.

⚠ **State the limit in the results doc**: an account added outside `setup.sh`
(hand-seeded, `seed-home`) is not in the canonical list until setup runs again.
That is an acceptable and *visible* failure — a refusal naming the accounts that
exist — where today's is an invisible one.

## Ruling 2 — three outcomes, because there are three

⚠ **The decorator records the wrapper's return or exception, not what the control
mutated**, and `bus` proved the consequence: `stop_agent_failed` with reason
`tmux kill failed`, emitted **after** the roster `hdel` and the resource purge had
already committed. Verified in the tree: `stop_agent` commits desired state and
*then* calls `kill_window`; `pause_agent` sets the marker and *then* interrupts.

**A record that says `failed` when the agent is already gone from the roster is
worse than no record**, because a wrong record is trusted. That contradicts the
title of this build.

**Ruling: three records, named for what a reader must do next.**

| record | meaning |
|---|---|
| `<kind>_confirmed` | desired state committed **and** actual state followed |
| `<kind>_incomplete` | desired state committed, actual state did **not** follow. ⚠ **No rollback happened.** Must name what committed and which side effect failed |
| `<kind>_failed` | nothing changed. Validation or the desired-state mutation itself failed |

⚠ **`_incomplete`, not `_side_effect_failed`.** Both are honest; the reader of a
control log is asking *"what is the state now, and what must I do"*, and
`incomplete` answers that in one word while `side_effect_failed` describes the
mechanism. `docs/NAMING-tmux.md` is yours and a naming review is on the board —
**counter with a locus if you disagree** and I will take it.

⚠ **`_incomplete` still dead-letters.** Partial is not success.

## Ruling 3 — one finding neither of you raised, and it is mine

`src/flock/watchdog/service.py` now does `continue` when
`CLAUDE_OAUTH_TOKEN_<ACCOUNT>` is present. That correctly stops the false
`absent` alert. ⚠ **It also means a token-authenticated agent is never checked at
all**, so a **revoked or expired token is invisible** — the agent is dead and the
watchdog is silent, which is the failure mode the check exists for.

**I am not asking you to fix that in this build.** A token cannot be validated
locally; presence is the only signal available without an API call. **State it as
a known limit in the results doc**, in the comment at that `continue`, and I will
put it on `TODO.md` myself. An untested claim that says so is fine; a silent one
is not.

---

# ⚠⚠ SECOND AMENDMENT — my first ruling was wrong, 2026-08-23

`bus` re-executed all nine mutations: all exit 1 at the claimed loci. **Two of
its three findings are against the AMENDMENT above, not against the
implementation.** `tmux` built what I specified; what I specified was not true of
this architecture. Recorded in full because a ruling that cannot be refused is
not a ruling, it is a decree.

**What I got wrong.** The three-outcome table assumed (a) desired-state writes
commit atomically and (b) a control opener can observe actual state. Neither
holds. `stop_agent` performs **two** desired writes — `hdel` then `purge_agent` —
and `start_agent` performs several; a failure between them reaches `_failed`,
which my own table defines as *"nothing changed"*, after the roster row is
already gone. And `tmuxhost.reconcile_once` applies actual state
**asynchronously**, so a fresh hire returns before any window exists.

## Ruling 4 — the opener speaks only about desired state

⚠ **`_confirmed` is withdrawn from the opener. Rename it `_accepted`.**

| record | meaning |
|---|---|
| `<kind>_accepted` | **all** desired-state writes committed. ⚠ **Claims nothing about actual state**, which reconciles later |
| `<kind>_incomplete` | **some** desired-state writes committed. ⚠ **Must name the committed subset explicitly** — "roster row removed, resource purge failed" — because no rollback happened and the reader has to know what is already gone |
| `<kind>_failed` | **no** desired-state write committed. Validation, or the first write |

The inline actual-state attempts — `kill_window`, `interrupt_window` — stay under
`_incomplete`, since desired state committed and the inline attempt did not. The
`reason` field already distinguishes them and `bus` should say if that conflates
too much.

## Ruling 5 — `pending` is right, and it is not this build

`tmux` proposed `start_agent_pending` at the opener with `tmuxhost` emitting
`confirmed` after the window exists, and **argued against** synchronously waiting
because it turns an asynchronous architecture into a gate and window presence
does not prove correct configuration. ⚠ **That reasoning is correct and it is the
better design.**

⚠ **But it is a new emission path in a component this build does not touch.**
Build 91 lands the opener half — `_accepted`, `_incomplete` naming its subset,
`_failed` — which is complete, testable, and truthful on its own. **`tmuxhost`
emitting `<kind>_confirmed` is its own build**, and it is what finally closes
*a hire leaves no record of whether it worked* rather than half-closing it.

⚠ **Say so in the results doc**: build 91 records what control *accepted*, not
what *happened*. A build that half-closes a row and says which half is fine; one
that implies the whole is not.

## Ruling 6 — do not make the writes atomic here

Redis cannot roll back committed commands, so the truthful options are naming the
committed subset or giving desired state an atomic representation — a Lua script,
as `watchdog/activity.py` already uses for usage emission.

⚠ **Name the subset. Do not add atomicity in this build.** It is a design change
with its own argument, and it is going on the board. The record becoming truthful
is this build's job; making the failure impossible is not.

## Ruling 7 — bind each gate to the tree it actually ran against

`bus` measured the checker at `64744b1` as 0 hard / **58** near, while the
snapshot quotes **52**, which reproduces at `6adce63` after `NAMING-tmux.md`
changed. **All hashes match** — the artifact is authentic and was produced at a
different commit than the one printed beside it.

⚠ **A citation gate validates DOCUMENTS, so it binds to the docs commit.** Print
`6adce63`, not the code SHA. ⚠ **Same class as build 88's non-existent sha and
strictly subtler**: there the evidence pointed at nothing, here it points at
something real that is not what the line claims. **A sign-off field naming the
wrong true thing is harder to catch than one naming a false thing.**

---

## Done means

Pushed to origin. Tests green. `TEST-SIGNOFF` filled in, ⚠ **`VERIFIED BY` is not
you**, and ⚠ **evidence at an immutable path** — snapshot it, hash the snapshot,
quote the snapshot. `docs/TEST-SIGNOFF.md` gained that rule today and build 91 is
the first build to be held to it.
