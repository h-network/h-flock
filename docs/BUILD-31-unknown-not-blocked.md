# Build 31 — `unknown` is not `blocked`, and does the gap exist?

> Two things, both from [`BUILD-30-FINDINGS`](BUILD-30-FINDINGS.md) §13 and §14.
>
> **Base on `main`.** Branch `bus/build-31-<piece>`, push to origin.

## 1. A delivery to an agent that has never spoken has no verdict

Measured: a freshly started claude agent produces **no session file, no activity
entry and no `activity.offset` for at least 15 s** — nothing exists until it
receives its first input. `VERIFY_AFTER_SECONDS` is 10, so the verdict lands
first and a healthy agent is marked `blocked`.

The rule:

> **Only judge a delivery to an agent that has ever produced activity.** An agent
> with no feed is `unknown`, and a delivery to `unknown` has no verdict.

- the signal is the existence of the agent's activity offset / feed — an
  `HEXISTS`-class read the router already does. ⚠ **No terminal is read.**
- an unjudged marker must not accumulate: drop it, and log the reason
- ⚠ **Do not "wait longer" instead.** A bigger timeout is the same bug with a
  larger constant, and it makes a real block slower to surface. The distinction
  is *can this agent be judged at all*, not *how long shall we give it*
- the cost is deliberate: **the first delivery to a new agent is never judged.**
  Say so in `LLD-bus-and-router`, because it is a real hole and an honest one

⚠ **`blocked` is what clients act on** — `API.md` says so and both clients
implement it. A false `blocked` on a healthy agent tells a user "not accepting
messages" about an agent that is fine, and after build 30 there is no retry
behind it.

## 2. Does the login-prompt gap exist? Test claude

`HLD` §8a and `TODO` both say a CLI at a login prompt records input it never acts
on, so the delivery verifies and `blocked` is missed. With the timing race
removed, **codex at a proved login prompt was caught** — `blocked` set.

The original observation was **claude**, and it has never been tested.

Add a case to `container/sim-blocked.sh` alongside the others: claude in a
credential-free profile, login prompt **proved on screen** before delivering, and
the verdict waited for with `poll_judged`.

⚠ **Assert what happens, not what we expect.** If claude is caught too, the gap
does not exist and `HLD` §8a and `TODO` are both wrong — report that and change
nothing until we have looked at it together.

⚠ **Absence checks are how we got here.** §12: polling `blocked` for 20 s and
calling empty a verdict passes whenever the router is slow. Use `poll_judged`,
which waits for the marker to appear and then to go.

## 3. Done when

- a healthy freshly-started agent is **not** marked `blocked` — `sim-blocked.sh`
  case 2 passes
- the new claude case runs and its result is reported either way
- `bash container/sim-blocked.sh` against the lab with the run **pasted into the
  report**, not unit tests
- `LLD-bus-and-router` records the rule and the first-delivery hole, in the same
  commit — [`TODO`](TODO.md)

## 4. Reporting

`jira done`, then message `architect` with the run, what the claude case did, and
whether §2 leaves the documented gap standing.
