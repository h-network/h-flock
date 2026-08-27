# Contracts

> System-level view is [`HLD.md`](HLD.md) — read that first if you are new.
> This file is the narrower thing: what more than one module depends on.

> **Cross-module agreements.** Everything here is depended on by more than one
> lane, which is the only reason it is centralised. Anything one module can
> decide alone belongs in that module's LLD, not here.
>
> The five LLDs remain the design. This file adds nothing to it — it fixes the
> details three lanes would otherwise each answer differently.

## 1. Stack and layout

**Python 3.12 throughout.** `LLD-api` §6 already commits to FastAPI, and the api
and the tmux port both import the bus library — any second language turns that
import into an IPC boundary nobody asked for.

One project, one `pyproject.toml`, one virtualenv in the container. The library
is imported, never vendored.

```
  src/flock/
    bus/         prefix, envelope, the two doors, roster reads   ← library
    tmux/        create/kill/list windows, the paste sequence   ← library
    switch/      the switch process
    control/     the control port_type: StartAgent, StopAgent openers
    port/     the port: invoked per delivery, dispatches on port_type
    tmuxhost/    the tmux host
    api/         the FastAPI app
  tests/
  container/     Dockerfile, entrypoint, compose file
```

Every process is `python -m flock.<module>`. Dependencies: `redis`, `fastapi`,
`uvicorn`, `websockets`. Nothing else without saying why.

⚠ `websockets` is not optional. `uvicorn` has no WebSocket implementation of its
own, and without one `flock.session`'s route answers **404** while logging only a
warning — which looks like a wrong path, not a missing package. FastAPI's
`TestClient` does not need it, so unit tests pass either way.

**`flock.bus` and `flock.tmux` are the only shared libraries.** `switch`,
`port`, `tmuxhost` and `api` never import *each other* — the layer split in
`LLD-bus-and-switch` §1 is enforced by that rule and is checkable by grep.

`flock.tmux` holds the low-level operations — `create_window`, `kill_window`,
`list_windows`, and the paste sequence — because both the tmux host and the
port's openers drive tmux. One implementation with two callers; two
implementations would drift, and the drift would be invisible until a window
appeared with the wrong environment or the wrong shell.

## 2. The bus library surface

Frozen here so the api and port lanes can code against it before it exists.
The `bus` lane owns the implementation and may add to this; it may not change
what is written below without saying so.

```python
# flock.bus.keys
def prefix(pod: str, tenant: str, agent: str | None = None,
           resource: str | None = None) -> str
    # pod:<pod>:tenant:<tenant>[:agent:<agent>][:<resource>]
    # validates every segment against ^[a-z0-9][a-z0-9-]{0,62}$
    # rejects the reserved words pod / tenant / agent / all and all-digit values
    # raises KeyError on anything invalid. There is no way to build a flat Redis key.

# flock.bus.envelope
def build(kind: str, source: str, destination: str, payload: dict,
          correlation_id: str | None = None, *, pod="default",
          tenant="default") -> dict
    # returns a v3 frame with L2 source/destination and qualified L3 addresses;
    # mints stream_id and mints correlation_id when not given (propagate-or-mint)
def parse(raw: str) -> dict          # validates the full frame at the port
def parse_for_switch(raw: str) -> dict
    # validates common and L2 fields only; never reads L3

# flock.bus.doors
def send(r, *, pod, tenant, source, destination, payload,
         kind="Message", correlation_id=None) -> str
    # resolves destination locally, builds, writes the egress named by source,
    # and logs. A non-local qualified destination is logged and raises before write.
    # ⚠ Not "its own" — the caller supplies `source`, and the same value
    # picks the queue. They agree by construction, not by verification.
class DeadLetter(Exception)             # opener rejection; reason is str(exc)
def receive(r, *, pod, tenant, agent, openers: dict[str, callable],
            timeout: int, blocking: bool = True) -> None
    # BLPOP this agent's ingress when blocking; LPOP for a kicked one-shot.
    # Then validate, dispatch on kind, and log.
    # unknown kind -> dead-letter under THIS agent's prefix

# flock.bus.roster
def members(r, *, pod, tenant) -> set[str]        # HKEYS  — fields only
def is_member(r, *, pod, tenant, agent) -> bool   # HEXISTS
def port_type(r, *, pod, tenant, agent) -> str | None   # HGET   — port side only
    # the port dispatches on it, and control openers read it to know which
    # teardown they owe (build 12). ⚠ The switch still never reads a value —
    # that is invariant 8, and it is about the switch, not about this function.
```

The Redis wire is **hard v4**: a frame is a fixed 256-byte ASCII header then an
opaque JSON body (`bus/envelope.py:16`), and anything else is rejected rather
than upgraded — as v3 rejected v2 and v2 rejected flat v1. ⚠ **191 is the TTL
offset now, not the header width** (`TTL_START`, `bus/envelope.py:13`); a reader
who remembers 191 as the width is one version behind. HTTP send request bodies
are port input and keep their existing shape; mailbox consumers receive the
layered frame and must read L2/L3, and since v4 also `ttl` and `hops`.

⚠ **The switch calls `members` and `is_member`, never `port_type`.** Reading the value
is what would tell it how an agent is hosted, which invariant 8 forbids. That is
the whole of the split: the switch reads the table's fields, a port reads its
values.

An opener is `callable(envelope: dict) -> None`. A normal return means opened;
raising `DeadLetter(reason)` asks `receive` to park and log it instead. The
opener never writes the dead list or emits a terminal record itself. Registering
one is how a kind becomes deliverable; `LLD-port-tmux` §3 is the tmux
implementation of one.

⚠ **Port burst batching**: When `flock.port` wakes up, it atomically drains all
currently queued envelopes from the agent's ingress queue via an atomic Lua script
(`_DRAIN_INGRESS`). Consecutive `Message`-kind envelopes are concatenated into ONE
combined bracketed paste in arrival order, executed under a single lock acquisition.
Non-`Message` kinds (`Command`, `AddTicket`) are executed individually in arrival
order. Every drained envelope retains its full custody record chain (`received`,
`pending.verify` / `delivery.markers`, and `opened` per `stream_id`).

### `flock.tmux` — the shared window surface

Frozen for the same reason as the bus library: the `tmux` lane implements it and
the `control` port_type calls it.

⚠ **Every tmux-driving entry point calls `require_isolated_tmux()` first.**
`run_tmux` does it for you; anything invoking `tmux` by other means — a
control-mode client, for instance — must call it explicitly.

```python
def require_isolated_tmux(socket: str | None = None) -> None
    # raises AmbientTmuxError unless a socket is given, or TMUX_SOCKET or
    # TMUX_TMPDIR is set. Without one of those, tmux uses
    # /tmp/tmux-$UID/default — the office's own server.
```

This is a guard rather than a warning because the warning did not work. The
office has been destroyed twice by a module driving the ambient server: once by a
reconcile deleting every window not in the roster it was given, once by testing a
control-mode client. Both times the hazard was already documented. The container
always sets `TMUX_TMPDIR`, so the check costs nothing in production.

