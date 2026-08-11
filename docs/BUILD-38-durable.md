# Build 38 — things that must survive, and an alert you can clear

> Four defects with one shape: **a fact is recorded once, in a volatile place,
> and never revised.** All four were found by an operator using the product for
> an afternoon, not by a test.
>
> **Base on `main`.** Branch `<lane>/build-38-<piece>`, push to origin.

## 1. An alert you can clear — `api`

⚠ **Clear one alert. Do not mute a kind.** The operator's words: *"just clear
that specific alert"* — a credential warning that has been dealt with should go
away, while the next one still arrives.

Alerts are an append-only Redis stream and nothing acknowledges them today.

- `POST /alerts/{cursor}/clear` records that cursor in a set
- `GET /alerts` and `/alerts/stream` omit cleared entries
- ⚠ **Key it by cursor, never by kind, agent or account.** A cursor identifies
  one instance; anything coarser is the mute this build is explicitly not
  building
- bound the set — the stream retains ~1000, so cleared cursors below the oldest
  surviving entry are dead weight
- clearing is **tenant-wide and durable**: it must survive a browser refresh,
  because a dismissal that a reload undoes is not a dismissal

Document it in `docs/API.md` next to `/alerts`.

## 2. Credential alerts must clear themselves — `api`

Measured on the operator's laptop: one alert, `status=absent`, raised at
`01:00:42Z`. They logged in at `01:07Z`. **Nothing was ever emitted to retract
it**, so the console correctly rendered a fact that had been false for an hour.

- when a credential the watchdog reported `absent` becomes present, emit the
  status change
- ⚠ **an alert stream cannot express "never mind"** unless something supersedes:
  either emit `status=present` and let readers take the latest per
  `account`+`cli`, or clear the stale entry using §1. Pick one and say which in
  `LLD-watchdog`
- ⚠ **The bug was only ever tested firing.** Whatever you build, test the
  transition back — a guard nobody has seen stop is half-built

## 3. The permission mode must outlive a relaunch — `tmux`

A hired agent came up as `claude --dangerously-skip-permissions --tools …`
(verified at +4s, +8s, +12s on the lab), and was later observed as bare
`/home/ubuntu/.local/bin/claude` carrying `CLAUDE_CODE_RELAUNCH_TERMINAL_SIZE`
and `CLAUDE_CODE_TUI_JUST_SWITCHED=fullscreen`. The CLI re-executed itself and
its argv — the only place the permission mode lived — went with it. The agent
then sat asking for permission.

⚠ **What is NOT known:** what triggers the relaunch. A forced `resize-window` on
the lab did **not** reproduce it, and both machines run claude 2.1.227. Do not
write a fix that assumes a trigger.

- put the permission mode where `skipDangerousModePermissionPrompt` and `tui`
  already live — `~/.claude/settings.json`, written by the profile seeding in
  `tmux/ops.py` — so a relaunch keeps it
- ⚠ **verify the key against the installed CLI** rather than assuming the schema
- `startAgent`'s flags stay; they become a convenience rather than the only
  thing holding the mode up

## 4. Conversation history must not depend on an optional flag — `architect`

`clients/web/server.py:374` rebuilds the operator's own messages by replaying
the audit log. Started without `--audit-log`, outbound history has no source and
every refresh looks like data loss. Agent replies survive, because those come
from the mailbox. Mine to fix — `clients/` is closed to lane development.

## 5. Done when

⚠ **Each demonstrated against a running tenant.** Not a unit test alone: every
one of these passed its tests and failed in front of an operator.

- an alert cleared in the console stays cleared after a refresh, **and the next
  alert of that kind still arrives**
- a credential alert raised before a login is gone after it
- an agent's permission mode survives the CLI re-executing itself
- the console shows what the operator typed after a reload

## 6. Reporting

`jira done`, then message `architect` with the commit you worked from, what you
changed, and what you forced. ⚠ **If you cannot run docker in your lane, say so
and stop where you can reach** — that answer has been the right one twice.
