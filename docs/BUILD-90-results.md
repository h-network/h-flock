# Build 90 — acceptance after build 88, in two parts

**Two verdicts, deliberately not one.** `main` at `e3504c9` (build 88 at
`633b4c4`), `h-lab@172.16.0.14`, base image
`ghcr.io/h-network/base@sha256:10406097c895…` — unchanged across builds 86, 89
and 90, so three runs share a host and an image and the deltas are code.

## Part 1 — regression: `EXIT:0`

26/26 plumbing, 19/19 simulator, 4/4 console flows, nothing skipped, zero matches
for `error|usage:|unrecognized|argparse|traceback` across the whole log. Build 88
broke nothing the harness already covered.

## Part 2 — what the harness cannot reach

⚠ **Neither `container/accept.sh` nor `container/plumbing-check.sh` invokes
`office status` or `office usage` anywhere.** Part 1 exercised **none** of build
88. Everything below was run by hand against the kept tenant, and **part 1's exit
code does not stand for any of it.**

**Build 88's headline claim holds under a real hired agy agent** — `office hire
agy-check --cli agy`, not a synthesised record:

| surface | agy row |
|---|---|
| `office status` activity | `not measurable (agy)` |
| `office usage` | `model=not measurable`, every count `-`, `unpriced` |
| `office usage --json` | carries `"measurable": false`, which claude rows do not |

Not zeros, not `unknown`, not omitted. That is the property the build claimed and
it is now proven end to end rather than by unit test.

## ⚠ Two things this run could NOT establish

**Rate limits are unverified live.** `office usage --json` carried **no
`rate_limits` key on any row** — correctly, because the tenant had no codex
agent. Build 88 surfaces them from codex `token_count` records, so that half of
the build has passed unit tests against the captured fixture and **has never been
seen working on a live tenant.**

**The codex extraction path is untouched.** The ticket named agy specifically and
the seat kept to that scope, then said so rather than letting part 2's success
imply coverage it did not have.

## ⚠ A new observation, not a build-88 defect

`office status` shows the agy agent as `unknown` in the **status** column while
the **activity** column correctly reads `not measurable (agy)`.

That is the same word doing two jobs one column apart: *"we cannot determine
this"* and *"we know, permanently, that this cannot be measured."* Build 88 fixed
exactly that confusion in the activity column. Whether presence is genuinely
underivable for agy — a pane exists either way — is not answered here. **Recorded
as an open question, not a verdict**, which is how the seat reported it.

## Method

Third consecutive run where the seat named what it could not reach without being
asked: `soak.sh` in build 89, and here both the missing codex agent and the
status-column wording. It also owned teardown under `--keep` and returned the
host to exactly 39 running / 41 total / 8 networks.
