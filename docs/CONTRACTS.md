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

The Redis wire is **hard v3**: a frame is a fixed 191-byte ASCII header then an
opaque JSON body (`bus/envelope.py:14`), and anything else is rejected rather
than upgraded — as v2 rejected flat v1. HTTP send request bodies are port input and keep their existing
shape; mailbox consumers receive the layered frame and must read L2/L3.

⚠ **The switch calls `members` and `is_member`, never `port_type`.** Reading the value
is what would tell it how an agent is hosted, which invariant 8 forbids. That is
the whole of the split: the switch reads the table's fields, a port reads its
values.

An opener is `callable(envelope: dict) -> None`. A normal return means opened;
raising `DeadLetter(reason)` asks `receive` to park and log it instead. The
opener never writes the dead list or emits a terminal record itself. Registering
one is how a kind becomes deliverable; `LLD-port-tmux` §3 is the tmux
implementation of one.

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
    # load-buffer → paste-buffer -p → delay → Enter → delete-buffer
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

`LLD-bus-and-switch` §4 promises two records per component and **six** across a
delivered envelope's life — `sent, popped, forwarded, kick_started, received,
opened`. ⚠ **`kick_started` (build 65) made it six**; this line said five until
2026-08-15, as did three other docs.

⚠ **A broadcast does not have six**: `forwarded` is emitted once with `count=N`
and `destination:"all"` (`switch/service.py:169`), so it cannot be joined per
recipient. `analyse-run.py`'s `STAGES` is the operative list.

The contract is and that a crash shows up as "popped, no outcome".
That only works if the records join, so the shape is a contract.

**One JSON object per line.** Daemons write records to stdout for the container
to collect. `office` runs inside an agent pane, so it suppresses stdout and
appends to `/home/ubuntu/.flock/window.log.jsonl`; the switch tails that spool to
its own stdout. Board mutations also append their separate operator history to
`TASK_RECORD` (default `/home/ubuntu/.flock/tasks.jsonl`). These files are
transport paths for records, not competing lifecycle schemas.

| Field | | |
|---|---|---|
| `ts` | required | RFC3339, UTC, milliseconds |
| `module` | required | component name, such as `bus`, `switch`, `port`, `tmuxhost`, `api`, `session`, `watchdog`, `control`, `tmux` or `container` |
| `event` | required | see below |
| `stream_id` | envelope events only | the join key; absent on lifecycle records |
| `correlation_id` | when known | |
| `source`, `destination` | when known | `destination` is the participant the record is about; receive-side broadcast records name the actual recipient, not literal L2 `all` |
| `reason` | on a failure | why it dead-lettered or was refused |
| `count` | on a broadcast | how many copies were written |
| `task_id` | on a board move | the entry's `id` |
| `bytes` | on window-log truncation | consumed spool bytes removed |

⚠ `task_id`, not `id` — a bare `id` sits beside `stream_id` and `correlation_id`
in the same record and reads as a third identity for the same thing.

The five successful-unicast custody records are a **set, not a sequence**. Join them by
`stream_id`; do not reconstruct custody by sorting timestamps. `send` appends
before it emits `sent`, so a fast switch can emit `popped` before the source
emits `sent` even though custody is correct.

Events, in custody order (not guaranteed log or timestamp order):

```
  sent          send wrote an egress                     (flock.bus.doors)
  popped        the switch took it off an egress         (switch)
  forwarded     … and wrote an ingress                   (switch)
  dead_lettered terminal alternative to forward/open    (switch or port)
  received      receive took it off an ingress           (flock.bus.doors)
  opened        an opener ran to completion              (port)
