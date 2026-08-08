# Plan — the jira board

> Rewritten after reading h-office's `task.py` and `jira.py` properly. It is a
> Jira board: **tickets** an agent works through. Take their model; change only
> what h-flock forces.

## 1. It is a ticket board, not a message queue

Two separate namespaces on the same Redis, and conflating them is the mistake to
avoid:

| | carries | how it moves |
|---|---|---|
| **the bus** | messages between agents | pushed — the router forwards, the adapter delivers |
| **the board** | tickets: things to build or track | **pulled** — a ticket waits until the agent asks |

h-office's own words: *"Pull-based, so — unlike the message bus — there's no
courier: tasks just wait on the list until the agent asks for one."*

⚠ **So nothing notifies an agent that a ticket arrived.** No paste, no envelope
into its window. If you want it started now, add the ticket and then **send it a
message** — that is a message, and messages are what the bus is for. The board
carries *what*; a message carries *now*.

The first live test proved why: with a notification, the agent worked from the
pasted text and ran take/done afterwards as, in its own words, *"bookkeeping
only"* — so `doing` was never populated while the work was happening, which is
the one state the watchdog reads.

## 2. The ticket

h-office's shape, plus one field:

```json
{ "v": 1,
  "id": "<hex>",
  "title": "one line naming the deliverable",
  "description": "the brief — as long as it needs to be",
  "created_by": "architect",
  "status": "todo" | "doing" | "done",
  "created_ts": "…",
  "started_ts": "…",     set by take
  "done_ts": "…",        set by done
  "priority": "…"        optional
}
```

⚠ **`description` is ours, and it is a deliberate difference.** h-office keeps
the ticket to a title pointing at a spec file, because *"ticket text is echoed
back by `jira list` and the dashboard every time anyone looks"*. Here the brief
lives in the ticket — so `list` must print **titles only**, and `take` prints the
whole thing. Their reason still applies; only the storage moves.

⚠ **A ticket is structured data, not an opaque blob.** `CONTRACTS` §7 said the
api must not parse board entries — that was written when nothing wrote them, and
it is wrong for a ticket board. `status` and `started_ts` are fields the board's
own tooling reads. What stays opaque is `title` and `description`: *text*
nothing interprets.

## 3. The columns and the states

Four columns. A column is a Redis LIST, so **which list a ticket is in is its
state** — there is no separate index to keep in step.

```
  <prefix>:tasks.todo    waiting      RPUSH to add   ← LPOP to take (FIFO)
  <prefix>:tasks.doing   being worked
  <prefix>:tasks.hold    parked deliberately
  <prefix>:tasks.done    finished     status: done | cancelled
```

`done` and `cancelled` share a column because "finished with" is one place on a
board even when the reason differs — the `status` field carries which.

**Actions**

| | |
|---|---|
| `add` | RPUSH onto `todo` |
| `take` | `LPOP` todo → `RPUSH` doing, stamps `started_ts` |
| `done` | `LREM` from doing → `RPUSH` done, `status: done`, stamps `done_ts` |
| `cancel` | same, `status: cancelled` — the ticket is finished with, not deleted |
| `hold` / `resume` | between `doing` and `hold` |
| `delete` | **removes the ticket.** A real deletion, not a label |

`take` needs no locking — h-office's note: *"One agent (the assignee) consumes
its own column, so the LPOP+RPUSH pair needs no locking."*

⚠ `delete` is destructive and there is no `deleted` state. If you want the
history kept, `cancel` is the one to use — that is the whole difference between
them.

## 4. Commands

h-office's verbs. They exist, they work, and the office already types them — only
the `office` prefix differs, forced by `sendMessage` colliding with Claude Code's
built-in tool and `TaskList`/`TaskGet` colliding next.

```bash
office add -a backend -t "one line" -d "the brief" [-p high]
office take                       # todo → doing, prints the ticket
office done [<id>]                # doing → done; id optional if exactly one
office list [-a <agent>|--all]    # titles only
```

⚠ **`add`, never `assign`.** `assign` presupposes a ticket that already exists
and only changes owner; this creates one on a board. It is also ambiguous about
which it means.

⚠ `done` takes an **optional id or prefix**, and is unambiguous when exactly one
ticket is in doing. Copied from h-office because it is the ergonomics that make
it usable by hand.

⚠ `take` must say **why** it came back empty — "your todo is empty" and "you
already have one open" are different answers.

## 5. Events go to a file, not stdout

h-office writes an append-only JSONL of task events — `$TASK_RECORD`,
*"mirrors the bus's `messages.jsonl`"* — recording `add`, `consume` and `done`
with the task id, title and creator.

⚠ **This is the fix for a real problem we hit.** `office` runs inside an agent's
window, so anything it prints to stdout lands in that pane and is never
collected. A file on the container filesystem is written by whoever runs the
command and read by anything that wants the history. Same reason h-office chose
it.

`record_event` never raises: *"logging must not break a command."*

## 6. What the watchdog reads

Already written in h-office, and the reason boards come first:

- `doing_tasks` — what an agent says it is working on
- `oldest_doing_age` — how long the longest has been open, from `started_ts`
- `stalled_tasks(stall_sec)` — *"the agent took work and hasn't marked it done
  — i.e. it may be stuck"*

Combined with window silence, which is the half that stops it crying wolf.

## 7. Everything goes through the bus

**Decided.** `office add -a backend …` sends an **`AddTicket`** envelope; the
opener on backend's side writes it to backend's own `tasks.todo`. It does not
write another agent's keys directly, which is what h-office does.

This generalises invariant 3 from queues to every per-agent key: **nothing writes
another agent's keys — it sends an envelope.** And it pays for itself three ways:

- the four log records every envelope already gets, so "who added what, when" is
  answerable from the log rather than only the task JSONL
- it works from the api and an app unchanged — `POST /agents/backend/envelopes`
  with `kind: AddTicket` is adding a ticket, no new endpoint
- one route for the operation instead of two that can diverge

⚠ **The kind is `AddTicket`, not `AssignTask`** — renamed for the same reason the
command is `add`: nothing is being assigned, a ticket is being created on a
board.

## 8. One ticket in `doing`

**It falls out of §1 rather than being a rule we impose.** Nothing delivers a
ticket — the agent knows its board and grabs work when it is ready. So it only
ever holds what it pulled, and it pulls the next one when it has finished the
last. `take` refusing while one is open is that made explicit, not a policy on
top of it.

Which is also why the board needs no delivery machinery at all: no courier, no
kick, no adapter, no opener on the receiving side. The agent is the mechanism.

Practically it makes "is this agent busy" a single yes/no, which is what the
watchdog reads.

⚠ Differs from h-office, which allows several — `doing_tasks` returns a list and
`stalled_tasks` can report more than one. Ours is the narrower rule; if a ticket
must be set aside, that is what `hold` is for.
