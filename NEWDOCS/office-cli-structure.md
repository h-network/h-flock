# office: a one-shot CLI, not a daemon

This note describes the current implementation of `src/flock/office/`. It does
not propose that every private function is a clean abstraction boundary, or
that the file's internal organization is wrong for what it does today — the
useful distinction, same as tmux's daemon/library note, is what actually runs
continuously versus what runs once because a human or a script invoked it.

## 1. No daemon, no loop, no exception

`office` is a process that parses `argv`, does the one thing the first
argument names, prints a result, and exits. There is no background loop
anywhere in the module:

- `src/flock/office/__main__.py` is three lines: import `main` from `.cli`,
  call it. No arguments, no setup.
- `main()` (`cli.py`) sets `FLOCK_LOG_QUIET` for the duration of the call,
  calls `_run()` once, restores the environment variable, and returns.
- `_run()` parses the command name, dispatches to exactly one `_<command>_command`
  function (or `_control_command` for the four lifecycle names), and returns.
  Every `for` loop in the file iterates a collection already fetched from
  Redis or already known (roster members, a ticket list, `argv` characters,
  hire's `_COMMANDS` tuple) — there is no `while True`, no polling, no
  `time.sleep`, anywhere in `src/flock/office/`.
- The process holds one Redis connection (`flock.bus.resp.Redis`, a
  hand-rolled RESP2 client built for exactly this: connect, issue the
  command(s) one invocation needs, disconnect) and, for `cloneToAll`, spawns
  `git` as a subprocess it waits on synchronously.

**The one exception worth flagging, and it is not really an exception**:
`office broadcast` and `office cloneToAll` both loop over multiple
recipients/targets and do multiple bus sends or multiple `git clone`
invocations within that single process lifetime. That is still one process
running to completion, not a resident loop — it is bounded by the roster size
at the moment of invocation, not by time or by new work arriving. There is
nothing in this module that a signal, a supervisor, or a restart policy would
ever need to manage the way `tmuxhost`'s `run_forever()` is managed.

## 2. The real structure

`office` has exactly two files with behavior: `cli.py` (1175 lines, all 22
command names) and `pricing.py` (a pure calculation library `usage` calls
into). `__init__.py` re-exports `main` and adds nothing.

### Entry points

- `flock.office:main` (console script `office`) and
  `flock.office.cli:clone_to_all_main` (console script `cloneToAll`) are the
  two things actually on `PATH`. `clone_to_all_main` is not a second
  implementation — it calls `main(["cloneToAll", *sys.argv[1:]])`, i.e. it is
  the same dispatcher entered with the command name already filled in. A
  second, independent implementation of this existed for two days in
  2026-08-19–21 and silently dropped `_clone_to_all_command`'s cleanup of a
  half-written clone; the comment on `clone_to_all_main` records that as the
  reason to delegate rather than reimplement.
- `_root_parser()` builds the top-level `argparse` parser and the
  `_COMMANDS`/description table used for `--help`. `_run()` is the actual
  dispatch: a name off `argv[0]`, an `if/elif` chain to one handler function,
  `OfficeError` caught at that one point and turned into `office: error: …`
  on stderr with exit 1.

### The four mechanism categories, and where each command's code lives

This split already exists as a documented table in `docs/LLD-office.md` §3;
mapping it to actual function names:

**Bus sends** (build a payload, call `flock.bus.send()`, print the
acknowledgement) — `_send_command`, `_send_file_command` (plus
`_validate_filename`/`_validate_mime_type`), `_broadcast_command`,
`_add_command`, and `_control_command` (shared by `hire`/`letGo`/`pause`/
`resume` — one function, keyed by a `{command: kind}` table, because all four
build a `{"agent": <name>}`-shaped payload and differ only in extra
validation and which `kind` string they send). `_message()` is the one
payload-builder shared between `send` and `broadcast`.

**Direct Redis, own keys** (`take`/`done`/`cancel`/`hold`/`delete`) —
`_task_keys()` builds the four list-key names for one agent; `_ticket()`
normalizes a raw list entry into the ticket shape and `_serialized()` writes
it back; `_select()` and `_remove()` implement "find the one ticket a command
means" (by id prefix or by "the only one there") and "pop it, or fail loudly
if it already changed"; `_log_task()` and `flock.bus.record_task_event()` are
the two independent, failure-swallowing history writers every mutation calls.
`_finish_command()` is shared by `done`/`cancel` the same way
`_control_command` is shared by the four lifecycle names.

**Direct Redis, read-only** (`peers`/`profiles`/`status`/`list`/`usage`) —
`_peers_command`, `_profiles_command`, `_status_command` (with
`_status_row`, `_age`, `_timestamp` as its formatting helpers),
`_list_command` (with `_list_one`, `_ticket_line`, `_ticket_age`,
`_AGE_FIELD`), and `_usage_command` (with `_format_token_count`, and the only
call out to `pricing.py`).

**Filesystem, roster read only** (`cloneToAll`/`clone-to-all`) —
`_clone_agents()` selects live tmux targets, `_repo_name()` derives a
directory name from the URL, `_git_clone()` is one `git clone` +
`git remote set-url`, `_clone_to_all_command()` sequences all three plus the
first-clone-becomes-the-local-source optimization and `--dry-run`.

### `pricing.py`

A separate, side-effect-light module: `load_pricing()` resolves a pricing
table in a fixed order — an explicit `path` argument, then an
`FLOCK_PRICING_FILE` environment override, then a short list of candidate
`container/config/pricing.json` locations, then a hardcoded fallback table if
none of those exist — `find_model_rates()` does longest-prefix matching on a
model id, and
`calculate_cost()` combines rates with token counts into a USD figure and an
`is_priced` flag. Nothing here touches Redis, the bus, or argparse — it is a
pure calculation library that happens to live inside the CLI's package
because only `_usage_command` calls it.

## 3. What does not fit cleanly

**One 1175-line file holds all four mechanism categories.** `LLD-office.md`
documents the category split as a *reasoning* tool — it is not reflected in
the file's actual layout. Reading `_send_command` next to `_task_keys` next
to `_clone_agents` gives no signal that one talks to the bus, one mutates
Redis lists directly, and one shells out to `git`; the only thing separating
them is which helper functions they happen to call.

**`_control_command` is the one function serving four command names**, where
every other command (`take`, `hold`, `list`, …) gets its own
`_<name>_command` function. `_finish_command` does the same for two names
(`done`/`cancel`). This is a real, load-bearing pattern (shared validation,
shared payload shape) but it makes the file's own internal convention
inconsistent: 18 of 22 names map one-to-one to a function; 4 map to one
shared function keyed by a string, and 2 more map to another.

**Aliases are kept in sync in three separate places by hand**: the
`_COMMANDS` tuple, the `descriptions` dict in `_root_parser()`, and the
`command in ("send-file", "sendFile")`-style membership checks inside
`_run()` (and the `"letGo" if command == "let-go" else command` normalization
for the lifecycle aliases). Nothing enforces that a name added to one
is added to the other two; `docs/CONTRACTS.md` §5 already carries a warning
that this exact list has drifted (missing `profiles`, then missing
`cloneToAll`/`usage`) at least twice.

**`main()` mutates process-global environment state**
(`os.environ["FLOCK_LOG_QUIET"]`) from inside what the module's own docstring
calls "a stateless, one-shot process." It restores the previous value
afterward and the reason is documented (bus telemetry printed to an agent's
own pane is a signpost the agent does not need), but it is still a side
effect on shared process state from a function whose surrounding design
promise is statelessness — and it is why `main()`, not `_run()`, has to be
the thing tests call in-process rather than either being safely callable from
a long-lived caller.

**`pricing.py` is a domain-logic library (billing/cost math) sitting inside
what is otherwise a thin mechanism layer.** Every other file in `office/`
either builds an envelope, reads/writes Redis directly, or shells out to
`git`; `pricing.py` is the one place with actual business rules (longest-prefix
rate matching, what counts as "unpriced" versus "$0.00"). Its only caller is
`_usage_command`, so it reads as usage-specific rather than a
general-purpose office concern, but it lives at the package's top level next
to `cli.py`.

## 4. A cleaner split and vocabulary

With freedom to change file boundaries and names, I would keep `office` a
single console-script CLI (there is no daemon to separate it from) but stop
putting all four mechanism categories and the argument parser in one file:

- `flock.office.cli`: `_root_parser()`, `_operation_parser()`, `_context()`,
  `OfficeError`, and `_run()` (renamed `_dispatch()` — "`_run()`" is easy to
  misread as "run the whole program," which is `main()`'s job, not this
  one's). Nothing here would know how to build an envelope or read a ticket;
  it would only route a parsed command to a handler in one of the modules
  below.
- `flock.office.messaging`: `send`, `send-file`/`sendFile`, `broadcast`,
  `_message()`, `_validate_filename()`, `_validate_mime_type()`, the
  attachment constants.
- `flock.office.directory`: `peers`, `profiles`, `status`, `_status_row()`,
  `_age()`, `_timestamp()`.
- `flock.office.lifecycle`: `hire`/`letGo`/`pause`/`resume`, i.e. today's
  `_control_command`, renamed `_lifecycle_command()`. "Control" already names
  a different module (`flock.control`, the fabric-side opener that actually
  acts on these envelopes) — the same word naming two different layers is
  exactly the confusion `LLD-office.md` §4 already calls out between `office
  send` and `flock.bus.send()`; `_control_command` deserves the same fix.
- `flock.office.board`: `add`/`list`/`take`/`done`/`cancel`/`hold`/`delete`,
  `_task_keys()`, `_ticket()` (renamed `_normalize_ticket()`, to pair with
  `_serialized()` which I'd rename `_dump_ticket()` — parse/dump is a more
  common pairing than an unqualified `_ticket`/`_serialized`), `_select()`,
  `_remove()`, `_log_task()`, `_ticket_line()`, `_ticket_age()`,
  `_finish_command()`.
- `flock.office.clone`: `cloneToAll`/`clone-to-all`, `_clone_agents()`,
  `_git_clone()`, `_repo_name()`, and `clone_to_all_main` (renamed
  `clone_to_all_entrypoint`, so the word "main" is not doing two different
  jobs — the program's `main()` and this command-specific entry point — in
  the same package).
- `flock.office.usage`: `_usage_command()`, `_format_token_count()`, and the
  import of `pricing.py`. I would leave `pricing.py` where it is or fold it
  into this module directly — it is small, single-purpose, and has exactly
  one caller, so a separate top-level file buys nothing a docstring wouldn't.

I would keep the `_COMMANDS` tuple and the `descriptions` dict, but generate
`_run`/`_dispatch`'s branch from a single `{name: handler}` mapping built next
to that tuple, rather than three independently-maintained places that must
agree on the same set of names by convention.

The central boundary would then be: `flock.office.cli` only parses and
routes; every other module is a callable mechanism for exactly one of the
four categories `LLD-office.md` §3 already describes, with `pricing.py`
staying a small, dependency-free calculation library `usage` happens to
import rather than a peer of the mechanism modules.
