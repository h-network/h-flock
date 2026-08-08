# Build 10 — task boards

> Design is [`PLAN-boards.md`](PLAN-boards.md). This is the split, the three
> policy calls, and what done means.
>
> **Base on `main`.** Branch `<lane>/build-10-boards`, push to origin.

## 1. The rule

**The agent moves its own tasks. Nothing infers them.** The adapter knows an
envelope arrived; it cannot know whether the agent read it, started it or
disagreed with it. So the board is written by the agent and read by everything
else, and **the adapter never touches a `tasks.*` key** — except through the
`AssignTask` opener in §3, which puts work *in* and never moves it along.

## 2. `bus` — the agent's surface

Four subcommands of `office`:

```bash
office tasks                        # my board: todo / doing / done
office take                         # todo → doing, FIFO. prints the task
office done                         # doing → done
office assign -a backend -t "one line" -d "the brief"   # → AssignTask, §3
```

Keys are already pinned (`CONTRACTS` §7), already served by the api, and have
never had anything written to them:

```
  <prefix>:tasks.todo     LIST   FIFO — take pulls from the head
  <prefix>:tasks.doing    LIST   at most one
  <prefix>:tasks.done     LIST
```

An entry is a **ticket**:
`{"id", "title", "description", "from", "created_at"}`. `tasks` lists titles;
`take` prints the whole ticket. ⚠ **Both text fields are opaque** — nothing
parses them, not the api, not you.

`take` is an `LMOVE` from `todo` to `doing`, so it is one atomic operation rather
than a read-then-write two agents could tear.

**`take` and `done` emit a log record** — `module: office`, events `task_taken`
and `task_done`, carrying the task `id`. That is the board's activity log; there
is no second place to look. ⚠ We log envelope movements, not Redis activity, so a
board move is invisible unless the tool records it.

⚠ **`take` must say why it came back empty.** "Your todo is empty" and "you
already have one open" are different answers and an agent acts differently on
each. h-office has a commit for exactly this mistake.

## 3. `tmux` — the `AssignTask` opener

`office assign` sends an envelope; it does **not** write the recipient's board.
The opener on the recipient's side does:

| | |
|---|---|
| kind | `AssignTask` |
| payload | `{"title": "…", "description": "…"}` |
| opener | writes the ticket to that agent's `tasks.todo`, and **pastes nothing** |

Only an agent's own side writes its keys.

⚠ **Nothing is pasted.** The first live test had a notification, and the agent
worked straight from the pasted text, running `take` and `done` afterwards as —
its own words — *"bookkeeping only"*. So `doing` was never populated while the
work was happening, which is the one state the watchdog reads. Two sources for
one ticket means the agent uses whichever lands first, and that is always the
paste.

**The board carries *what*; a message carries *now*.** Assign the ticket, then
`office send -a backend ticket waiting on your board` if you want it started
immediately.

## 4. Three policy calls — decided, do not re-open

**One `doing` per agent.** `take` refuses when `doing` is non-empty and says so.
It makes "is this agent busy" a single question, which is what the watchdog
needs, and it stops an agent silently stacking work it will not do.

**A board survives `letGo`.** `StopAgent` clears per-agent *state* and leaves
*data*; a board is data by that line, same as queues. So a re-hired `backend`
inherits the old board. ⚠ Known and accepted — if it turns out to surprise
people, the fix is to widen `StopAgent`, not to special-case boards.

**Anyone may assign to anyone.** No permission check. It would rest on
`producer`, which is forgeable ([`TODO.md`](TODO.md)), so a check here would be
theatre.

## 5. Done when

- `office assign -a backend -t "…" -d "…"` puts the ticket on backend's `todo`
  and **pastes nothing** into its window
- `office take` in backend's window moves it to `doing` and prints it
- `office take` again refuses, and says it is because one is already open
- `office done` moves it to `done`
- `GET /board` returns all three lists populated — it has served empty since
  build 03
- `take` and `done` appear in the container log with the task `id`
- a second `take` on an empty `todo` says *why*, not just nothing

## 6. Reporting

`jira done`, then message `architect` with paths, the subcommand list, and status.

⚠ Do not edit another lane's files. `bus` owns `flock.office`; `tmux` owns the
adapter's openers.
