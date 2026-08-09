# Build 32 — why a seeded claude credential goes stale, and what to do

> ⚠ **Measure first. Do not implement a fix in the first commit.** The mechanism
> is not known, and the last four times we guessed at a mechanism on this project
> the guess was wrong in a way that cost a day.
>
> **Base on `main`.** Branch `tmux/build-32-<piece>`, push to origin.

## 1. What happened, and what is actually established

A live session died at 15:30: a profiled agent's claude stopped working because
its credential was no longer valid. It was fixed by hand — re-seed, then
`pause`/`resume`.

Established:

- we copy `~/.claude/.credentials.json` into each profile's config dir at hire
- the watchdog **warns** on `claudeAiOauth.refreshTokenExpiresAt` and does
  nothing else
- **claude only.** codex and agy run for days on one token — h-cli has run both
  unchanged for days. Their `unknown` is correct, not a coverage gap

⚠ **Not established: why the copy went stale.** claude holds a refresh token and
renews its own access token, so a copy should heal itself. It did not.

## 2. Measure this, and write down what you see

The likeliest mechanism, and the first thing to test: **refresh tokens rotate.**
If claude replaces the refresh token when it renews, then every copy is racing
for a one-use token — the first process to refresh invalidates every other copy,
including the one we handed the agent.

If that is what is happening, **seeding by copy is structurally broken** and no
amount of re-seeding fixes it; it only shortens the window.

Answer these with observations, not reasoning:

- does the value of `refreshToken` in the source file **change** after the source
  claude refreshes? Record it before and after
- does a profiled agent's copy **update itself** while it runs, or stay frozen?
- after the source refreshes, does the copy still work — try it
- how long does an access token actually last

⚠ **Report the measurements even if they contradict the hypothesis above.** A
measurement that kills the theory is the most useful result this build can have.

## 3. Then decide, with the evidence in hand

Options, in the order I would consider them — but the measurements decide, not
this list:

- **share one config dir per account.** Profiles exist to separate *accounts*; two
  agents on the same account arguably want the same credentials, not two copies.
  What breaks: session files and history collide, and that may be fine or may not
- **re-seed on detection.** The watchdog already knows how to read the file; it
  could notice invalidity and repair. ⚠ This is a patch over a race if §2 shows
  rotation, and the build should say so rather than shipping it quietly
- **stop copying.** If credentials cannot be duplicated safely, say that plainly
  and make hiring on a profile require its own login

⚠ **Whatever is chosen, `unknown` stays `unknown` for codex and agy.** Do not add
expiry checks for them.

## 4. Done when

- §2 answered with recorded observations, in `docs/` as a findings file
- a decision, with the reasoning, in `LLD-tmux-host` — in the
  same commit as the change, per [`TODO`](TODO.md)
- if a fix lands, a way to prove it: force the condition, show the agent survives
- `TODO`'s credential entry closed or rewritten to match what was learned

## 5. Reporting

`jira done`, then message `architect` with the measurements, the decision, and
whether seeding by copy survives contact with them.
