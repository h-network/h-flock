# Plan — task boards

> Proposal. Nothing built. The prerequisite for the watchdog.

## 1. The one rule everything else follows from

**The agent moves its own tasks. Nothing infers them.**

The adapter knows an envelope was delivered. It does not know whether the agent
read it, agreed with it, started it, finished it, or decided it was a bad idea.
A framework that guesses is worse than one that admits it does not know, because
the guess looks like data.

So the board is **written by the agent** and **read by everything else**:

| | |
|---|---|
| the agent | `office take`, `office done` — moves its own tasks |
| the api | reads. `GET /board` already exists |
| the watchdog | reads. A task in `doing` is its only evidence anything is underway |
| the adapter | **never touches it** |

That is what makes the board worth having: it is the one place an agent states
what it is doing, rather than somewhere we record what we did to it.

## 2. Shape

Already pinned in `CONTRACTS` §7 and served by the api since build 03 — three
LISTs per agent, nothing writing them:

```
  <prefix>:tasks.todo     LIST   FIFO — take pulls from the head
  <prefix>:tasks.doing    LIST   at most one entry
  <prefix>:tasks.done     LIST
```

Three keys rather than one hash, because a board is ordered ("take your next
task" is only meaningful against a FIFO) and because a state change is then an
`LMOVE` between two keys rather than a read-modify-write of one value — which is
what stops two readers tearing a board in half.

An entry is a small JSON object:

```json
{ "id": "<hex>", "title": "…", "from": "architect",
  "created_at": "…", "started_at": "…" }
```

⚠ **`title` is opaque and stays opaque.** `LLD-bus-and-router` §8 is explicit that
this is not a task system, and `CONTRACTS` §7 says the api must not parse
entries. Neither changes. What moves, deliberately and by one field, is that
**the watchdog reads `started_at`** — it cannot answer "how long has this been
open" otherwise. Everything else about a task stays the agent's business.

## 3. Assignment travels as an envelope

`office assign -a backend "review the auth change"` does **not** write backend's
board. It sends an `AssignTask` envelope, and the opener on backend's side writes
it.

Three reasons, and the third is the one that matters:

- Only an agent's own side writes its keys, which is the rule everywhere else.
- Assignment gets the four log records every other envelope gets, so "who
  assigned what, when" is answerable from the log we already have.
- **It works from the api and the app for free.** `POST /agents/backend/envelopes`
  with `kind: AssignTask` is assignment, with no new endpoint and no new
  mechanism — exactly as `hire` turned out.

The opener writes the entry to `tasks.todo` **and pastes a notification** into
the window, so an agent learns it has work the same way it learns anything else.

## 4. The agent's surface

Subcommands of `office`, which is what that namespace was for — and it dodges
`TaskList` / `TaskGet`, the other collision the agent's own tool list showed us:

```bash
office tasks                       # my board: todo / doing / done
office take                        # todo → doing, FIFO, prints the task
office done                        # doing → done
office assign -a backend some text # → AssignTask envelope
```

⚠ `office take` with an empty `todo` must say **why** it came back empty — h-office
has a commit for exactly this (*"jira: say why consume came back empty"*). "No
tasks" and "you already have one open" are different answers and an agent will
act differently on each.

## 5. What this unblocks

The watchdog's signal is **stalled task AND silent window** — and h-office's
comment says why neither half works alone:

> A stalled task only alerts if the agent's window has ALSO been quiet this
> long — a long build keeps printing, a wedged agent does not.

On elapsed time alone it fired identically for a 15-minute rebuild and a wedged
agent, so the lead learned to dismiss it and then dismissed a real one. Without
boards the watchdog has only the half that cries wolf.

It also gives `GET /board` something to return — the api has served it since
build 03 and it has always been empty.

## 6. Open

**Does an agent have exactly one `doing`?** h-office assumes so. It makes "is
this agent busy" a single question, and it makes `take` refuse rather than
silently stack work. Recommended, but it is a rule about how agents work, not a
technical constraint.

**What happens to a board on `letGo`?** `StopAgent` clears per-agent *state* and
leaves *data*. A board is data by that line — so it survives, and a re-hired
`backend` inherits the old one. Arguably right, arguably a surprise. Same
question we deferred for queues.

**Who may assign to whom?** Anyone, today. The lead being positional (first
agent) makes "only the lead assigns" expressible, and it rests on `producer`,
which is forgeable — see [`TODO.md`](TODO.md). Worth leaving open rather than
half-enforcing.