```python
def run_tmux(*args: str, socket: str | None = None,
             input_data: str | None = None) -> tuple[int, str, str]

def list_windows(session_name: str, socket: str | None = None) -> set[str]
    # empty set means the command succeeded and the session has no windows;
    # a non-zero tmux result raises TmuxCommandError

def create_window(session_name: str, agent_name: str,
                  command: list[str] | None = None,
                  cwd: str | None = None,
                  socket: str | None = None,
                  lead: str | None = None,
                  profile: str | None = None) -> tuple[int, str, str]
    # command defaults to ["env", f"AGENT_NAME={agent_name}", "bash", "-il"]
    # cwd -> tmux -c. Defaults to /workdir/<agent_name>
    # targets "<session>:" — the trailing colon is load-bearing, see
    # LLD-tmux-host §5

def kill_window(session_name: str, window_name: str,
                socket: str | None = None) -> tuple[int, str, str]

def write_agent_guide(cwd: str, agent_name: str, tenant: str = "default",
                      lead: str | None = None, profile: str | None = None) -> None
    # AGENTS.md *and* CLAUDE.md, both, in the agent's own directory
    # every window gets one — create_window calls this for all callers,
    # so a guide is not something a caller can forget

def generate_agents_md(agent_name: str, tenant: str = "default",
                       lead: str | None = None) -> str
    # the guide text itself. Names the board, because nothing else will:
    # a board is pulled, so a silent guide makes it invisible

def ensure_claude_project_trusted(cwd: str, profile: str | None = None) -> None
    # writes hasTrustDialogAccepted AND hasCompletedProjectOnboarding for that
    # directory, in ~/.claude.json or ~/.claude-<profile>/.claude.json
    # per-directory, so a new agent home needs its own — found by running
    # a real CLI into a first-run gate

def ensure_agy_project_trusted(cwd: str) -> None
    # appends cwd to trustedWorkspaces AND sets enableTelemetry = False
    # in ~/.gemini/antigravity-cli/settings.json — global, not per-profile

⚠ **Every routine in this group absorbs its own errors, and now records them.**
`write_agent_guide` and all three `ensure_*_project_trusted` still never raise —
a trust failure must not break a delivery — but each emits a `tmux` `error`
record naming the directory that failed. They used to end in `except: pass`, and
that is exactly how the profile-blind trust bug hid: seeding failed quietly and
every profiled agent sat at a picker, unreachable, reading as `idle`.

def paste_text(session_name: str, agent_name: str, text: str,
               stream_id: str = "", socket: str | None = None) -> None
    # load-buffer → paste-buffer -p -d → delay → Enter
    # failures get a best-effort delete; -d deletes on the successful path
    # the sequence in LLD-port-tmux §4, in one place
    # any non-zero tmux result raises TmuxCommandError; normal return means the
    # complete paste sequence succeeded
```

`StartAgent` writes desired state and leaves creation to tmuxhost, the sole
window-creation implementation. tmuxhost passes the resolved environment and
`startAgent <cli>` command to `create_window`.

### A delivery routine per port_type

`flock.port.deliver` dispatches on the port_type and calls one of these. The
tmux path is inline; API and control have delivery routines with the same
single-envelope contract, so adding a base is adding a routine and a branch:

```python
def deliver_one(r, *, pod, tenant, agent, session_name, socket=None) -> None
```

| port_type | Module | Owner |
|---|---|---|
| `tmux` | `flock.port.deliver` (inline) | `tmux` lane |
| `api` | `flock.port.deliver.deliver_api` | `api` lane |
| `control` | `flock.control` | `bus` lane |

⚠ **This is a named exception to the rule above.** `flock.port` imports
`flock.control`, which is a module and not a shared library. It is done as a
*lazy* import inside the dispatch branch, so a port with no control module
installed logs and carries on rather than failing to start. Any further
cross-module import needs the same explicit justification, or the layer split
stops meaning anything.

## 3. What a log record is

A delivered unicast has **six** records across its life — `sent, popped,
forwarded, kick_started, received, opened`. ⚠ **`kick_started` (build 65) made
it six**; this line said five until 2026-08-15, as did three other docs. Do not
derive this count from a pair-per-component rule: `sent` is an origin and
`kick_started` is an attempted wake-up, not a custody pair.

⚠ **A broadcast does not have six**: `forwarded` is emitted once with `count=N`
and `destination:"all"` (`switch/service.py:169`), so it cannot be joined per
recipient. `analyse-run.py`'s `STAGES` is the operative list.

The contract is a set, and a crash shows up as "popped, no outcome".
That only works if the records join, so the shape is a contract.

**One JSON object per line.** Daemons write records to stdout for the container
to collect. `office` runs inside an agent pane, so it suppresses stdout and
appends to `/home/ubuntu/.flock/window.log.jsonl`; the switch tails that spool to
its own stdout. Board mutations also append their separate operator history to
`TASK_RECORD` (default `/home/ubuntu/.flock/tasks.jsonl`). These files are
transport paths for records, not competing lifecycle schemas.

Every h-flock JSON record printed to container stdout is also copied to
`FLOCK_CUSTODY_FILE` when configured. The compose deployment mounts its parent
directory from the named custody volume, so ordinary container removal keeps
the evidence; an explicit volume removal deletes it. `mirror(line)` never
raises and must be called only for a line also printed to stdout: writing on
only one path creates either missing evidence or a duplicate custody record
(`src/flock/bus/logging.py:27-51`, `container/compose.yaml:105-122`).

| Field | | |
|---|---|---|
| `ts` | required | RFC3339, UTC, milliseconds |
| `module` | required | component name, such as `bus`, `switch`, `port`, `tmuxhost`, `api`, `session`, `watchdog`, `control`, `tmux` or `container` |
| `event` | required | see below |
| `writer` | required | process label: `FLOCK_WRITER` when set, otherwise `module`; it is provenance for analysis, not an unforgeable credential |
| `stream_id` | envelope events only | the join key; absent on lifecycle records |
| `correlation_id` | when known | |
| `source`, `destination` | when known | `destination` is the participant the record is about; receive-side broadcast records name the actual recipient, not literal L2 `all` |
| `reason` | on a failure | why it dead-lettered or was refused |
| `count` | on a broadcast | how many copies were written |
| `task_id` | on a board move | the entry's `id` |
| `bytes` | on window-log truncation | consumed spool bytes removed |

⚠ `task_id`, not `id` — a bare `id` sits beside `stream_id` and `correlation_id`
in the same record and reads as a third identity for the same thing.

Standard process labels for `writer` reflect operational components: `control`,
`switch`, `port`, `tmuxhost`, `watchdog`, `container`, and `usage` (or `bench-send`/`bench-port`
during benchmarking).

