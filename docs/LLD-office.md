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
(`src/flock/office/cli.py:17`) — the same rule that lets every other lane own
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
password (`cli.py:22`).

## 2. Identity, and how a command finds it

Identity is never an argument. `_context()` (`cli.py:96`) reads `AGENT_NAME`
(required — `OfficeError` if absent), `POD` and `TENANT` (both default
`"default"`) straight from the window's environment, so the same binary
writes the right egress and the right board keys without being told who it
is. This is what makes "no agent writes another agent's keys" (`HLD` invariant
3) hold structurally rather than by convention — the command has no argument
that could name someone else's identity to write as.

⚠ **`main()` scopes `FLOCK_LOG_QUIET` to its own run** (`cli.py:1073`), setting
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
| **bus send** — builds an envelope, writes the caller's own egress, the switch and a port do the rest | `send`, `send-file`/`sendFile`, `broadcast`, `add`, `hire`, `letGo`/`let-go`, `pause`, `resume` | `flock.bus.send()` |
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
opener decide (`cli.py:483`, `_control_command`) — `hire` creates the name,
so checking would be backwards for it, and the others let one dead-letter
reason live in one place rather than two.

⚠ **`send`, `send-file` and `add` do check** (`is_member`, `cli.py:150`, `:265`, `:792`) before
building the envelope, because sending to an unenrolled name is always a
mistake for those, never a lifecycle transition.

## 4. Messaging and directory: `send`, `send-file`, `broadcast`, `peers`, `profiles`

**`send`** (`cli.py:118`) takes exactly one payload source — positional text,
`--stdin`, or `--file <path>` — mutually exclusive, checked before any Redis
call. `--stdin` refuses empty input; `--file` reads without shell
interpretation. The body becomes `{"text": "<body>"}` under `kind: "Message"`
(`_message`, `cli.py:105`). Full flag semantics — `--`, dash-leading bodies,
the byte-count acknowledgement — are `CONTRACTS.md` §5's, not repeated here.

**`send-file`** (alias **`sendFile`**, `cli.py:192`) sends an `Attachment`
envelope to one agent (`office send-file -a <destination> <path> [--caption <text>] [--mime-type <type>]`).
It requires `-a <destination>` (unicast only; `destination: all` is refused),
validates that `<path>` is a regular file, checks `ATTACHMENT_MAX_BYTES` (10 MiB)
before reading and encoding, validates the basename (`<=255` UTF-8 bytes, no
slashes, control characters, or `.`/`..`), validates or guesses the MIME type
(falling back to `application/octet-stream`), validates caption length (`<=65,536` UTF-8 bytes),
and encodes the raw bytes into RFC 4648 standard base64 with padding. The acknowledgement
prints the accepted raw byte count and stream ID (`sent to <destination>: <N> bytes (<stream_id>)`),
matching `send`.

**`broadcast`** (`cli.py:289`) is the one command still on
`argparse.REMAINDER`: multi-word text is unquoted, deliberately unlike `send`
(`CONTRACTS` §5). It resolves recipients client-side — every roster member
except the caller with `port_type == "tmux"` — and sends one `Message` per
recipient. This is the client-side filter `HLD` §6 contrasts with a raw
`destination: "all"`, which reaches every roster row including `api` clients.

**`peers`** (`cli.py:307`) lists the same `port_type == "tmux"`-minus-self set.
Plain output is one line, comma-joined, with `(lead)` appended to whichever
name matches the tenant's `lead` key (`prefix(pod, tenant, resource="lead")`,
read live — not baked into any agent's guide). `-v` adds, per peer: `launch`
(the CLI, or `"unknown"`), `profile` if set, and the title of whatever ticket
sits at the head of that peer's `tasks.doing` — three keys the file already
reads for other commands, assembled into a display rather than a new read
path. Plain `office peers` is unchanged by `-v` existing; a test pins that
specifically, because that is when a regression would happen unnoticed.

⚠ **`-i`/`--interfaces` adds a second, explicitly labeled line for
`port_type in ("api", "control")` roster members — never merged into the peer
list itself.** This exists because the plain colleague list, on its own, once
led an agent to conclude a real roster member (a Telegram bot) was not a valid
`office send` destination just because `peers` didn't say so. `CONTRACTS.md`
§5's "clients are hidden from an agent's view, not from its inbox" invariant is
about the *bare* command and about `broadcast` never reaching a client — it
says nothing about a second, deliberately-requested, deliberately-labeled line
naming exactly which non-colleague addresses exist, which is a different act
from folding them into "peers" as if they were colleagues. `profiles` already
sets this precedent (its "members without CLI accounts" list is the same
`api`/`control` set, framed for account auditing instead); `-i` is that same
fact, framed for "who else can I address" instead of "who has no CLI account".
Every `api`/`control` roster row got there through a `StartAgent` call, so
membership itself is the sanctioning act — there is no further "allowed" flag
to read, and none is invented here. `-i` composes with `-v` (interfaces line
prints last, after either plain or verbose peer output) and is a no-op change
to bare `office peers` and to `office peers -v` alone — both keep their pinned
shapes exactly.

