# Build 90 — acceptance after build 88, and the hole it exposes

**Base: `main` at `633b4c4`.** Method is
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md).

⚠⚠ **A GREEN ACCEPTANCE RUN WOULD NOT COVER BUILD 88.** I grepped before writing
this: neither `container/accept.sh` nor `container/plumbing-check.sh` invokes
`office usage` or `office status` **anywhere**. Build 88 changed the watchdog's
codex extraction and both of those renderers. So the harness would pass, tell us
nothing about the build, and read as if it had.

**This ticket is therefore two things**, and the second is the point.

## Part 1 — the regression run

Exactly as build 89. Fresh tenant, `PATH=~/pw-venv/bin:$PATH`, `EXIT:$?` into the
log, teardown check. This answers *"did build 88 break anything already
covered"* — a fair question, just not the interesting one.

⚠ **Use `--keep`** so the tenant survives for part 2, and tear down manually
afterwards with `docker compose -p h-flock-<tenant> down -v`. **You now own the
teardown that `accept.sh` normally does for you.**

## Part 2 — exercise what acceptance cannot reach

Against that live tenant:

1. **`office status`** — runs without error, and renders. Note what it says in
   the activity column for each agent.
2. **`office usage`** — runs without error. ⚠ **An empty table is a legitimate
   result** on a fresh tenant whose agents have done no work; report it as empty
   rather than as a failure, and say whether any agent produced usage records at
   all.
3. **`office usage --json`** — valid JSON, and note whether `rate_limits` appears
   on any row.
4. ⚠ **Hire an agy agent if the tenant's configuration allows it**, and check
   that `office status` and `office usage` name it **not measurable** rather than
   showing zeros, `unknown`, or omitting it. This is build 88's headline claim
   and no unit test can prove it end to end.

**If the tenant has no codex or agy agent and one cannot be hired, say so and
stop.** ⚠ **Do not synthesise usage records to make the check pass** — a
fabricated input proves the renderer renders, which nobody doubted.

## Report

Per `BUILD-83-acceptance-seat.md`, and keep the two parts separate. **Part 1's
exit code does not stand for part 2.**

⚠ **Be explicit about what part 2 could not reach.** You did this unprompted on
build 89 with `soak.sh` and it was the most useful line in the report.