⚠ **`writer: fault-injection` identifies deliberately synthetic records.** It is
set via `FLOCK_WRITER=fault-injection` exclusively by the scenario harnesses in
`container/scenarios/` (such as `fault-forward-unknown.sh` and
`partial-control-damage.sh`) when artificially provoking failure shapes like
`forward_unknown` or `stop_agent_incomplete` on a disposable tenant. **It never
appears in normal operation, and no shipping code in `src/` emits, assigns, or
references the `fault-injection` writer or `FLOCK_WRITER` beyond the single read in
`src/flock/bus/logging.py:8`.** An observer or log parser encountering `writer:
fault-injection` knows the event represents deliberate fault-injection testing
rather than a genuine operational failure or live system defect.

The six successful-unicast custody records are a **set, not a sequence**. Join them by
`stream_id`; do not reconstruct custody by sorting timestamps. `send` appends
before it emits `sent`, so a fast switch can emit `popped` before the source
emits `sent` even though custody is correct.

**Ingress admission is atomically count-bounded by `INGRESS_MAX`.** The switch
checks capacity and appends in one Lua execution; it never rolls an over-limit
append back with a later `RPOP`. Unicast admits its one copy or dead-letters it.
A raw broadcast is all-or-none across its selected recipients: if any ingress is
at the bound, none receive the frame, the sender retains one dead-letter with
`destination: "all"`, and no recipient is kicked. A successful broadcast emits
one `forwarded` with `count=N`.

Events, in custody order (not guaranteed log or timestamp order):

```
  sent          send wrote an egress                     (flock.bus.doors)
  popped        the switch took it off an egress         (switch)
  forwarded     … and wrote an ingress                   (switch)
  kick_started  … and successfully spawned the port     (switch)
  dead_lettered terminal alternative to forward/open    (switch or port)
  received      receive took it off an ingress           (flock.bus.doors)
  opened        an opener ran to completion              (port)
```

A module may also log its own **lifecycle** — `started`, `stopped`, `error` —
which is not about any envelope. Those carry no `stream_id`: it is the join key
for one envelope's life, and a synthetic value like `"system"` in that field
makes the six records of a real **unicast** envelope harder to find, not
easier. ⚠ **A broadcast leaves three shared records plus a `kick_started`,
`received`, and `opened` trio per recipient.** The receive-side records name the actual receiving participant even
though the unchanged frame still carries L2 `destination: all`;
`forwarded.count` is the cardinality. N receive-side trios sharing one
`stream_id` are correct for a broadcast. More than one record for the same
`(stream_id, event, recipient)` is a duplicate; the recipient dimension is
unnecessary for unicast. `stream_id`
is required on the seven custody events above and the joinable attempt records
below, and absent on lifecycle records. A parsed frame carries its `stream_id`
on each of those records, but a successful unicast has six custody records:
`dead_lettered` replaces a later success path rather than joining it.

⚠ A malformed frame may have no trustworthy identifier. Its `popped` and
`dead_lettered` records therefore carry `stream_id: unknown` and are not
joinable to a custody set. What remains knowable is the source egress queue,
the time it was popped, the parse reason, and the sender's dead queue retaining
the raw value. The literal field being present does not make it a join key.

`send_refused` is **not a custody record**. It says the sending port
rejected a request before assembly and before any egress write, so there is no
enqueued envelope whose custody could be joined to the six-record set. It
carries `source`, `destination` and `reason`, but no `stream_id`.

Four joinable **attempt records** describe work around custody without claiming
a handover. `send_unknown` means the egress write was attempted but raised, so
its outcome is unknown; `forward_unknown` says the same for an ingress write;
`kick_started` means `Popen` returned and acknowledged the spawn attempt; and
`kick_unknown` means `Popen` raised, so whether the process started is unknown.
The reason names the attempted operation and says `outcome UNKNOWN after`, never
that it failed. The kick records name the actual destination port, including one
record per recipient of a broadcast. They do not prove that the port ran,
popped, or delivered anything; only `received` and `opened` make those later
claims.

⚠ **Conservation carries an unresolved `forward_unknown` in its own
`indeterminate` bucket.** It is neither counted as forwarded (which could create
a phantom handover) nor as lost (which could invite a duplicate retry). Later
evidence can settle it: an `opened` record proves delivery, and a retained
ingress frame proves the write committed but stranded. With no such evidence,
the conservation gate refuses rather than choosing a side. There is no retry.
For broadcast, the one frame-level `forward_unknown` makes every recipient with
no later `opened` record indeterminate; a recipient that did open is settled as
delivered. It is never reported as a known broadcast loss.

⚠ **Attempt-record names are a version boundary.** The current analysers refuse
a log containing legacy `send_failed`, `forward_failed`, or `kick_failed`
instead of interpreting the same observation differently on either side of the
rename. Use a version-specific analyser for a historical custody file; do not
mix old and current attempt semantics in one conservation result.

An `event: usage` record is an observation, not another custody handover. It
uses `writer: usage` and carries `agent`, `cli`, `model`, `input`, `cache_read`,
`cache_write`, and `output`; `stream_id` and `correlation_id` appear only when a
preceding delivery marker can be attributed without guessing. The tenant
`usage` Stream stores the same JSON object in its `usage` field, capped
approximately at 10,000 entries (`src/flock/watchdog/activity.py:480-566`).

Control openers (`src/flock/control/openers.py:37-73`) emit
`{start,stop,pause,resume}_agent_accepted` upon successfully acknowledging all
desired-state writes in Redis (`writer: control`, carrying `destination: <agent>`
and `correlation_id` when present). If request validation fails before any write
is attempted, the opener emits `{start,stop,pause,resume}_agent_failed` with `reason`
before dead-lettering. If any write attempt encounters an exception (including
the first write, where outcome is UNKNOWN with no writes acknowledged), the
opener emits `{start,stop,pause,resume}_agent_incomplete`. ⚠ **`_accepted` records
desired-state acknowledgement, not actual window or process creation.** For `StartAgent`,
actual tmux windows and process lifecycles are reconciled asynchronously by
`tmuxhost.reconcile_once`. For `StopAgent`, the opener attempts to kill the window
synchronously inline after desired-state writes, with `tmuxhost` providing later cleanup.

`resume_agent_partially_failed` is the distinct known-failure outcome: desired-state
writes and any earlier actual-state actions named as acknowledged did occur, but
a later kick was provably rejected by `Popen` and did not spawn a process. It is
neither `_failed` (which would erase the acknowledged subset) nor `_incomplete`
(which is reserved for an attempt whose outcome is UNKNOWN). Its reason names
the acknowledged desired and actual subsets separately, then the failed kick;
the failing kick never appears in either acknowledged list. The envelope is
dead-lettered and the control layer does not retry it.

⚠ **Never log a payload.** Invariant 4 says the switch does not read one; the
same restraint applies to everything else, and a payload is the one field that
may hold something private. Headers are enough to trace an envelope end to end.

⚠ **A swallowed exception is a lost envelope.** `receive` has already popped by
the time an opener runs, so an opener that raises destroys the envelope. Invariant
7 says one bad envelope must not stop the loop; §4 says nothing disappears
silently. Both hold only if the handler dead-letters and logs. `except: pass`
satisfies the first invariant by violating the second.

## 4. The kick

