# Build 26 — `office status`

> The lead can see what an agent *took*. It cannot see whether the agent is
> moving. This is that, as a **pull** — nothing is pushed at anyone.
>
> **Base on `main`.** Branch `<lane>/build-26-office-status`, push to origin.

---

# A. The command — `bus`

```bash
office status              # every agent in the office
office status sme-2        # one
```

```
  architect   working   —                                  last activity 4s ago
  sme-2       working   "review the auth change" 14m        last activity 20s ago
  sme-3       idle      —                                   last activity 6m ago
  lab         unknown   —                                   no activity feed
```

## A1. What it reads

| | from |
|---|---|
| state and `since` | `<prefix>:agent:<n>:presence` |
| the open ticket and its age | `tasks.doing`, `started_ts` |
| `blocked` | `<prefix>:agent:<n>:blocked` — **if present** |

⚠ **`blocked` does not exist yet** — the watchdog writes it in the next build.
Read it if it is there and report `blocked` in place of the presence state when
it is, because it is the more consequential fact. **Do not create it, do not
write it, and do not fail without it.**

⚠ **`unknown` is not `idle`.** An agy agent or a bare shell writes no session
file, so nothing can be said. Print *"no activity feed"* rather than a time, or a
reader will take silence for calm.

## A2. Scope and shape

- **tmux agents only**, including yourself. App clients and `host` have no
  windows and no feeds; listing them as `unknown` forever is noise.
- **A read, like `peers`.** No permission check — any agent may run it, the same
  way any agent may already read any board with `office list -a`. `producer` is
  forgeable, so a check would be theatre.
- Unknown agent name → say so and exit non-zero. Do not print an empty table.

⚠ **It reads and never writes.** No marking, no clearing, no side effects. Two
agents running it at once must be indistinguishable from one.

## A3. Done when

- `office status` lists every tmux agent with state, ticket and last activity
- `office status <agent>` prints one row; an unknown name errors
- an agent with no feed reads `unknown` and says why
- an agent mid-task shows its ticket and how long it has been open
- a `blocked` key, if one is planted by hand, is reported in place of the state
- nothing is written to Redis by running it

---

# B. One sentence for the lead — `tmux`

The lead's guide already says *"You are the lead of this office."* Add, in that
same block:

> Before you hand out work, check `office status`. An agent that is `blocked`
> will not receive it — hold the work and say so. Do not try to fix the agent.

⚠ **Only the lead's guide.** The other agents do not route work and do not need
it; every added sentence pushes something out of the part that gets read.

⚠ **Keep the reason in it.** *"An agent that is blocked will not receive it"* is
why, and an LLM follows a rule with a reason far more reliably than a bare
instruction. That is the same lesson as naming the lead rather than describing
one.

⚠ **"Do not try to fix the agent" is the load-bearing half.** An agent told
something is wrong will attempt a repair — restart it, re-send into it, take over
its ticket. Fixing is a human's job, and an agent that hides the symptom by
poking the stalled one makes the problem harder to see, not easier.

## B1. Done when

- the lead's guide carries the sentence; other guides do not
- a fresh office and a hired agent both get the right variant

---

## Reporting

`jira done`, then message `architect` with the exact output format and status.
⚠ These touch no common file — `bus` owns `flock.office`, `tmux` owns the guide.
