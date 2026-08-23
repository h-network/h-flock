# Build 94 — acceptance after build 91, in two parts

**Part 1: `EXIT:0`.** `main` at `3cb8425` (build 91 at `bd706a6`), `h-lab`, base
image `…10406097c895` — unchanged across builds 86, 89, 90 and 94.

26/26 plumbing, 19/19 simulator, 4/4 console flows, nothing skipped, teardown
clean, host returned to 39 running / 41 total / 8 networks.

⚠ **Port 8099 was taken by an unrelated process on the shared host**, so the run
used `--console-port 8199` after confirming it free. Recorded because the default
being occupied is a property of the lab, not of h-flock.

## Part 2 — what a real run actually exercises

⚠ **Part 1's exit code does not stand for any of this.** The control path *runs*
during acceptance; **nothing asserts what it emitted.** All of the below came
from the custody log of a kept tenant — 284 lines from part 1 alone.

The records are shaped as claimed: `destination` (not `agent`) plus a
`correlation_id`.

| control kind | occurrences in a full acceptance run |
|---|---|
| `start_agent_accepted` | **11** — eleven distinct destinations, not just the one `StartAgent` the spec named |
| `stop_agent_accepted` | **15** — ⚠ **reached, contrary to the spec's framing.** Console tab-close/retire and the simulator's state restoration both trigger it |
| `pause_agent_*`, `resume_agent_*` | **ZERO. Never exercised by anything** — not `accept.sh`, not `plumbing-check.sh`, not `flow-check.py` |
| any `*_incomplete` or `*_failed` | **ZERO** |

⚠⚠ **Only the SUCCESS shape has ever run on a live tenant.** Build 91 spent five
refusals getting `_incomplete` and `_failed` right, and **neither has been
exercised outside a unit test.** That is a formal statement of what is
unverified, not a guess that they probably work.

## The refused hire behaved better than specified

```
office hire: error: unknown account 'does-not-exist-account'; available accounts: default
```

Exit 2, **client-side**, naming the account that exists. The custody log was
**284 lines before and after** with no trace of the attempt — so the refusal
happened *before any envelope was sent*. The spec allowed either outcome and
asked which; this is the answer, and it is the better one: nothing entered the
fabric to be dead-lettered.

## ⚠ The reconciliation gap is 4.091 seconds, and `tmuxhost` already reports it

```
20:18:09.197  control    start_agent_accepted   destination: windowtiming
20:18:13.288  tmuxhost   window_created         destination: windowtiming
```

⚠ **This changes the open row about `tmuxhost` emitting the control
confirmation.** That row assumed a new emission path was needed. It is not —
`src/flock/tmuxhost/host.py:116` and `src/flock/tmuxhost/host.py:150` **already
emit `window_created`**. What is missing is only that it carries no
`correlation_id`, so it cannot be *joined* to the `_accepted` record that caused
it.

**The row shrinks from "build a confirmation path" to "thread the correlation_id
through so the two records join."**

## Method

Fourth consecutive run naming what it could not reach, unprompted. The coverage
table above is worth more than the exit code: it converts *"we think pause and
resume work"* into *"nothing has ever run them."*