The switch's only outbound call. One fixed command, one argument:

```bash
flock.port <agent>          # e.g.  flock.port frontend
```

Fire and forget — the switch does not wait, does not read a return code, and
does not retry (`LLD-bus-and-switch` §3.3, rail 3). It emits `kick_started` when
`Popen` returns or `kick_unknown` when spawning raises, then throws the process
handle away. Those attempt records do not claim that the port ran or delivered.

⚠ **The switch must set `signal.signal(signal.SIGCHLD, signal.SIG_IGN)` at
start (`src/flock/switch/service.py:243`).** Without it the kernel keeps every
exited kick as a zombie until the switch reaps it, and CPython only reaps at the
top of the *next* `Popen` — so during a burst the reaping lags the spawning.
Measured: **65 zombies** for a 100-envelope run, **40 still present at rest**
afterwards, clearing only when traffic resumed. `SIG_IGN` makes the kernel reap
them immediately and the count never leaves zero.

This is safe **only inside the switch**, because its kick is fire and forget
(rail 3): `SIG_IGN` makes `wait()` and `poll()` unusable, and the switch never
calls them. But an ignored signal disposition survives `exec`, so the spawned
`flock.port` inherits it. A port *does* wait on its own tmux and control
subprocesses and treats their return codes as evidence. Its entry point must
therefore reset `SIGCHLD` to `SIG_DFL` before running any delivery code
(`src/flock/port/__main__.py:7-11`). Without that reset, a child which really
exits non-zero can be auto-reaped before CPython waits for it and be reported as
return code zero: a paste or control action that failed then reads as accepted.

⚠ **The ignore and the reset are one mechanism, not independent defensive
lines.** Removing the switch half reintroduces the zombie leak; removing the
port half makes the switch's necessary disposition corrupt every subprocess
status the port observes. Neither line is redundant, and changing either
requires re-evaluating the other. `tests/test_port.py:36` is the behavioural
guard: under an inherited `SIG_IGN`, the port must expose `SIG_DFL` and preserve
a real child exit status of 1.

⚠ **Throw the handle away.** Discard the `Popen` return value. Keeping the
handles in a list to "track" the children is the natural-looking improvement and
it is the broken one: tracked objects are never garbage collected, so they leak
memory alongside the processes. The careless-looking version is the correct one.

⚠ **A kick that cannot start is not fatal.** `Popen` raises `FileNotFoundError`
when the binary is missing, and `OSError` under fork pressure. Catch it, log a
lifecycle `error` with the agent in `destination`, and carry on — the envelope is
already safely on the ingress queue, so the worst case is that it waits for the
next kick. Letting it propagate kills the switch and, per `LLD-container` §6,
the whole tenant.

The pre-delay measurement split delivery into `forwarded` → `received` 274 ms
(process start, busy tag, `HGET`, `LPOP`) and `received` → `opened` 226 ms (the
paste path).

⚠ **`PASTE_ENTER_DELAY` is the environment variable; `ENTER_DELAY` is the module
constant it is read into** (`tmux/ops.py`). Both names refer to the same thing.

⚠ **That measurement predates `PASTE_ENTER_DELAY = 0.5`**, which
adds 500 ms inside the second half — a delivery now costs about a second, with
roughly 726 ms on the paste side versus 274 ms before `received`. The
delay is not slack for a slow terminal: the paste and the Enter are **two
writes**, and a CLI arriving at both together takes the text and drops the
submit. Do not tune it to zero because the machine is fast.

So **paste-and-enter is the larger half** after the configured delay. The total
puts a single tmux agent near **1 delivery a second**, not 2. Deliveries to
different agents overlap freely, so it is a per-agent
ceiling, not a tenant one, and nothing is lost above it — the backlog waits in
Redis. If it ever matters, the lever is the port's import graph.

The port is invoked, delivers, and **exits**. It is not a service and holds
nothing between deliveries. On start it:

1. acquires the busy tag with a single `HSETNX …:tenant:<t>:delivering <agent>`,
   retrying every 50 ms until it succeeds (`LLD-bus-and-switch` §3.3)

   ⚠ **One command, not two.** An earlier draft of this contract described
   `HEXISTS` then `HSET`, which is racy: two adapters can both see the field
   absent and both write. `HSETNX` decides it atomically. Do not "simplify" it
   back into a check followed by a write.
2. `HGET`s the roster for this agent's port_type, and dispatches to that base's
   delivery routine
3. delivers **the one envelope it was kicked for**
4. `HDEL`s the busy tag and exits

A crash between 1 and 4 leaves the tag set. Nothing expires it and nothing takes
over — that is the design, not an omission. `HGETALL …:delivering` plus the
ingress depth is how you see it.

Adding a base is adding a value to the roster and a routine to the port.
Nothing in the switch changes, because the switch never learns that bases exist.

## 5. The `office` command

The agent-facing surface, and the only part of this a human touches. One binary
on `PATH` in every agent window (`LLD-port-tmux` §1).

```bash
office send -a <destination> "<text>"
office send -a <destination> --stdin
office send -a <destination> --file <path>
office send --agent=<destination> "<text>"
office send -a <destination> -- --<leading-dash-body>
office broadcast <text>...              # tenant broadcast, everyone but you
office hire <agent> [--cli claude|codex|agy] [--profile <account>]
office peers | profiles | letGo | let-go | pause | resume
office add | list | take | done | cancel | hold | delete
office status [<agent>]                 # presence, open ticket, last activity
office cloneToAll <repo-url> [-a a,b] [--dry-run]
office clone-to-all <repo-url> [-a a,b] [--dry-run]
office usage [--agent <a>] [--since <ISO>] [--json]
```

⚠ **Twenty command names (including kebab-case aliases `let-go` and
`clone-to-all`), and this block listed nineteen — missing `profiles` — until
2026-08-26.** Before that it listed fifteen until 2026-08-22, missing
`cloneToAll` and `usage`. The list in `office/cli.py:_COMMANDS` is the
authority; if the two disagree, the code is right and this is the stale one.

- **`send`** delivers a message to one agent. The body is exactly one quoted
  argument, `--stdin` (body read from standard input; empty stdin is refused), or
  `--file <path>` (body read directly from a file without shell interpretation).
  These payload sources are mutually exclusive. Use `--` before a body starting
  with a dash. The acknowledgement is `sent to <destination>: <N> bytes (<stream_id>)` —
  **the UTF-8 byte count is the signal** that confirms accepted payload size.
  ⚠ **`broadcast` deliberately kept `argparse.REMAINDER` and does not follow
  this** — multi-word text is unquoted for broadcast (`office broadcast <text>...`).
- **`hire`** takes `--cli` and `--profile`. ⚠ **`--profile` decides both the
  config directory and the credential** — `~/.claude-<account>` and that
  account's OAuth token if one was given at setup. Omitted means the tenant's
  default account. `--profile` is validated against existing accounts
  (`available_profiles()`) at both the client CLI and fabric opener (`StartAgent`),
  refusing unknown accounts with an explicit list of available accounts.
  ⚠ **`--cli` is validated against the three known values** (`claude`, `codex`,
  `agy`).