**`profiles`** (`cli.py:358`) is the tenant-wide account audit `peers -v`
cannot give: every configured account, which tmux agents are on it, which
landed on `default` implicitly, and which roster members carry no account at
all (`api`, `control`). The account/profile mechanism itself —
`available_profiles()`, the `profile` Redis key, `CLAUDE_CONFIG_DIR` /
`CODEX_HOME` — is `HLD` §2a and the `GLOSSARY` `account`/`profile` entries;
this command is a read over exactly those keys, nothing more.

## 5. Lifecycle: `hire`, `letGo`/`let-go`, `pause`, `resume`

One shared implementation, `_control_command` (`cli.py:483`), keyed by a
`{command: kind}` table (`hire → StartAgent`, `letGo → StopAgent`, `pause →
PauseAgent`, `resume → ResumeAgent`). All four build a payload around
`{"agent": <name>}` and send it to `host` — never act locally. What each kind
does once it lands is `control`'s opener, described in `CONTRACTS` §6 and
`LLD-bus-and-switch` §7, not here.

`hire` alone carries extra validation, both client-side:

- `--cli` is `choices=("claude", "codex", "agy")` (`cli.py:503`) — an accepted
  typo used to reach `startAgent <typo>` inside the freshly created window,
  indistinguishable from a login prompt or a CLI with nothing to say yet. A
  typo now fails at the prompt instead.
- `--profile` is checked against `available_profiles()` when the registry
  exists (`cli.py:523`) — the same registry `profiles` reads — refusing with
  the list of configured accounts rather than dead-lettering one component
  away from where it was typed.

⚠ **Both checks are advisory, not authoritative.** `control/openers.py`
validates the same two fields again at the far edge (`CONTRACTS` §5), because
the client and the fabric are different processes and the fabric is the one
that must not trust what crossed the bus.

`--resume`/`--fresh` are a mutually exclusive pair (`cli.py:514`), and neither
is the client validating anything — they only decide whether `payload["resume"]`
is present at all. Omitted (the default) means the fabric decides:
`tmuxhost` auto-detects prior session history for that agent's workspace
(`~/.claude[-<profile>]/projects/...`, `~/.codex[-<profile>]/sessions/...`,
`~/.gemini/antigravity-cli/history.jsonl`) and resumes it if there is any —
retiring an agent (`letGo`) never deletes those files, only Redis state and the
window, which is what makes a later re-hire resumable at all. `--resume` forces
`resume: true`; `--fresh` forces `resume: false` and starts clean regardless of
what history exists. The mechanism — which native resume command each CLI gets
launched with, and why `StopAgent` leaves history on disk deliberately — is
`CONTRACTS` §6, not repeated here.

## 6. The board: `add`, `list`, `take`, `done`, `cancel`, `hold`, `delete`

**Board mechanics — one open ticket, pull not push, `AddTicket` as the only
cross-agent write — are `LLD-bus-and-switch` §7 and `HLD` §9. This section is
the ticket shape and the seven commands' edges around it.**

### 6a. The ticket

`_ticket()` (`cli.py:571`) normalizes whatever JSON sits in a list entry into:

```
{v, id, title, description, created_by, status, created_ts, started_ts, done_ts, held_ts, [priority], [related]}
```

Reading is defensive by construction: a non-dict, a missing `id`, or a
non-string `title` all raise `OfficeError` rather than propagate a malformed
board entry into a command that assumes a shape. `_serialized()` (`cli.py:606`)
writes it back with `separators=(",", ":")` — compact, not pretty-printed,
because it is a Redis list entry, not a file for a human to read directly.

⚠ **`held_ts`, set by `hold` (`cli.py:756`), is the youngest of the four
timestamps.** `started_ts` is not reusable for "how long has this been on
hold": `take` overwrites it unconditionally on every take, including a retake
out of `hold`, so it means "since last taken", not "since parked". A ticket
held before this field existed carries none — `list` falls back to
`created_ts` for those rather than showing nothing (§6d).

⚠ **`related` is a list of ticket ids, stored, never validated.** `office add
--related <id>[,<id>...]` (`cli.py:783`) splits on comma, strips, and dedupes
(`list(dict.fromkeys(...))`, the same pattern `_clone_agents` uses); the
opener filters to strings and drops the key entirely when the result is
empty, the same "absent means not set" convention as `priority`. **No
cross-board lookup happens anywhere** — a related id can name a ticket on a
different agent's board, or nothing at all, and neither `add` nor `list`
ever reads another board to check. That is a deliberate limitation, not an
oversight: the whole point is a structural reference in place of "see ticket
&lt;id&gt;" in free text, not a join.

### 6b. Selecting a ticket

`_select()` (`cli.py:616`) is shared by `take` (with an id), `done`, `cancel`,
`hold` and `delete`. With no reference it requires exactly one match — zero is
"you have no open task", more than one is "specify an id". With a reference it
matches by **id prefix**, refusing an empty match set and an ambiguous one
(more than one ticket sharing that prefix) by name. `_remove()` (`cli.py:632`)
does the `LREM` and raises if it removed nothing — the entry changed under the
command mid-run, which reads as "try again" rather than a silent no-op.

