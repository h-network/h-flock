# Build 11 — the board, re-cut

> Build 10 shipped a working board with the wrong shape. Design is now
> [`PLAN-boards.md`](PLAN-boards.md), settled. This is the delta from what is on
> `main` — read the plan first; this file only says what changes.
>
> **Base on `main`.** Branch `<lane>/build-11-boards-recut`, push to origin.

⚠ [`BUILD-10-boards.md`](BUILD-10-boards.md) is **superseded**. Where the two
disagree, this one and the plan win.

## 1. Why it is a re-cut and not an extension

Build 10 was built from a sketch of a board. The plan was then written against
h-office's `task.py`, which is a board that has been in daily use — and the
verbs, the ticket and the event log all came out different. The names are on
`PATH` and typed by agents, so changing them later costs more than changing them
now, while the only user of the board is us.

## 2. Verbs — `bus`

| on `main` | becomes | why |
|---|---|---|
| `office assign -a X -t "…" -d "…"` | `office add -a X -t "…" -d "…" [-p high]` | `assign` presupposes an existing ticket and only changes owner; this creates one |
| `office tasks` | `office list [-a <agent>\|--all]` | h-office's verb; `tasks` also collides with Claude Code's `TaskList`/`TaskGet` |
| `office done` | `office done [<id>]` | id optional, unambiguous when one is open |
| — | `office cancel [<id>]` | finished with, reason recorded |
| — | `office hold [<id>]` | doing → hold |
| — | `office take [<id>]` | with an id, pulls a specific ticket **including one on hold** |
| — | `office delete <id>` | removes it. Requires an id, always |

⚠ **`take <id>` is how a held ticket comes back** — deliberately, rather than an
`unhold` verb. `office resume` already means *resume a paused agent*, and one
word meaning two things in one CLI is how the `assign` mistake happened. If you
find `take <id>` reads wrong in practice, say so before inventing a third verb.

⚠ **`delete` never takes the "obvious one".** `done` and `cancel` may default to
the single open ticket; a destructive verb may not. No id, no deletion.

⚠ **`list` prints titles only** — meaning *not the description*. Printing
`<id>  <title>` is right and necessary, since the id verbs need an id to name.
Use a short prefix and accept a prefix wherever an id is taken, as h-office does.
What §2 of the plan is protecting against is the brief being echoed back every
time anyone looks; the id is four characters.

## 3. The ticket — `bus`

On `main`: `{"id", "title", "from", "created_at"}`. Becomes the plan §2 shape:

```json
{ "v": 1, "id": "<hex>", "title": "…", "description": "…",
  "created_by": "architect", "status": "todo|doing|hold|done|cancelled",
  "created_ts": "…", "started_ts": "…", "done_ts": "…", "priority": "…" }
```

`from` → `created_by`, `created_at` → `created_ts`, and `v`, `status`,
`started_ts`, `done_ts`, `priority` are new. **Read tolerantly**: a ticket
missing `status` or carrying the old field names must still list and still take —
there are live boards on the lab host.

## 4. Columns — `bus`

A fourth: `<prefix>:tasks.hold`. `todo` / `doing` / `done` keep their keys and
their contents.

`doing` holds **at most one** — already true on `main`, and plan §8 says why it
falls out rather than being enforced. Keep the refusal, keep the reason in the
message.

## 5. The kind — `bus` and `tmux`

`AssignTask` → **`AddTicket`**, payload `{"title", "description", "priority"}`.
Same shape of opener: it writes the ticket to the recipient's `tasks.todo` and
**pastes nothing**.

⚠ Accept `AssignTask` as an alias for one build so anything in flight still
lands, and log it as deprecated. Remove it in the build after.

## 6. Events go to a file — `bus`

On `main`, `take` and `done` call `log_record`, which writes to **stdout — and
`office` runs inside an agent's window**, so those records land in a pane and are
never collected. That is the bug plan §5 exists to fix.