- **`cloneToAll`** (and alias **`clone-to-all`**) puts one repository in every `tmux` agent's workspace. It
  fetches from the network **once** and clones the rest from that copy, then
  points each `origin` back at the real URL. `api` and `control` agents are
  skipped — they have no `/workdir`. Also on `PATH` under the bare name, which
  delegates here (`office/cli.py:clone_to_all_main`).
- **`status`** reports agent presence, open work ticket, and last activity feed.
  An `agy` agent reads `not collected (agy)` under the activity feed column.
- **`usage`** reports token counts, active model, rate limits, and estimated cost per agent, from the `usage`
  records the watchdog emits. Codex rows price against the model resolved from
  `turn_context` (e.g. `gpt-5.6-sol` matching `gpt-5` pricing) and surface a rate-limit
  column (`used_percent`, `plan_type`). ⚠ **Rate limits are verified against
  the captured rollout fixture `tests/fixtures/codex-session-captured.jsonl` and
  remain unproven against a live codex agent in acceptance.** An `agy` agent
  reads `model: "not collected"` with `-` for counts and `unpriced` in table output.
  `office usage --json` includes `"collected": false` on uncollected rows
  (`agy`), while claude and codex rows omit the key. `agy` writes a
  per-conversation transcript under `brain/<id>/.system_generated/logs/`, but
  h-flock does not collect it; whether those transcripts carry token counts is
  unverified.
  ⚠ **A model absent from `container/config/pricing.json` reads `unpriced`, never `0.00`** —
  a local model and an unpriced cloud model must not become indistinguishable in a total.

⚠ **Corrected in build 09 — this was seven separate binaries** (`send`,
`sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`, …) and is now one.
Found by running a real agent: told to use `sendMessage`, Claude Code reached for
its **own built-in `SendMessage` tool** and reported that no such teammate
existed — a coherent-sounding failure from entirely the wrong subsystem. A
lowercase prefixed command cannot be mistaken for a PascalCase tool, which fixes
the class rather than the one name.

⚠ Not to be confused with **`flock.bus.send()`** in §2, which is the library
function that writes an egress. Same word, different layer: the command is what
an agent types, the function is what it ends up calling.

Identity is **never** an argument — it comes from `AGENT_NAME`, `POD` and
`TENANT` in the window's environment, so the command writes the right egress
without being told. Exit 0 on write, non-zero with a message on an invalid
destination name. It does not report delivery, because it cannot observe it.

**Payload for `kind: "Message"`** is `{"text": "<the message>"}`. This is an
agreement between `send` and the tmux Message opener, not a bus concern — the
bus does not validate payloads (`LLD-bus-and-switch` §5).

## 6. Kinds and their payloads

`kind` is opaque to the switch and read only by an opener (`LLD-bus-and-switch`
§5). The table below is therefore an agreement between whoever *sends* a kind
and whoever *opens* it — never a bus concern, and never something the switch or
the api validates.

| `kind` | port_type that opens it | Payload | Does |
|---|---|---|---|
| `Message` | `tmux` | `{"text": "..."}` | pastes `[message from <source>] <text>` |
| `Command` | `tmux` | `{"text": "..."}` | pastes `<text>` **bare** — it executes |
| `StartAgent` | `control` | `{"agent": "networking", "cli": "claude", "port_type": "tmux", "resume": true}` | publishes desired launch state, enrols (tmuxhost reconciles window and CLI, auto-resuming history) |
| `StopAgent` | `control` | `{"agent": "networking"}` | removes roster row, purges identity state, kills window inline (tmuxhost cleans up on reconcile) |
| `PauseAgent` | `control` | `{"agent": "networking"}` | marks paused in Redis and interrupts CLI |
| `ResumeAgent` | `control` | `{"agent": "networking"}` | clears pause in Redis, resumes CLI, kicks pending ingress |
| `AddTicket` | `tmux` | `{"title", "description", "priority", "related"}` | writes a ticket to that agent's `tasks.todo` — and **pastes nothing** |

⚠ **`AssignTask` is gone.** It was the old name for `AddTicket`, kept as an alias
"for one build" in build 11 and removed in build 23 — four builds later. Sending
it now dead-letters with a reason, which is the right answer and a visible one.
The lesson is in the delay: a compatibility shim with a date but no owner keeps
its date and loses its removal.

⚠ **`AddTicket` is opened by `tmux` but does not require a tmux window.** It
writes only the board and produces no terminal output: the board is pulled, so
the ticket waits in `tasks.todo` until the agent runs `office take`, including
while its window is crashed or not yet reconciled. A name absent from the roster
never reaches this opener because the switch dead-letters it first.

The opener confirms the synchronous `RPUSH` from its returned list length and
logs `board_write_confirmed`. An exception logs `board_write_unknown` because
the write may have committed before its reply was lost; a returned non-positive
length is provably invalid and logs `board_write_failed`. Both raise `DeadLetter`;
neither creates a
`pending.verify` marker or a `blocked` state because no CLI consumption is
expected for a board write.

`port_type` defaults to `tmux` and accepts `tmux` or `api`; `cli` defaults to `claude`.

⚠ **`port_type: "api"` enrols a client, and creates no window.** A phone app, a web
front end and a Telegram wrapper are each a roster row and a mailbox — nothing
else. `StopAgent` on one removes the row and **purges the client's classified
identity state**, retaining its mailbox and other data and touching no tmux.

⚠ **`hmac_secret`/`kid`/`revoke_kid` only apply to `port_type: "api"`.** The
secret is client-generated and handed to control in the same `StartAgent`,
never minted server-side — `StartAgent` is fire-and-forget with no
synchronous return path (`LLD-bus-and-switch` §3.3), so control has nothing
to hand a generated secret back over. Stored in the clear in
`agent:<name>:hmac-keys` (a hash keyed by `kid`): HMAC verification needs the
same secret on both sides, so a stored digest could never reproduce a
matching signature. Enforced only at `flock.api` when the door is published
(`LLD-api` §3, §6) — loopback-only, nothing reads this state at all. A
repeated `StartAgent` with a new `kid` **adds** a key rather than replacing
one, so an old and new key validate concurrently during rotation;
`revoke_kid` removes one explicitly. `StopAgent`'s generic `AGENT_STATE_RESOURCES`
purge covers `hmac-keys` the same as every other per-agent state resource —
no special-cased teardown.

⚠ **Clients are hidden from an agent's *view*, not from its inbox.** Precisely:

- `office peers` and `office broadcast` select `port_type == "tmux"`, so a client is in
  nobody's peer list and no agent-initiated broadcast reaches it. That filter
  predates clients — it was built to hide `api` and `host` — and it is why
  per-client addressing cost almost nothing.
- **An agent does see a client's name when one writes to it.** A message sent
  with `as: "telegram"` arrives as `[message from telegram]`, and replying by
  that name is the whole point. "Agents never see clients" would be wrong.