```

A module may also log its own **lifecycle** — `started`, `stopped`, `error` —
which is not about any envelope. Those carry no `stream_id`: it is the join key
for one envelope's life, and a synthetic value like `"system"` in that field
makes the five records of a real **unicast** envelope harder to find, not
easier. ⚠ **A broadcast leaves three shared records plus a `received`/`opened`
pair per recipient.** The pairs name the actual receiving participant even
though the unchanged frame still carries L2 `destination: all`;
`forwarded.count` is the cardinality. N receive-side pairs sharing one
`stream_id` are correct for a broadcast. More than one record for the same
`(stream_id, recipient)` is a duplicate; for unicast, more than one record for
the `stream_id` is therefore still a defect. `stream_id`
is required on the six events above and absent on the rest. A parsed frame can
carry its `stream_id` on all six possible events above, but a successful
unicast has five:
`dead_lettered` replaces a later success path rather than joining it.

⚠ A malformed frame may have no trustworthy identifier. Its `popped` and
`dead_lettered` records therefore carry `stream_id: unknown` and are not
joinable to a custody set. What remains knowable is the source egress queue,
the time it was popped, the parse reason, and the sender's dead queue retaining
the raw value. The literal field being present does not make it a join key.

`send_refused` is **not a sixth custody record**. It says the sending port
rejected a request before assembly and before any egress write, so there is no
enqueued envelope whose custody could be joined to the five-record set. It
carries `source`, `destination` and `reason`, but no `stream_id`.

Four joinable **attempt records** describe work around custody without claiming
a handover: `send_failed` means an assembled frame was not written to egress;
`forward_failed` means a popped frame was not written to ingress;
`kick_started` means the switch successfully spawned a port process; and
`kick_failed` means it could not. The kick records name the actual destination
port, including one record per recipient of a broadcast. They do not prove that
the port ran, popped, or delivered anything; only `received` and `opened` make
those later claims.

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
`Popen` returns or `kick_failed` when spawning raises, then throws the process
handle away. Those attempt records do not claim that the port ran or delivered.

⚠ **The switch must set `signal.signal(signal.SIGCHLD, signal.SIG_IGN)` at
start.** Without it the kernel keeps every exited kick as a zombie until the
switch reaps it, and CPython only reaps at the top of the *next* `Popen` — so
during a burst the reaping lags the spawning. Measured: **65 zombies** for a
100-envelope run, **40 still present at rest** afterwards, clearing only when
traffic resumed. `SIG_IGN` makes the kernel reap them immediately and the count
never leaves zero.

This is safe *because* the kick is fire and forget (rail 3): `SIG_IGN` makes
`wait()` and `poll()` unusable, and we never call them — a return code is
exactly what rail 3 forbids caring about.

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
office send -a <destination> <text>...    # kind defaults to Message
office broadcast <text>...              # tenant broadcast, everyone but you
office peers | hire | letGo | pause | resume
office add | list | take | done | cancel | hold | delete
office status [<agent>]                 # presence, open ticket, last activity
```

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
| `StartAgent` | `control` | `{"agent": "networking", "cli": "claude", "port_type": "tmux"}` | enrols, creates the window, starts the CLI |
| `StopAgent` | `control` | `{"agent": "networking"}` | reverses all three |
| `PauseAgent` | `control` | `{"agent": "networking"}` | stops the CLI, keeps the agent and its queues |
| `ResumeAgent` | `control` | `{"agent": "networking"}` | starts the CLI again and kicks delivery for queued ingress |
| `AddTicket` | `tmux` | `{"title", "description", "priority"}` | writes a ticket to that agent's `tasks.todo` — and **pastes nothing** |

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
logs `board_write_confirmed`. A failed or unconfirmed write logs
`board_write_failed` and raises `DeadLetter`; it never creates a
`pending.verify` marker or a `blocked` state because no CLI consumption is
expected for a board write.

`port_type` defaults to `tmux` and accepts `tmux` or `api`; `cli` defaults to `claude`.

⚠ **`port_type: "api"` enrols a client, and creates no window.** A phone app, a web
front end and a Telegram wrapper are each a roster row and a mailbox — nothing
else. `StopAgent` on one removes the row and **purges the client's classified
identity state**, retaining its mailbox and other data and touching no tmux.

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

`cli` defaults to `claude`. `Message` and `Command` share a payload shape and
differ only in whether the prefix is rendered — see `LLD-port-tmux` §3 for why
that one difference is the whole security boundary.

### `StartAgent` and `StopAgent` are the whole operation — for a tmux agent

`StartAgent` publishes optional profile and provider state plus the launch key,
then enrols the agent; tmuxhost reconciliation creates its window and starts the
CLI in it. Desired launch state is visible before the roster row that triggers
reconciliation, while actual window creation still follows enrolment.
`StopAgent` reverses all three. They are not enrolment alone.

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
or provider removes the stale window after publishing the new desired state;
tmuxhost then rebuilds it through the same path used at boot. An unchanged hire
is idempotent and leaves the running window alone.

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
  v           int     schema version, 1
  id          str     the ticket id
  title       str     one line
  description str     "" when absent
  created_by  str     who raised it
  status      str     todo | doing | done | hold | cancelled
  created_ts  str     ISO-8601 UTC
  started_ts  str?    null until taken
  done_ts     str?    null until done
  priority    str?    present only when set
```

⚠ **`created_by` is whatever the writer supplied** — the envelope's `source`
for an `AddTicket`, the caller for `office add`. Nothing resolves or verifies it,
for the same reason `source` itself is unverified (`HLD` invariant 2). An
earlier draft claimed the bus resolved it; it does not.

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
  <prefix>:alerts                         STREAM   tenant-level, MAXLEN ~ 1000
```

⚠ **`blocked` is written by the switch, not the watchdog.** It is the switch's
own delivery verdict retained instead of discarded: set on `unverified`, deleted
on `verified`. One writer, and no screen is read to produce it.

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
| `ACTIVITY_POLL_SECONDS` | default `2`. How often the switch tails CLI session files for the activity feed |
| `VERIFY_AFTER_SECONDS` | default `10`. How long a delivery marker waits for a later `input` event before being reported unconfirmed |
| `WATCHDOG_ENABLED` | default `1`. `0` exits the process cleanly |
| `WATCHDOG_INTERVAL` | default `30`. Seconds between passes |
| `WATCHDOG_STALL_SEC` | default `600`. A ticket open longer than this **may** alert |
| `WATCHDOG_SILENCE_SEC` | default `300`. …**and** the window quiet this long |
| `WATCHDOG_COOLDOWN_SEC` | default `3600`. One alert per ticket within this |
| `WATCHDOG_CREDENTIAL_WARN_DAYS` | default `7`. Warn before a **refresh** token expires |
| `BOARD_DONE_MAX` | default `500`. Newest finished tickets retained per agent |
| `DEAD_MAX` | default `500`. Newest dead-lettered envelopes retained per agent |
| `WINDOW_LOG_MAX_BYTES` | default `8388608` (8 MB). Consumed window-log spool size before truncation |
| `REDIS_URL` | infrastructure-process handoff; loopback Redis, never inherited by agent windows or published |
| `AGENT_NAME` | in an agent's window only |
| `API_TOKEN` | handed only to both external doors; never inherited by agent windows |
| `API_BIND`, `SESSION_BIND` | bind for each door; exposure policy is decided by the container's published-host configuration |