Append JSONL to `$TASK_RECORD` (default `/home/ubuntu/.flock/tasks.jsonl`): one
object per `add` / `take` / `done` / `cancel` / `hold` / `delete`, with the id,
title, agent, actor and timestamp. The action goes in a field named **`event`**,
the same word `log_record` uses — one vocabulary across both logs.

**Each mutation is recorded by whoever performs it**, and that settles where the
`add` line comes from: `office add` does not write one, the **`AddTicket` opener
does**, at the moment the ticket lands on the board. It has the id, because it
minted it.

⚠ **`office add` therefore does not mint or learn the ticket id, and the payload
stays pinned at `{title, description, priority}`.** It returns a `stream_id` like
every other send — build 09 §3 made that the rule for `hire`, and an added ticket
is the same kind of thing: fire-and-forget, with "did it land" answered by
`office list` or the log.

The alternative — minting the id at the sender — writes an `add` line for a
ticket that may dead-letter on a missing window, which puts a ticket in the
history that never existed. A record of board mutations has to be written where
the board is mutated.

⚠ **Recording must never break a command.** Wrap it; swallow everything. An
unwritable log is not a reason a `done` fails.

Keep the `log_record` calls as well — they are how an envelope-side view stays
whole. The file is the board's history; the log is the bus's.

## 6b. `GET /board` — `api`

A fourth list, `hold`, alongside `todo` / `doing` / `done`.

⚠ **Build against the key, not against `bus` landing it.** `tasks.hold` will read
empty until build 11 lands on the `bus` side, and that is fine — `/board` has
served empty lists since build 03. An empty list and a missing key are the same
answer here.

⚠ **Reading a ticket's `status` is now allowed** and `CONTRACTS` §7 needs the
same correction the plan §2 makes: that clause was written when nothing wrote
board entries. `status`, `started_ts` and the id are structured fields. `title`
and `description` stay opaque — do not parse, summarise or truncate them.

Old-shaped entries from build 10 must still serialise. Do not fail a whole
`/board` response on one unparseable entry; skip it and carry on.

## 6c. The guide must mention the board — `tmux`

`generate_agents_md` in `src/flock/tmux/ops.py` tells an agent about `peers` and
`send` and nothing else. **The whole pull model rests on the agent knowing it has
a board** — nothing will ever tell it, by design (plan §1), so if the guide is
silent the board is invisible and tickets sit in `todo` forever.

Add a paragraph. Suggested wording, adjust if it reads badly in place:

> You have a task board. Nothing will notify you about it — check it yourself:
>
>     office list        titles waiting for you
>     office take        take the next one, and it prints in full
>     office done        when it is finished
>
> Take a ticket *before* you start work, not after. `doing` is how the office
> knows what you are on.

⚠ **That last line is the point of the paragraph.** The first live test had an
agent do the work and then run take/done as, in its own words, *"bookkeeping
only"* — so `doing` was empty for the entire time the work was happening, which
is the one state the watchdog reads.

Every window gets the guide, so this reaches existing agents on their next
`create_window` and new ones immediately.

## 7. Done when

- `office add -a backend -t "…" -d "…"` puts a plan-§2-shaped ticket on
  backend's `todo` and pastes nothing
- `office list` prints titles only; `office take` prints the whole ticket
- `office take` a second time refuses and says it is because one is open
- `office hold` then `office take <id>` returns that ticket to `doing`
- `office cancel` lands it in `done` with `status: cancelled`
- `office delete` with no id refuses
- a build-10-shaped ticket already on a board still lists and still takes
- `$TASK_RECORD` has one line per action; no board output appears in a pane
- `GET /board` returns four lists, `hold` included and empty until `bus` lands
- none of `assign`, `tasks` remain on `PATH`
- a freshly hired agent's `AGENTS.md` and `CLAUDE.md` both mention the board

## 8. Reporting

`jira done`, then message `architect` with paths, the final verb list, and status.

⚠ Do not edit another lane's files. `bus` owns `flock.office`; `tmux` owns the
opener.