- **A raw `destination: "all"` does reach clients**, unlike `office broadcast`.
  The switch fans out over roster *fields* and by invariant 8 cannot read a port_type,
  so it has no way to exclude them. Client-side filtering is what `office
  broadcast` does; the switch does not and structurally could not.
- **`office peers -i`/`--interfaces` is an opt-in exception to the first bullet,
  not a repeal of it.** It prints `api`/`control` roster members on a second,
  explicitly labeled line, never merged into the peer list `-i`-less output
  still returns unchanged. Bare `peers` and `broadcast` are exactly as hidden
  as above; `-i` exists because that hiding, on its own, once cost an agent a
  correct reply to a real client (`LLD-office.md` §4).

`cli` defaults to `claude`. `Message` and `Command` share a payload shape and
differ only in whether the prefix is rendered — see `LLD-port-tmux` §3 for why
that one difference is the whole security boundary.

### `StartAgent` publishes desired state; `StopAgent` attempts actual-state teardown synchronously

`StartAgent` publishes optional profile and provider state plus the launch key,
then enrols the agent; tmuxhost reconciliation asynchronously creates its window
and starts the CLI in it. Desired launch state is visible before the roster row that triggers
reconciliation, while actual window creation still follows enrolment.
`StopAgent` removes the roster row, purges classified identity state, and attempts to kill
the window synchronously inline (`tmuxhost.reconcile_once` also cleans up any orphaned window later).

For a fresh tmux membership carrying a `correlation_id`, `StartAgent` atomically
publishes the per-agent `window.cause` key with roster visibility. The first
successful `window_created` atomically consumes that one-shot value and carries
it as `correlation_id`, joining asynchronous actual state to
`start_agent_accepted` without making control wait. A failed window creation
retains the cause for the next attempt. If reconciliation finds the window
already present, it consumes any marker without emitting a join: that envelope
did not cause the existing window, and retaining its id would falsely attach a
later crash recovery. A real-agent recovery with no marker emits a valid
`window_created` with `correlation_id` absent; `__init__` placeholder creation
does not emit that lifecycle event. Consumption happens before
logging, deliberately preferring a missing join over a stale false join if
tmuxhost dies at that boundary. Idempotent starts do not publish a cause because
they require no new window.

The cause and roster row are one Lua write boundary because neither sequential
ordering is truthful: cause-first could strand an id when roster publication
fails, while roster-first could let tmuxhost create before the id is visible.
If the operation commits but its reply is lost, control conservatively emits
`start_agent_incomplete`; Redis nevertheless contains both values. The Lua
script writes the roster first because Redis does not roll back earlier script
writes after a command error: a server-side failure may expose a cause-less
membership, but never a cause without the membership that request published.

⚠ **For `port_type: "api"` there is only enrolment.** A client enrolment writes a
roster row and stops: no launch key, no home, no window, no CLI. `StopAgent`
removes the row and purges classified identity state, touching no tmux; retained
data such as its inbox survives re-enrolment. Unqualified, the sentence above
is false for half the participants.

⚠ **"the mailbox" was too narrow, and naming keys here would go stale the same
way.** Build 22 replaced the enumeration with a classified set — `flock.bus`
holds which resources are per-agent state, `purge_agent` deletes them, and a test
fails when a new resource is added without being classified. Read the set, do not
restate it.

```
  StartAgent            StopAgent
    SET  …:networking:launch cli   HDEL roster networking
    HSET roster networking tmux    purge classified identity state
    tmuxhost reconciles      kill the window
```

**Desired state before its reconciliation trigger on start; roster before actual
state on stop.** Launch/profile/provider values are written before the roster
row, because that row can immediately trigger tmuxhost. On stop, the roster row
is removed before the window. The roster is desired membership and tmux is
actual state, so the host converges the second toward the first.

⚠ Reversed on stop it does worse than fail: kill the window first, crash before
the `HDEL`, and the host finds a roster row with no window and **recreates it**.
The agent you just killed comes back, one poll later, looking like the host
working correctly.

tmuxhost is the only creator. A repeated `StartAgent` with changed CLI, profile,
provider, or resume setting removes the stale window after publishing the new
desired state; tmuxhost then rebuilds it through the same path used at boot. An
unchanged hire is idempotent and leaves the running window alone.

⚠ **Session history and re-hiring**: `StopAgent` cleans up Redis state and kills
the active tmux window, but deliberately leaves `/workdir/<name>` and prior CLI
session files on disk (`~/.claude[-<profile>]/projects/...`,
`~/.codex[-<profile>]/sessions/...`, `~/.gemini/antigravity-cli/history.jsonl`).
When `StartAgent` is subsequently called for that agent name without an explicit
`resume: false` (`--fresh`), `tmuxhost` auto-detects existing session history for
that workspace and launches with the CLI's native resume command (`startAgent claude --resume`,
`startAgent codex resume --last`, `startAgent agy --continue`), attaching to the
most recent session recorded for that directory. Explicit `resume: true` forces
resumption; explicit `resume: false` starts a fresh session.

⚠ **`launch` is a separate key, not a roster value.** `LLD-bus-and-switch` §3.2
is explicit that nothing beyond the port_type lives in the roster — *"what is started
in its window, its credentials, its configuration — belongs to whichever module
starts it, not to membership."* Putting `cli` in the roster value would make
every reader of the MAC table parse an agent's configuration.

## 7. Seeding the roster

Roster ownership is now split deliberately: the container seeds boot members,
and the control port_type owns runtime enrolment and retirement. The entrypoint writes
the initial roster at start, from the environment, before any module runs. It
is a `HASH` of `agent → port_type`
(`LLD-bus-and-switch` §3.2) — the MAC table:

```bash
HSET pod:$POD:tenant:$TENANT:roster backend tmux frontend tmux systems tmux api api
# AGENTS=backend:tmux,frontend:tmux,systems:tmux  plus the fixed api row
```

`HSET` is idempotent, so bringing the container up twice converges
(`LLD-container` §5).

The tenant-level `accounts` SET is the canonical list of configured CLI
accounts:

```text
SMEMBERS pod:$POD:tenant:$TENANT:accounts
```

`setup.sh` writes the complete list as `FLOCK_ACCOUNTS`; entrypoint replaces
and seeds this SET before removing the startup variable. Both `office hire` and
the `StartAgent` fabric opener read this one resource. Config directories are
derivative state and never establish that an account exists. An absent key is
deliberately permissive for tenants created before the resource shipped; a
present key makes an unknown profile a visible refusal naming the canonical
accounts. Hand-seeding a directory does not add an account — setup must run
again.

⚠ **Corrected in build 03 — this used to say "nothing else writes the roster".**
`StartAgent` and `StopAgent` `HSET` and `HDEL` it; this runtime write path is how
`office hire` and `office letGo` work.

What still holds, and is the part worth keeping: **the switch never writes the
roster and never reads its values** — only `HKEYS`/`HEXISTS`, fields not values.
That is invariant 8, and it is structural rather than a convention. The write
path belongs to `flock.control`, reached only through the bus.

## 8. What the api reads

