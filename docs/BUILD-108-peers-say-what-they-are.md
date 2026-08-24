# Build 108 — `office peers` says what a peer actually is

**Lane: `tmux`. Base: `main` at `2cb0402`.** Branch from main, push to origin.

⚠ **Scheduled ahead of two already-specced builds because a live feedback session
is imminent, and this is the one the agents will use in the first five minutes.**

## Why

`src/flock/office/cli.py:163-176` is fourteen lines: `members()`, then print the
names. **A peer is a string.**

⚠ **Raised by the agents themselves after the 2026-08-23 session**, and by the
agy agent in particular — **the one that most needed it.** Four agents reasoned
about each other for an hour with no idea what each other *was*, and capability
genuinely differs by CLI: one cannot be pointed at a local model, one cannot be
priced, and none of them could tell which was which.

## What to add

`office peers -v` (or `--verbose`) showing, per peer:

- **framework** — `claude`, `codex`, `agy`
- **profile** — the account, where one is set
- **current task** — what it is doing, if anything

⚠ **Every value already exists and is already read in this file**: `launch` at
`src/flock/office/cli.py:232`, `tasks.doing` at
`src/flock/office/cli.py:223`, and profile alongside them. **This is a display,
not a new data path.** If you find yourself adding a Redis resource, stop and
tell me — the estimate is wrong and I would rather know before you spend the day.

⚠ **Plain `office peers` must not change.** Scripts and agents use it, and the
delivery tests count on its shape.

## Also, if it stays cheap

`office send`'s acknowledgement prints destination and bytes accepted. **Add the
`correlation_id`.**

⚠ **Read-only. Do NOT accept one** — taking a caller-supplied id is the deferred
threading question, and half of it is worse than none. Printing the id the fabric
already minted needs no decision at all, and it lets agents refer to a thread out
loud instead of reconstructing topology socially, which is what they actually did
last time.

⚠ **If this turns out to be more than a few lines, drop it and say so.** It is a
convenience riding a build that has a deadline; the peers half is the one that
matters.

## What "unknown" must not mean

⚠ **An agy peer's framework is known** — it is `agy`. Do not let it render as
`unknown` because a *usage* lookup returns nothing. **We have spent two builds on
the word `unknown` meaning three different things**; do not add a fourth.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Behavioural
claim** — a test that hires agents on different CLIs and asserts the output
distinguishes them. ⚠ **Assert the plain `peers` output is unchanged**, since
that is the regression risk.