### 6c. The seven commands

| command | states it reads from | states it writes to | notes |
|---|---|---|---|
| `add` | — | destination's `todo` (via `AddTicket`) | the one cross-agent write; §3 above; `--related` sets unvalidated ticket-id links |
| `list` | all four, `-a`/`--all` for every `tmux` agent | — | id-prefix, title, priority, related ids and state-scoped age (§6d); `-a` adds a per-agent heading |
| `take` | `todo`, `hold` (by id) | `doing` | refuses when `doing` is non-empty (`cli.py:711`) — checked, not emergent; no id pops FIFO from `todo` |
| `done` | `doing` | `done`, `status: "done"` | |
| `cancel` | `doing` | `done`, `status: "cancelled"` | shares `_finish_command` with `done` (`cli.py:734`) |
| `hold` | `doing` | `hold`, `status: "hold"`, `held_ts` | `started_ts` stays as "last taken"; `done_ts` is never set |
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
- `_log_task()` (`cli.py:637`) calls `log_record("office", event, …)`, which
  reaches the window log the switch tails, same as the bus telemetry §2
  silences from the pane.

### 6d. What `list` shows beyond id and title

The default line was `<id8>  <title>` and nothing else — `priority`,
`created_ts`, `started_ts`, `done_ts` all existed on the ticket and none of
them were visible without `office take` or a direct Redis read, which does not
scale to `list --all` across a whole tenant. `_ticket_line()` (`cli.py:658`)
appends, when present, `p:<priority>`, `rel:<id8>,<id8>,…` and
`age:<duration>` in that order — priority and relations are ticket metadata,
age is timing, kept last. Age is formatted by the same `_age()` (`cli.py:411`)
`status` already uses for "last activity N ago" — one duration vocabulary
across both commands rather than two. `rel:` truncates each related id to
eight characters, the same prefix width as the ticket's own id column, so a
line stays scannable rather than wrapping under a handful of full UUIDs.

**No existing consumer parses the old shape** — checked before changing it:
`office`'s own guide text quotes `office list` only as a one-line description
(`tmux/ops.py:112`), no `container/scenarios/*.sh` or `accept.sh` greps its
output, and the one test that pins the format
(`test_list_prints_short_ids_and_titles_for_all_four_lists`) asserts substrings
like `"a1  next" in output`, not an exact line — so appending fields is safe
and the default output stays what it was, extended rather than replaced. No
`--json`/`-v` flag was added because there was nothing to keep backward
compatible with.

**"Age" means one thing, consistently: time in the state the line is printed
under**, not a duration score (`_ticket_age`, `cli.py:648`):

| state | timestamp | why |
|---|---|---|
| `todo` | `created_ts` | how long it has waited, untouched |
| `doing` | `started_ts` | how long work has been in progress — matches `status`'s task column |
| `hold` | `held_ts` | how long it has been parked (§6a) |
| `done` | `done_ts` | how long ago it finished |

⚠ **`done`'s total cycle time (`created_ts` → `done_ts`) was considered and
rejected.** It is a genuinely useful number, but it means something different
from the other three — "how long did this take" rather than "how long has it
sat here" — and mixing the two under one unlabelled `age:` would need a second
label to stay honest. One consistent meaning across all four states was worth
more than the extra metric; a cycle-time view is a `created_ts`/`done_ts` diff
away for anyone building one.

A ticket missing its state's timestamp (a pre-existing entry from before this
shipped, or a hand-written test fixture) prints with no `age:` segment at all
rather than a placeholder — same defensive-by-omission style as `priority`.

## 7. `cloneToAll` / `clone-to-all`

The filesystem-shaped exception (`LLD-bus-and-switch` §7): no envelope, no
board, just `git`. `_clone_agents()` (`cli.py:821`) selects live `tmux`
participants — `-a a,b` narrows to a comma-separated subset, validated against
that set; omitted means all of them. It fetches the upstream **once** into
whichever target agent clones first, clones every remaining target from that
local copy, and points **every** clone's `origin` at the supplied URL rather
than at the local source (`cli.py:860`, `:836`) — so the network cost is paid
once but no agent ends up with another agent's workspace as its remote.
Existing target directories are skipped outright and never reused as the
local source for subsequent fresh clones in that run; a failed clone's partial
directory is removed (`shutil.rmtree`) so a retry does not read "already has
it" from debris. `--dry-run` performs no writes and reports what would happen.
`api` and `control` participants have no `/workdir` and are never targets.

Also reachable as the bare `cloneToAll` on `PATH` (`clone_to_all_main`,
`cli.py:1090`), which delegates to `office cloneToAll` rather than
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

Every command-level failure is `OfficeError` (`cli.py:53`), a `ValueError`
subclass carrying a user-facing message. `_run()` (`cli.py:1105`) is the single
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