The board is **four LISTs per agent**, using the resource names
`LLD-bus-and-switch` §3.1 already shows:

```
  <prefix>:tasks.todo     LIST     FIFO — take pulls from the head
  <prefix>:tasks.doing    LIST     at most one entry
  <prefix>:tasks.hold     LIST     parked deliberately
  <prefix>:tasks.done     LIST     status: done | cancelled
```

Not one HASH. A board is ordered — "take your next task" is only meaningful
against a FIFO — and a hash gives no order.

⚠ **Corrected in build 11 — a transition is `LPOP`/`LREM` then `RPUSH`, not
`LMOVE`.** This used to promise `LMOVE`, and build 11 made that impossible: a
ticket is **mutated in flight**. `take` stamps `started_ts` and sets `status`, so
the value pushed is not the value popped, and `LMOVE` moves a value untouched.
The moment tickets carried state, the atomic single-command move was gone.

That is safe here for the reason h-office gives: **one agent consumes its own
column**, so there is no second reader to tear against, and the pair needs no
locking.

⚠ **The residual risk is a crash between the two commands, which loses the
ticket.** Small window, single process, and no reason to pay for a Lua script or
a WATCH loop before it happens once — but it is a real hole and it should be
written down rather than discovered. Not the same claim as the one this
paragraph used to make.

⚠ **Corrected in build 11 — an entry is a ticket, and the api parses it.** This
clause used to read *"entries are opaque strings and the api does not parse
them"*, which was right when **nothing wrote boards**: the shape was undefined,
so returning bytes through was the only honest thing to do. Boards are written
now, by `office add` and the `AddTicket` opener, and **the shape is pinned
here**:

```
  v           int      schema version, 1
  id          str      the ticket id
  title       str      one line
  description str      "" when absent
  created_by  str      who raised it
  status      str      todo | doing | done | hold | cancelled
  created_ts  str      ISO-8601 UTC
  started_ts  str?     null until taken
  done_ts     str?     null until done
  held_ts     str?     null until held; not cleared by a later take
  priority    str?     present only when set
  related     [str]?   present only when non-empty; ticket ids, unvalidated
```

⚠ **`created_by` is whatever the writer supplied** — the envelope's `source`
for an `AddTicket`, the caller for `office add`. Nothing resolves or verifies it,
for the same reason `source` itself is unverified (`HLD` invariant 2). An
earlier draft claimed the bus resolved it; it does not.

⚠ **`related` names other ticket ids and nothing looks them up.** Set with
`office add --related <id>[,<id>...]`, stored by the `AddTicket` opener as a
list of strings and by nothing else — a related id may name a ticket on a
different agent's board entirely, or nothing at all, and neither `add` nor
`list` ever reads another board to check. It is a structural stand-in for
writing "see ticket &lt;id&gt;" in a description, not a cross-board join.

So the api parses each entry as JSON and returns an object. `status`,
`started_ts` and `id` are structured fields anything may read.

⚠ **`title` and `description` stay opaque.** That is where the original rule
still holds and where it was always aimed — they are *text*, and nothing parses,
summarises or truncates them.

⚠ **Tolerate both shapes.** Build 10 tickets and bare strings still exist on live
boards. An unparseable entry is skipped, never a `500` for the whole response —
one bad row must not cost the other agents their board.

An agent with no board is `[]` and
`200`, never `404`: `LLD-api` §2 requires that agents holding nothing still
appear.

Response shapes, since every read is a fixed shape and a request can never name
a key (`LLD-api` §5, §8):

```json
GET /agents/backend           { "agent": "backend", "port_type": "tmux",
                              "depths": { "ingress": 0, "egress": 0, "dead": 0 },
                              "presence": { "state": "idle", "since": "…",
                                            "last_activity": "…" } }

GET /agents/backend/board     { "agent": "backend",
                              "todo": [], "doing": [], "hold": [], "done": [] }

GET /board                  { "agents": [ { "agent": "backend", "todo": [], … },
                                          { "agent": "frontend",   … } ] }

GET /agents                 { "agents": ["api", "backend", "frontend", "host", "systems"] }
```

A list rather than a map for `GET /board`, so roster order is expressible and
the entry shape matches the single-agent route exactly.

### Observation keys — builds 18, 20, 27, 28

```
  <prefix>:agent:<name>:activity          STREAM   the CLI's own records, tailed
  <prefix>:agent:<name>:activity.offset   STRING   where the tail has read to
  <prefix>:agent:<name>:presence          HASH     working | idle | unknown
  <prefix>:agent:<name>:blocked           HASH     { since, stream_id }
  <prefix>:agent:<name>:doing.alerted     STRING   "<ticket_id>:<crossing>", set by the watchdog
  <prefix>:agent:<name>:todo.alerted      HASH     { <ticket_id>: <crossing>, … }, set by the watchdog
  <prefix>:agent:<name>:hold.alerted      HASH     { <ticket_id>: <crossing>, … }, set by the watchdog
  <prefix>:alerts                         STREAM   tenant-level, MAXLEN ~ 1000
```

⚠ **`doing.alerted`, `todo.alerted` and `hold.alerted` do not gate the alerts
stream.** They are the dedupe keys for a *different* mechanism —
`LLD-watchdog` §2a/§2b/§2c's direct paste into the tenant `lead`'s pane when a
ticket has sat in `doing`, `todo` or `hold` past
`WATCHDOG_DOING_ALERT_SEC`/`WATCHDOG_TODO_ALERT_SEC`/`WATCHDOG_HOLD_ALERT_SEC`.
This is the one case where the watchdog writes to a participant's `ingress`
rather than only to `<prefix>:alerts`, and it is addressed to the `lead`
alone, never to the ticket's own agent (`HLD` §8c). `doing.alerted` is a
STRING because `tasks.doing` holds at most one ticket; `todo.alerted` and
`hold.alerted` are HASHes keyed by ticket id because `tasks.todo` and
`tasks.hold` can each hold several aging tickets at once, tracked
independently and dropped once a ticket leaves that state.

⚠ **`blocked` is written by the WATCHDOG.** It is a delivery verdict retained
instead of discarded: set on `unverified`, deleted on `verified`. One writer, and
no screen is read to produce it.

⚠ **This said "the switch, not the watchdog" until 2026-08-22**, and it was true
until 2026-08-17, when activity tailing, presence sampling and delivery
verification moved out of the fabric into `flock.watchdog`. The switch now owns
the window-log tail and retention; anyone chasing `blocked` in `switch/` will not
find it (`watchdog/verification.py`).

⚠ **`blocked` does not mean "stuck".** It means *a delivery was judged unverified
and nothing has been consumed since*. Measured with each precondition proved: it
catches a wedged CLI, and both claude and codex at a login prompt. Do not restate
it as a general health signal.

⚠ **It is written only for an agent with activity history.** No history means no
verdict — the marker is dropped and logged `delivery_unjudged`. A new agent
therefore cannot be `blocked` until it has spoken once.

