# LLD — the office command

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address
> scheme, the envelope, and the board mechanics it does not repeat here.
> [`CONTRACTS.md`](CONTRACTS.md) §5 and §6 pin the command surface and the
> kind/payload table; this document is the deep dive behind them.

## 1. Purpose

The one binary every agent has on `PATH`, in every window
(`LLD-port-tmux` §1). It is the whole of an agent's reach into the tenant: who
it can talk to, what it can start or stop, and the four-list board it pulls
work from. `flock.office` imports `flock.bus` and nothing else
(`src/flock/office/cli.py:14`) — the same rule that lets every other lane own
its module outright (`HLD` §3).

```
  agent's window
       │  office <command>
       ▼
  ┌─────────────────────────────────────────────┐
  │  src/flock/office/cli.py                     │
  │    a stateless, one-shot process              │
  └───────────┬───────────────────────┬──────────┘
              │                       │
      flock.bus.send()         direct Redis
      (builds + writes an      reads/writes on
       envelope; §3 below      the caller's OWN
       lists which commands    keys; §3 lists
       do this)                which commands do
              │                this
              ▼                       ▼
        …:<source>:egress      board / roster /
        → switch → …            presence / usage
                                keys, read or
                                mutated in place
```

`office` is deliberately narrow: every token after the destination is literal
message text, including option-looking tokens, so explaining an `office`
command to another agent cannot let the outer parser eat the inner one's flags
(`LLD-bus-and-switch` §7). It never reports delivery — it cannot observe it —
and it is read-only about presence and activity: it combines signals the
switch and watchdog already computed, and creates, clears or repairs nothing
except its own commands' own board.

**Fast transient startup, not `redis-py`.** Every invocation is a new process
inside an agent's turn, so `flock.bus.resp` is a minimal hand-rolled RESP2
client (`src/flock/bus/resp.py:1`) built for a one-shot connect-command-exit,
not a library's general-purpose overhead. `_REDIS_URL` defaults to
`redis://127.0.0.1:6379/0` and reads `REDIS_URL` for a tenant with a Redis
password (`cli.py:19`).

## 2. Identity, and how a command finds it

Identity is never an argument. `_context()` (`cli.py:86`) reads `AGENT_NAME`
(required — `OfficeError` if absent), `POD` and `TENANT` (both default
`"default"`) straight from the window's environment, so the same binary
writes the right egress and the right board keys without being told who it
is. This is what makes "no agent writes another agent's keys" (`HLD` invariant
3) hold structurally rather than by convention — the command has no argument
that could name someone else's identity to write as.

⚠ **`main()` scopes `FLOCK_LOG_QUIET` to its own run** (`cli.py:854`), setting
it before dispatch and restoring whatever it found afterward. `office` runs
inside an agent's own pane, so bus telemetry it would otherwise print
(`sent`, `send_refused`, …) is a signpost the agent does not need and, once,
was how one found the queue, the Redis URL and the broker (`HLD` §10a). The
window log the switch tails still gets the record; the pane does not. Scoped
rather than global because `main()` is called in-process by the test suite,
and leaking the flag would silence unrelated components for the rest of the
run.

## 3. What crosses the bus, and what is a direct Redis operation

Two different things share one binary, and telling them apart matters for
reasoning about who can see or block what:

| category | commands | mechanism |
|---|---|---|
| **bus send** — builds an envelope, writes the caller's own egress, the switch and a port do the rest | `send`, `broadcast`, `add`, `hire`, `letGo`/`let-go`, `pause`, `resume` | `flock.bus.send()` |
| **direct Redis, own keys** — reads or mutates keys under the caller's own `agent:<source>:*` prefix, no envelope, no switch, no port | `take`, `done`, `cancel`, `hold`, `delete` | `LPOP`/`RPUSH`/`LREM` on `tasks.*` |
| **direct Redis, read-only** — point-in-time reads, no mutation | `peers`, `profiles`, `status`, `list`, `usage` | `HGETALL`/`LRANGE`/`GET`/`XRANGE` |
| **filesystem, roster read only** | `cloneToAll`/`clone-to-all` | local `git clone`, no bus, no board |

⚠ **`add` is the one board-mutating command that *is* a bus send.** It targets
*another* agent's board, and the only way to reach another participant's keys
is through the switch and that participant's own `AddTicket` opener
(`LLD-bus-and-switch` §7, `CONTRACTS` §6) — never a direct write. Every other
board command (`take`/`done`/`cancel`/`hold`/`delete`) mutates the *caller's
own* board directly, because writing your own keys needs no envelope and no
switch trip; going through the bus for `take` would mean asking yourself for
permission.

⚠ **`hire`/`letGo`/`pause`/`resume` do not check the target agent exists
first.** They build a control-kind envelope addressed to `host` and let its
opener decide (`cli.py:323`, `_control_command`) — `hire` creates the name,
so checking would be backwards for it, and the others let one dead-letter
reason live in one place rather than two.

