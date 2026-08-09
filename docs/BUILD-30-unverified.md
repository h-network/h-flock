# Build 30 — the unverified path, and a harness that can prove it

> Everything we know about `blocked` was measured by hand on a live tenant. This
> build makes those cases reproducible, then acts on the verdict.
>
> **Base on `main`.** Branch `<lane>/build-30-<piece>`, push to origin.

## 1. Why the harness comes first

⚠ **`plumbing-check.sh` has no simulation for `blocked` at all** — no SIGSTOP,
no picker, nothing. Twenty-five checks and not one of them drives a delivery into
the state the whole verification machinery exists for.

So every claim in `HLD` §8a is true because I watched it happen once. That is not
a test, and it is why this file starts with the simulator rather than the retry.

## 2. `tmux` — the failure simulator

`container/sim-blocked.sh`, or a module if that reads better — say which and why.
Three cases, each driving one agent into one state and leaving it there:

| case | how | what should follow |
|---|---|---|
| **wedged process** | `SIGSTOP` the CLI | delivery unverified, `blocked` set |
| **trust picker** | start claude with trust unseeded | delivery unverified, `blocked` set |
| **login prompt** | start a CLI with no credential | ⚠ **verify passes, `blocked` is not set** |

⚠ **The third case is expected to fail, and it must be written as a passing test
of a known gap** — not as a broken test, and not left out because it is
inconvenient. A CLI records the input at a login prompt without acting on it, so
the marker is consumed and the verdict is `verified` while the agent is deaf.
Name it for what it is and assert the current behaviour.

⚠ **Resume the process.** `SIGCONT` in the teardown, and check the window is
gone afterwards by **polling for the condition, never sleeping a fixed time** —
three flakes in this repo came from sleeping.

## 3. `bus` — retry on `delivery_unverified`

Today the router logs the verdict, sets `blocked`, and stops. The envelope is
gone.

Decide and implement a retry, and ⚠ **write the reasoning into
`LLD-bus-and-router` in the same commit** — [`TODO`](TODO.md) says a build closes
its own entry, and this is that build.

The constraints that actually bind:

- **at most one re-paste**, and only if nothing was consumed since. A loop that
  re-pastes into a wedged CLI writes the same text forever and fills the window
- **never re-paste into a `blocked` agent that a human has not cleared** — the
  second paste lands in the same picker as the first
- **the ceiling is ~2 deliveries/second/agent** (`CONTRACTS` §2). A retry storm
  is a per-agent stall, not a tenant one, but it still delays real work
- ⚠ **an envelope must not be delivered twice.** If the first paste actually
  landed and only the *verification* failed, a retry duplicates it. Say which
  risk you chose — a possible duplicate or a possible loss — and why

⚠ **If the honest answer is "do not retry, surface it instead", that is a valid
outcome of this build.** Say so with the numbers, and build the surfacing.

## 4. Done when

- all three cases in §2 run from a script and leave the tenant clean
- the login-prompt case asserts the **gap**, and its name says so
- whatever §3 decides is implemented, tested, and reasoned about in the LLD
- `plumbing-check.sh` covers the new cases
- unit tests green, and the plumbing run recorded

## 5. Reporting

`jira done`, then message `architect` with the paths, what §3 decided and the
trade it chose, and the plumbing count.