⚠ **`office` never prints a lifecycle record to stdout.** It runs in an agent's
pane, so its stdout is the agent's screen. It sets `FLOCK_LOG_QUIET=1` for the
duration of its own command; the record still reaches the window log the switch
tails. Daemons do not set it and keep logging to the container's stdout. An agent
read one of those records off its own screen and reasoned its way to Redis
(`HLD` §10a).

⚠ **An agent may run against a model provider of its own.** `<prefix>:agent:<n>:provider`
holds a **name**; the address lives in the tenant environment as
`PROVIDER_<NAME>_URL` / `_MODEL` / `_TOKEN` / `_SMALL_MODEL` / `_KIND`. A url in a
Redis value would be a provider an agent could read and change, and the roster
holds membership and port_type, nothing else. Written before roster visibility, like
`launch` and `profile`, or the window is built against the wrong model.

⚠ **Such an agent uses no account credential** — the CLI talks to the server
directly. The watchdog's credential check does not apply to it and a missing
login is not a fault for it.

⚠ **`alerts` and `credential.alerted` are tenant-level**, so `StopAgent` must not
purge them. `credential.alerted` is a HASH keyed `<account>:<cli>` holding the
last status alerted — `absent` / `unknown` / `expiring` / `expired` — so an alert
fires once per **state change** rather than once per pass. It is tenant-level
because one account can be shared by several agents. The rest are
per-agent and are in the classified set the teardown test enforces —
`AGENT_STATE_RESOURCES` and `AGENT_DATA_RESOURCES` in `bus/resources.py`.

### The client mailbox — build 12

```
  <prefix>:agent:<name>:pending.verify   STREAM   MAXLEN ~ 100

Written by the port **before** the paste, judged and dropped by the switch.

⚠ **Before, not after — this was a bug.** Marking afterwards lost a sub-second
race: six deliveries landed and five read unverified because the agent's reply
beat the marker. Marking first costs nothing if the paste then fails, because the
delivery genuinely did not arrive.

⚠ **Only `{claude, codex}` are marked — an allowlist, never a denylist.** The
rule was once "not agy", which marked plain bash windows that could never
confirm anything. A CLI whose activity cannot be tailed must be skipped by
default, not by having been remembered. Resources
compose with a **dot** — `tasks.todo`, `activity.offset`, `pending.verify` — and
each part is validated as a segment.

⚠ **Do not widen the resource rule to admit a name.** Pick a name that fits. It
was widened once to allow an underscore, which also silently bypassed the
all-digit rejection for resources — a relaxation nobody asked for, in service of
a name that had a conforming alternative.

  <prefix>:agent:<client>:inbox   STREAM   MAXLEN ~ 1000
```

One per api client, written by `deliver_api` and read by the api. **One field,
`envelope`, carrying the envelope as JSON**, and the stream entry id is the
cursor a client resumes from — there is no second sequence number.

⚠ **The first Stream in the system, and the cursor is the reason.** Activity and
`pending.verify` followed for the same reason; everything
else is a LIST because a queue is consumed once, by one reader, and then gone. A
mailbox is not: several clients may read it at their own positions, and a
disconnected one has to be able to say *I had up to here*. `XRANGE` gives that
catch-up and `XREAD BLOCK` gives the SSE loop its wait — both built in, where a
LIST would need a hand-rolled sequence counter.

```json
GET /agents/telegram/messages   { "agent": "telegram",
                                  "messages": [ { "cursor": "…-0", "source": "backend",
                                                  "kind": "Message", "payload": {…} } ],
                                  "next_cursor": "…-0" }
```

`GET /agents/{client}/messages/stream` is the same objects as SSE, resumable with
`Last-Event-ID`. Both require the client to be enrolled with port_type `api` — `404`
otherwise, including for a tmux agent, which has no mailbox.

⚠ **`POST /agents/{agent}/envelopes` accepts `"as": "<client>"`**, checked against
the roster, so an agent sees `[message from telegram]` and replies by name like
anyone else. Omitted, the source is `api`. It is a *declaration*, not
authentication — one shared token means any holder can claim any enrolled name,
which is no weaker than `source` already being forgeable.

## 9. Shared environment

Supplied by the container, with deliberate per-process handoff where credentials
or boot-only configuration must not reach agent windows (`LLD-container` §4).

| | |
|---|---|
| `POD`, `TENANT` | the prefix every Redis key is built from |
| `AGENTS` | comma-separated `name:port_type` pairs; boot-only roster seed, unset before tmux starts |
| `ROSTER_POLL_SECONDS` | default `5`. Shared by the switch and tmuxhost |
| `ACTIVITY_POLL_SECONDS` | default `2`. How often the **watchdog** tails CLI session files for the activity feed |
| `VERIFY_AFTER_SECONDS` | default **`120`**. How long a delivery marker waits for later **`input`, `output` or `tool`** activity before being reported unconfirmed |
| `WATCHDOG_ENABLED` | default `1`. ⚠ **`0` does NOT stop the process** — it silences *alerting* only. The observers keep running, because the api door, the console and the Telegram client all read what they write, and exiting took those down with it |
| `WATCHDOG_INTERVAL` | default `30`. Seconds between passes |
| `WATCHDOG_STALL_SEC` | default `600`. A ticket open longer than this **may** alert |
| `WATCHDOG_SILENCE_SEC` | default `300`. …**and** the window quiet this long |
| `WATCHDOG_COOLDOWN_SEC` | default `3600`. One alert per ticket within this |
| `WATCHDOG_CREDENTIAL_WARN_DAYS` | default `7`. Warn before a **refresh** token expires |
| `WATCHDOG_DOING_ALERT_SEC` | default `900`. A ticket open longer than this is pasted directly into the tenant **lead**'s pane (`LLD-watchdog` §2a), independent of `WATCHDOG_STALL_SEC`/`_SILENCE_SEC`; re-fires once per crossing of this same period |
| `WATCHDOG_TODO_ALERT_SEC` | default `300`. A `todo` ticket unpicked longer than this is pasted directly into the tenant **lead**'s pane (`LLD-watchdog` §2b), same mechanism and re-fire rule as `WATCHDOG_DOING_ALERT_SEC` |
| `WATCHDOG_HOLD_ALERT_SEC` | default `3600`. A `hold` ticket parked longer than this is pasted directly into the tenant **lead**'s pane (`LLD-watchdog` §2c), same mechanism and re-fire rule as the other two — deliberately an hour, not minutes, since `hold` is often a legitimate wait |
| `BOARD_DONE_MAX` | default `500`. Newest finished tickets retained per agent |
| `DEAD_MAX` | default `500`. Newest dead-lettered envelopes retained per agent |
| `WINDOW_LOG_MAX_BYTES` | default `8388608` (8 MB). Consumed window-log spool size before truncation |
| `REDIS_URL` | infrastructure-process handoff; loopback Redis, never inherited by agent windows or published |
| `AGENT_NAME` | in an agent's window only |
| `API_TOKEN` | handed only to both external doors; never inherited by agent windows |
| `API_BIND`, `SESSION_BIND` | bind for each door; exposure policy is decided by the container's published-host configuration |