⚠ **`send` and `add` do check** (`is_member`, `cli.py:140`, `:581`) before
building the envelope, because sending to an unenrolled name is always a
mistake for those two, never a lifecycle transition.

## 4. Messaging and directory: `send`, `broadcast`, `peers`, `profiles`

**`send`** (`cli.py:108`) takes exactly one payload source — positional text,
`--stdin`, or `--file <path>` — mutually exclusive, checked before any Redis
call. `--stdin` refuses empty input; `--file` reads without shell
interpretation. The body becomes `{"text": "<body>"}` under `kind: "Message"`
(`_message`, `cli.py:95`). Full flag semantics — `--`, dash-leading bodies,
the byte-count acknowledgement — are `CONTRACTS.md` §5's, not repeated here.

**`broadcast`** (`cli.py:148`) is the one command still on
`argparse.REMAINDER`: multi-word text is unquoted, deliberately unlike `send`
(`CONTRACTS` §5). It resolves recipients client-side — every roster member
except the caller with `port_type == "tmux"` — and sends one `Message` per
recipient. This is the client-side filter `HLD` §6 contrasts with a raw
`destination: "all"`, which reaches every roster row including `api` clients.

**`peers`** (`cli.py:166`) lists the same `port_type == "tmux"`-minus-self set.
Plain output is one line, comma-joined, with `(lead)` appended to whichever
name matches the tenant's `lead` key (`prefix(pod, tenant, resource="lead")`,
read live — not baked into any agent's guide). `-v` adds, per peer: `launch`
(the CLI, or `"unknown"`), `profile` if set, and the title of whatever ticket
sits at the head of that peer's `tasks.doing` — three keys the file already
reads for other commands, assembled into a display rather than a new read
path. Plain `office peers` is unchanged by `-v` existing; a test pins that
specifically, because that is when a regression would happen unnoticed.

**`profiles`** (`cli.py:199`) is the tenant-wide account audit `peers -v`
cannot give: every configured account, which tmux agents are on it, which
landed on `default` implicitly, and which roster members carry no account at
all (`api`, `control`). The account/profile mechanism itself —
`available_profiles()`, the `profile` Redis key, `CLAUDE_CONFIG_DIR` /
`CODEX_HOME` — is `HLD` §2a and the `GLOSSARY` `account`/`profile` entries;
this command is a read over exactly those keys, nothing more.

## 5. Lifecycle: `hire`, `letGo`/`let-go`, `pause`, `resume`

One shared implementation, `_control_command` (`cli.py:323`), keyed by a
`{command: kind}` table (`hire → StartAgent`, `letGo → StopAgent`, `pause →
PauseAgent`, `resume → ResumeAgent`). All four build a payload around
`{"agent": <name>}` and send it to `host` — never act locally. What each kind
does once it lands is `control`'s opener, described in `CONTRACTS` §6 and
`LLD-bus-and-switch` §7, not here.

`hire` alone carries extra validation, both client-side:

- `--cli` is `choices=("claude", "codex", "agy")` (`cli.py:343`) — an accepted
  typo used to reach `startAgent <typo>` inside the freshly created window,
  indistinguishable from a login prompt or a CLI with nothing to say yet. A
  typo now fails at the prompt instead.
- `--profile` is checked against `available_profiles()` when the registry
  exists (`cli.py:356`) — the same registry `profiles` reads — refusing with
  the list of configured accounts rather than dead-lettering one component
  away from where it was typed.

⚠ **Both checks are advisory, not authoritative.** `control/openers.py`
validates the same two fields again at the far edge (`CONTRACTS` §5), because
the client and the fabric are different processes and the fabric is the one
that must not trust what crossed the bus.

## 6. The board: `add`, `list`, `take`, `done`, `cancel`, `hold`, `delete`

**Board mechanics — one open ticket, pull not push, `AddTicket` as the only
cross-agent write — are `LLD-bus-and-switch` §7 and `HLD` §9. This section is
the ticket shape and the seven commands' edges around it.**

### 6a. The ticket

`_ticket()` (`cli.py:402`) normalizes whatever JSON sits in a list entry into:

```
{v, id, title, description, created_by, status, created_ts, started_ts, done_ts, [priority]}
```

Reading is defensive by construction: a non-dict, a missing `id`, or a
non-string `title` all raise `OfficeError` rather than propagate a malformed
board entry into a command that assumes a shape. `_serialized()` (`cli.py:431`)
writes it back with `separators=(",", ":")` — compact, not pretty-printed,
because it is a Redis list entry, not a file for a human to read directly.

### 6b. Selecting a ticket

`_select()` (`cli.py:441`) is shared by `take` (with an id), `done`, `cancel`,
`hold` and `delete`. With no reference it requires exactly one match — zero is
"you have no open task", more than one is "specify an id". With a reference it
matches by **id prefix**, refusing an empty match set and an ambiguous one
(more than one ticket sharing that prefix) by name. `_remove()` (`cli.py:457`)
does the `LREM` and raises if it removed nothing — the entry changed under the
command mid-run, which reads as "try again" rather than a silent no-op.

