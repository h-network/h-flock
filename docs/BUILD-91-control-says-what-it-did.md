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

## Done means

Pushed to origin. Tests green. `TEST-SIGNOFF` filled in, ⚠ **`VERIFIED BY` is not
you**, and ⚠ **evidence at an immutable path** — snapshot it, hash the snapshot,
quote the snapshot. `docs/TEST-SIGNOFF.md` gained that rule today and build 91 is
the first build to be held to it.
