# Audit 06 — the docs against builds 30 and 31

> Rules unchanged: [`AUDIT-01`](AUDIT-01-docs.md) §1 and §3, [`AUDIT-02`](AUDIT-02-docs.md) §5
> (hunt absolute claims), re-measure at the end ([`AUDIT-04`](AUDIT-04-docs.md) §5).
>
> **Base on `main`.** Branch `<lane>/audit-06-docs`, push to origin.

## 1. The gap, measured

```
                        unjudged  first-delivery  login-gap  rebuild  no-retry
  HLD.md                       0               0          2        0         0
  CONTRACTS.md                 0               0          1        0         0
  README.md                    0               0          0        1         0
  API.md                       0               0          1        0         0
  LLD-bus-and-router.md        1               1          1        0         1
  LLD-container.md             0               0          0        1         0
  LLD-adapter-tmux.md          0               0          1        0         0
  LLD-watchdog.md              0               1          0        0         0
  TODO.md                      0               0          3        1         0
```

`LLD-bus-and-router` is the only file that knows any of this, because `bus`
closed its own entries in the build that made them true. That is the rule
working — everything else is a file whose owner has not been told.

## 2. This round is different: a claim to *remove*

⚠ **The login-prompt gap does not exist, and five files say it does.**

Measured on the lab, preconditions proved on screen, verdict waited for
deterministically ([`BUILD-30-FINDINGS`](BUILD-30-FINDINGS.md) §16):

| | |
|---|---|
| codex at a login prompt | `blocked` **set** — caught |
| claude at a login prompt | `blocked` **set** — caught |

The belief came from an absence check that passed whenever the router was slow
(§12). It was never a property of the system.

⚠ **Delete the claim; do not soften it.** "May sometimes miss" is the same
sentence with a hedge, and it keeps a phantom in the architecture. If your file
says a CLI records input it never acts on and therefore verification passes, that
sentence goes.

⚠ **What replaces it is narrower and true:** a delivery is judged only for an
agent that has produced activity before. An agent that has never spoken is
`unknown`, and its delivery is **unjudged** — neither verified nor blocked.

## 3. What landed

- **no automatic retry on `delivery_unverified`** — verification cannot tell an
  unsubmitted paste from text that landed in a wedged CLI, so a retry either
  cannot help or duplicates. The trade chosen is possible loss over possible
  duplication, surfaced to a human
- **`delivery_unjudged`** — a new lifecycle record. The first delivery to an
  agent with no activity history is dropped without a verdict
- **`blocked` is surfaced by the api** — `GET /agents/<n>` folds it into
  `presence.state`. It never did before, so every client's `blocked` branch was
  dead code
- **`container/sim-blocked.sh`** — four cases, each proving its own setup, run
  from `plumbing-check.sh` §12

## 4. Two things `API.md` must tell a developer — mine

⚠ A brand-new agent **will never report `blocked`**, however wedged it is,
until it has spoken once. A client that waits for `blocked` to decide an agent is
unreachable will wait forever on a new one.

⚠ There is **no retry**. A delivery that goes unverified is not resent by the
framework, so a client that needs delivery guarantees must handle that itself.

## 5. Who audits what

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md` (re-check only), `LLD-watchdog.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-container.md`, `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

`HLD`, `README`, `CONTRACTS`, `API.md`, `TODO` are mine.

⚠ **`tmux`: `LLD-container` must gain the rebuild rule.** Rebuilding a tenant to
test a branch **restarted the office and destroyed every runtime enrolment** —
the `networking` agent, and the `telegram` and `web` clients, which kept running
against a tenant that no longer knew them. To a chat user that looks like the bot
going quiet, with no error anywhere. A rebuild is not a restart of the same
office; it is a new office wearing the same name.

⚠ **And a rule with it: do not rebuild a tenant someone is using.** Bring up a
second one.

## 6. Reporting

What you fixed, what you found in files you do not own, what you checked and
found correct, **and the re-measured §1 table**.

## 7. Closed — the re-measured table

```
                        unjudged  first-delivery  rebuild  no-retry
  HLD.md                       2               1        0         0
  CONTRACTS.md                 1               0        0         0
  README.md                    0               1        1         0
  API.md                       0               0        0         2
  LLD-bus-and-router.md        1               1        0         1
  LLD-container.md             0               0        4         0
  LLD-adapter-tmux.md          1               1        0         0
  LLD-watchdog.md              2               2        0         0
  LLD-api.md                   2               1        0         0
  TODO.md                      0               0        1         0
```

⚠ **The `login-gap` column is gone from the table on purpose.** Counting the
phrase "login prompt" is useless now that the true statement contains it — the
files should say a login prompt *is* caught. Searching for the **claim** instead
(`records input it .* acts on`, `misses a CLI`) returns nothing outside this
file, [`BUILD-30-FINDINGS`](BUILD-30-FINDINGS.md), and two deliberate retractions
in `HLD` §8a and `TODO`.

⚠ **A mention count cannot audit a deletion.** Both `README` and `LLD-adapter-tmux`
scored zero for `login-gap` while still carrying the claim, because it was phrased
without the words being counted — `README` said it in the watchdog paragraph and I
missed it in my own first pass. Grep for the assertion, not the topic.

**Deliberate zeros:** `LLD-tmux-host` and `LLD-session` have nothing to do with
verdicts. `CONTRACTS` at zero for `first-delivery` is correct — it pins keys, and
the hole is behaviour, described where the rule lives.

## 8. Cross-lane findings, again measured at the branch point

`bus` reported `HLD`, `CONTRACTS`, `TODO`, `LLD-adapter-tmux` and `API.md` as
still carrying the claim. All were fixed before it looked — the same
parallel-branch effect recorded in [`AUDIT-05`](AUDIT-05-docs.md) §7. Its own
files were correct.

⚠ **Two audits running, same surprise.** Worth building into the next one: state
the base commit each lane measured from, so a stale finding is visible as stale
rather than argued about.