### 6c. The seven commands

| command | states it reads from | states it writes to | notes |
|---|---|---|---|
| `add` | — | destination's `todo` (via `AddTicket`) | the one cross-agent write; §3 above |
| `list` | all four, `-a`/`--all` for every `tmux` agent | — | prints id-prefix + title only; `-a` adds a per-agent heading |
| `take` | `todo`, `hold` (by id) | `doing` | refuses when `doing` is non-empty (`cli.py:504`) — checked, not emergent; no id pops FIFO from `todo` |
| `done` | `doing` | `done`, `status: "done"` | |
| `cancel` | `doing` | `done`, `status: "cancelled"` | shares `_finish_command` with `done` (`cli.py:527`) |
| `hold` | `doing` | `hold`, `status: "hold"` | `started_ts` stays; `done_ts` is never set |
| `delete` | any of the four | — | permanent; requires an id, no "your one open task" default |

⚠ **`take` with an explicit id can pull from `hold`, not just `todo`.** That is
what makes `hold then take by prefix` a normal flow rather than a dead end —
a held ticket is not retired, it is parked.

Every state transition calls two independent recorders, and each swallows its
own failure so history can never break the mutation it is recording
(`LLD-bus-and-switch` §7):

- `record_task_event()` (`flock.bus.logging`) appends one JSONL line to
  `TASK_RECORD` (default `~/.flock/tasks.jsonl`) — `event`, `id`, `title`,
  `agent`, `actor`, `timestamp`.
- `_log_task()` (`cli.py:462`) calls `log_record("office", event, …)`, which
  reaches the window log the switch tails, same as the bus telemetry §2
  silences from the pane.

## 7. `cloneToAll` / `clone-to-all`

The filesystem-shaped exception (`LLD-bus-and-switch` §7): no envelope, no
board, just `git`. `_clone_agents()` (`cli.py:606`) selects live `tmux`
participants — `-a a,b` narrows to a comma-separated subset, validated against
that set; omitted means all of them. It fetches the upstream **once** into
whichever target agent clones first, clones every remaining target from that
local copy, and points **every** clone's `origin` at the supplied URL rather
than at the local source (`cli.py:649`, `:624`) — so the network cost is paid
once but no agent ends up with another agent's workspace as its remote.
Existing target directories are skipped outright; a failed clone's partial
directory is removed (`shutil.rmtree`) so a retry does not read "already has
it" from debris. `--dry-run` performs no writes and reports what would happen.
`api` and `control` participants have no `/workdir` and are never targets.

Also reachable as the bare `cloneToAll` on `PATH` (`clone_to_all_main`,
`cli.py:871`), which delegates to `office cloneToAll` rather than
reimplementing it — a second copy existed for two days in 2026-08-19..21,
dropped this cleanup, and left directories every later run misread as done.

## 8. `usage`

Reads the tenant's `usage` Redis Stream (`prefix(pod, tenant,
resource="usage")`) end to end with `XRANGE`, aggregates by `(agent, cli,
model)`, and prices each row against `container/config/pricing.json`
(longest-prefix match, `pricing.py:62`) — a model absent from that file reads
`unpriced`, never `0.00`, so a genuinely free model and an unpriced one never
look the same in a total. `--agent` and `--since` filter client-side after the
full stream read; `--json` emits the same aggregation as structured data
instead of the fixed-width table. An `agy` agent — a CLI this tenant does not
instrument — is listed separately with `"collected": false` (JSON) or `-` /
`unpriced` (table), sourced from the roster and its `launch` key rather than
from any usage record, since it is guaranteed to have none.

Full record shape, correlation and pricing edge cases are `CONTRACTS.md` §5's
`usage` entry, not repeated here.

## 9. Errors and output

Every command-level failure is `OfficeError` (`cli.py:45`), a `ValueError`
subclass carrying a user-facing message. `_run()` (`cli.py:886`) is the single
catch point: it prints `office: error: <message>` to stderr and exits 1.
Nothing below that boundary prints its own error text or exits directly —
argument parsing errors are the one exception, going through `argparse`'s own
`parser.error()`, which prints usage and exits 2.

Successful commands print exactly what a caller needs to act on next: a
`stream_id` for a bus send, a serialized ticket for a board mutation, a byte
count for `send`. Nothing is printed "for information" beyond that — the
board and Redis are the source of truth, and a command that also narrated
its own success would be a second place for that truth to drift from the
first.

## 10. What this is not

Not a daemon — every invocation is one process, one connection, one command,
then exit (§1). Not a place kinds are validated or interpreted — `add` builds
an `AddTicket` envelope and never asks whether the destination's board is
being watched; `hire`/`letGo`/`pause`/`resume` build a control envelope and
never ask whether `host` will accept it. Not a second copy of what
`LLD-bus-and-switch` and `HLD` already say about the switch, the board, or the
account mechanism — this document cites them rather than restating them, and
it goes stale the moment it does not.
