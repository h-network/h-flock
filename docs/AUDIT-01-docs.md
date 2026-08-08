# Audit 01 — the docs against the code

> Eleven builds in, and the docs were written *ahead* of most of them. Some
> describe a design that changed, some a build that was reverted, some a rule
> that has since been corrected. Find those.
>
> **Base on `main`** (`3ecf93e`). Branch `<lane>/audit-01-docs`, push to origin.

## 1. What you are looking for

In order of how much they matter:

1. **Wrong** — the doc says the code does X, the code does Y. `CONTRACTS` §8 said
   the api must not parse board entries while the api was parsing them.
2. **Stale** — describes something that no longer exists, or a count that has
   moved on. `three LISTs` when there are four; `AGENT_PEERS`, which was removed;
   `sendMessage`/`peers` as separate commands, which build 09 folded into
   `office`.
3. **Inconsistent** — two docs disagree, or one contradicts itself. These are the
   expensive ones, because both readers think they are right.
4. **Missing** — a rule everything depends on that is written down nowhere.

⚠ **Verify against the code, not against your memory of building it.** Open the
file. Several of these lanes built a thing, then had it changed underneath by
another lane's merge.

## 2. Who audits what

Lane-owned. **Fix your own files; report everything else** — three lanes editing
one doc is how a merge conflict eats an afternoon.

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `LLD-container.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

**Nobody edits these — report findings in them to `architect`:**

`CONTRACTS.md` (everyone depends on it, so it changes once, deliberately),
`README.md`, `PLAN-boards.md`, `TODO.md`, `SPRINTS-next.md`, and all `BUILD-*.md`.

⚠ **`BUILD-*.md` are history, not reference.** They record what was asked for and
why at the time. A build doc that no longer matches the code is not a bug — it is
a record. Do not rewrite them. If one is actively misleading, say so and I will
add a superseded banner, as `BUILD-10` already has. There is no `BUILD-07`; that
build was reversed, and the gap is deliberate.

## 3. Rules

⚠ **A docs audit does not change code.** If a doc and the code disagree and you
think the *code* is wrong, that is a finding, not a fix. Say so and stop. The
whole value of this pass is that it is safe to run everywhere at once, and that
holds only while nothing under `src/` moves.

⚠ **Keep the rationale.** These docs say *why* a decision went the way it went,
and that is the thing worth having — it is what stopped us re-deriving the same
answers. Correcting a fact must not flatten a paragraph into a reference entry.
If a rationale is now wrong, the reason it was wrong is usually worth a line.

⚠ **Do not add new design.** If you find a real gap, write it as a finding.
Filling it in yourself means a decision gets made in a file nobody reviewed.

Match the surrounding voice — plain sentences, `⚠` for the things that bite,
tables where a table genuinely reads better.

## 4. Known-good anchors

Current as of `3ecf93e`, so if a doc disagrees with these, the doc is wrong:

- one `office` command; `sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`
  are **not** separate binaries (build 09)
- board verbs: `add`, `list`, `take`, `done`, `cancel`, `hold`, `delete`
- four board columns: `todo`, `doing`, `hold`, `done`; terminal `status` is
  `done` or `cancelled`
- the kind is `AddTicket`; `AssignTask` survives only as a logged deprecated alias
- boards are **pulled** — adding a ticket notifies nobody, and pastes nothing
- `record_task_event` lives in `flock.bus` and is the only writer of `$TASK_RECORD`
- `AGENT_PEERS` does not exist
- adapters are **kicked per delivery** and exit; they are not daemons
- `flock.bus` and `flock.tmux` are the only shared libraries

## 5. Reporting

This is the deliverable, more than the edits. Message `architect` with:

- **what you fixed**, one line each, file and section
- **what you found in files you do not own**, same form — these are mine to apply
- **what you were unsure about** — a doc that reads oddly but might be right is
  worth a line; I would rather see it than not

`jira done` after the push.
