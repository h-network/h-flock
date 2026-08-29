# LLD — the bus and the switch

> **Status: built and running.** Decisions taken are stated as such; what is
> deferred is listed in §7.

## 1. Purpose & layer

A **participant** is anything that talks on the bus: a terminal agent, an app
client, or a control provider. It is a roster row and a name. A port
produces onto the participant's egress and consumes from its ingress on its
behalf; its port_type says what is attached at the far end. The bus carries envelopes
and the switch forwards them between participants. What a participant *is* — a
process, a session, a daemon, an HTTP handler — is not the bus's concern and is
deliberately absent from this document.

Three layers, and the point of the split is that each is ignorant of the layer
above it.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  L1  BUS       tenancy prefix · envelope · queue primitives  │
  │                a pure library. no daemon, no loop, no        │
  │                lifecycle, no opinion about what a message    │
  │                means                                         │
  ├──────────────────────────────────────────────────────────────┤
  │  L2  SWITCH    subscribe set · sender from the queue key     │
  │                resolve destination → queue · dead-letter       │
  │                observation and retention pass                │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  EDGE      adapters: send onto <prefix>:egress           │
  │                          receive from <prefix>:ingress       │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the switch must forward an envelope
without knowing anything about how the receiving agent is implemented or
hosted.** If routing and delivery live in one component, the bus can only ever
reach the kind of agent that component knows how to drive.

That independence is structural at import time. Switch modules import specific
bus submodules, and the stable `flock.bus` facade resolves exports lazily, so a
fresh import of `flock.switch.service` does not load `flock.bus.doors` (and
cannot acquire `send` or unreplied tracking as an accidental startup dependency).

**Everything reaches the bus through a port.** Not a workaround for agents
that cannot speak Redis — the rule for all of them. For registered VABs, `send`
writes what its participant emits onto egress and the receive boundary takes
what arrives on ingress and passes it to an opener. The switch owns the middle,
where it pops egress and writes ingress. There is one explicit fallback: an unknown roster port_type
uses `deliver_unroutable`, which drains the current ingress snapshot, validates
each item and parks it with an `unroutable port_type` reason because there is no
opener table to dispatch to.

What differs between participants is only the far end. One delivery routine
types into a terminal window; another appends the unchanged envelope to a
client's mailbox. The bus side of the port is identical for every one of
them.

Opening is where an envelope stops being opaque. The port reads the header to
choose a kind-specific opener; that opener may interpret the payload to paste a
message, mutate lifecycle state or add a ticket. Which is precisely the line the
switch cannot cross: it never touches the payload at all, not even to pass it
through.

### The two Redis clients

The codebase uses two distinct Redis clients, partitioned strictly by process lifecycle:

1. **Short-lived spawned tools (`flock.bus.resp.Redis`)**: CLI commands and edge ports (`port/send.py`, `port/deliver.py`, `office/cli.py`) execute frequently in transient processes where import time directly impacts latency (a port kick costs 659–911 ms). They use the minimal, hand-rolled RESP2 client (`flock.bus.resp.Redis`) implementing exactly 24 one-shot commands without external library dependencies.
2. **Long-lived daemons (`redis.Redis` via `redis-py`)**: Background services (`switch/service.py`, `watchdog/service.py`, `api/app.py`) import full `redis.Redis` to leverage advanced capabilities like multi-key pipelining (`pipeline()`), list trimming (`ltrim()`), element inspection (`lindex()`), key existence probing (`exists()`), and set mutations (`sadd()`, `sismember()`).

In tests, `FakeRespRedis` in `tests/conftest.py` strictly adheres to the 24-method surface of `flock.bus.resp.Redis`, ensuring short-lived tool tests cannot pass against capabilities production lacks, while `FakeRedis` extends it with daemon methods.

### The two doors

**Normal envelope traffic enters and leaves an edge through two logical doors.** The
switch necessarily performs raw queue operations in the middle; the unknown-port_type
fallback above is the sole edge exception. The doors are the normal edge
inspectors:

| | Does | Rejects |
|---|---|---|
| **send** | builds and encodes the envelope, writes the egress selected by `source`, then best-effort logs and tracks `unreplied` from the L2 header alone | nothing malformed can be constructed |
| **receive boundary** | validates what came off ingress, dispatches on `kind` to an opener, logs | unknown kind → dead-letter |

`send` constructs the scoped key and encodes the frame before entering the
`RPUSH` exception window. A failure there therefore proves no write was
attempted and is never called `send_unknown`. Once `RPUSH` returns, custody has
changed: a logging or unreplied-bookkeeping failure is swallowed so observation
cannot make a committed send look failed to the caller.

The switch treats custody logging as observation, never control flow. Once
`BLPOP`, ingress admission, dead-letter append, or `Popen` has returned, a
stdout/logging exception is swallowed and routing continues. A Redis admission
exception remains `forward_unknown` and is still re-raised; failure to emit that
record cannot replace the original Redis exception.

The receive-side `_emit_for_recipient()` helper follows the same rule. Its
records are best-effort after `LPOP`/`BLPOP` or an atomic burst drain, so a log
output failure cannot prevent opener dispatch, interrupt a drained batch, or
escape after a dead-letter/opened outcome. Both `receive()` and the tmux/api
and OpenShell burst delivery paths use this helper.

As secondary post-egress bookkeeping, `send()` also classifies closing
acknowledgments on directed tmux-to-tmux `Message` edges. It stores only a
streak and timestamp in the source agent's `acks` hash; content never enters
Redis. The atomic 120-second update and exact frozen classifier are specified in
CONTRACTS. Non-ack peer messages delete the directed field, and any tracking
fault is observed without changing the already-committed send result.

For registered VABs, each check therefore has one logical home. An envelope
built by `send` cannot be structurally malformed because only one thing builds
it. The `receive()` library function implements the one-envelope control path;
the tmux and api burst routines apply the same parse, dead-letter and terminal
logging boundary to every item in their drained snapshot. `deliver_unroutable`
duplicates that parse/park boundary for the exceptional port_type case. `send` does **not**,
however, authenticate its caller: its
`source` argument selects both the envelope field and the egress prefix. The
agent CLI supplies that argument from `AGENT_NAME`. At the switch, the popped
egress key is authoritative: a mismatched `source` field is overwritten with
the queue owner and logged as `source_stamped`. This makes attribution honest,
but does not authenticate which process wrote that queue or prevent a direct
caller from choosing another participant's valid egress prefix.

**`send`'s one piece of interpretation stays at the header, not the payload.**
It reads both `source` and `destination` port_type with two of its own roster
lookups — ⚠ **not** a reuse of `require_allowed` above, which checks policy
export/import *tags*, a separate hash, and never touches port_type; an
earlier version of this doc claimed otherwise, caught by `bus`'s
module-boundary sweep. It opens or clears one HASH field in `unreplied` — a
client (`api` port_type) reaching a `tmux` agent opens a count against that
client; that agent replying to the same client clears it. This reads `l2`
and the roster, the same inputs the switch's own forwarding decision already
reads; it never inspects `payload`. Full shape
and the watchdog rule that consumes it are LLD-watchdog §2d.

A consequence worth stating: **an agent never learns a queue name.** Components
at the edge use `send` and `receive`; a terminal agent sees the `office` verbs
and the name of whoever it is addressing.

**Why a switch exists at all.** A source could write straight into its
destination's queue, and then no switch would be needed — this is what h-office
does, and its envelope has no `destination` field at all: the address is the queue,
and the courier derives everything from the key it popped. Simpler, and it works.

**The switch is what buys scale.** A source names a **destination**, never a
route, so where that destination actually is can change without touching a single
sender:

- **another tenant.** A source cannot know a foreign tenant's topology, and
  should not. Cross-tenant routing has one home (§7) instead of needing every
  source to learn a second address space.
- **another base.** An agent moving from a tmux window to something else changes
  nothing for anyone addressing it, because nobody was addressing a queue.
- **gone.** An unresolvable name dead-letters in one place with a reason, rather
  than each sender discovering it separately.
- **tenant-scoped keys.** One switch watches only the validated prefixes for its
  configured tenant. The running deployment puts one tenant and one Redis in a
  container; the prefix keeps the addressing scope explicit, but is not an
  authorization boundary between direct callers inside that container.

⚠ Note what this is *not* justified by, because the tempting argument is the
weak one: it is **not** about hiding topology from producers. In this build every
terminal agent has `redis-cli` and can reach loopback Redis using its known
default address, even though credential-bearing Redis environment variables are
deliberately removed before its window is created. One read the whole roster
within minutes of starting. Topology is a command away. The switch earns its
place by being the single component that has to change when the answer to
"where is that destination" changes — not by keeping the answer secret.

## 2. The model, in one picture

Producers emit frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌──────────── tenant — pod:acme:tenant:hq:agent:* ───────────────────┐
  │                                                                    │
  │  L3 EDGE                                       L2 SWITCH           │
  │                                                                    │
  │  ┌───────┐  produce  ┌────────────────┐ BLPOP  ┌────────────────┐  │
  │  │       │──────────►│ …:backend:egress │───────►│                │  │
  │  │ backend │           └────────────────┘        │     switch     │  │
  │  │       │  consume  ┌────────────────┐ RPUSH  │                │  │
  │  │       │◄──────────│ …:backend:ingress│◄───────│  destination →   │  │
  │  └───────┘           └────────────────┘        │     queue      │  │
  │                                                │                │  │
  │  ┌───────┐  produce  ┌────────────────┐ BLPOP  │  from_key →    │  │
  │  │       │──────────►│ …:frontend:egress   │───────►│     sender     │  │
  │  │  frontend  │           └────────────────┘        │                │  │
  │  │       │  consume  ┌────────────────┐ RPUSH  │                │  │
  │  │       │◄──────────│ …:frontend:ingress  │◄───────│                │  │
  │  └───────┘           └────────────────┘        └───────┬────────┘  │
  │                                                        │ won't     │
  │   api and host are participants too —                  ▼ forward   │
  │   same prefix shape, same pair                 ┌────────────────┐  │
  │                                                │ …:<from>:dead  │  │
  │                                                └────────────────┘  │
  └────────────────────────────────────────────────────────────────────┘
```

The supported agent command never writes to another agent's ingress queue. It
calls `send` with its own `AGENT_NAME`, and the switch decides what happens next.
Routing decisions therefore happen in exactly one place. This is not a Redis
authorization boundary: a direct library caller can supply another valid name
as `source` and thereby select that participant's egress queue. The switch
attributes the envelope to that queue; the current shared Redis credential does
not establish which process wrote it.

## 3. Addressing

### 3.1 The prefix

Levels interleave, `tag:value` at each step:

```
  pod:<pod>:tenant:<tenant>:agent:<agent>

  e.g. pod:acme:tenant:hq:agent:backend
```

| Level | Holds | Who cares |
|---|---|---|
| `pod` | tenants | a gateway, when routing between tenants |
| `tenant` | participants | one switch serves exactly one tenant |
| `agent` | resources | the named participant itself (the tag name is historical) |

**Interleaved rather than tags-first**, so every level is a genuine prefix of
the level below it. That is what makes one pattern able to span levels:

```
  SCAN MATCH pod:acme:tenant:hq:*                    everything in the tenant
  SCAN MATCH pod:acme:tenant:hq:agent:*:tasks.todo   one resource, every agent
```

With the tags grouped at the front the shapes would not nest — a tenant key and
an agent key would diverge immediately after the tag block, and no single
pattern could cover both.

**The tags are reserved words.** No pod, tenant, agent or resource may be named
`pod`, `tenant` or `agent`. Without that rule a tenant resource called `agent`
is indistinguishable from the start of an agent path. The segment regex already
validates every name, so this is one more check in the same place — cheaper than
a marker segment that would lengthen every key to solve the same problem.

`all` is reserved too, for the same reason one level up: it is the broadcast
destination (§4), so an agent by that name would be unaddressable.

Putting the agent in the address rather than in the queue name makes a future
per-agent ACL scope expressible: a credential could be scoped to
`~pod:acme:tenant:hq:agent:backend:*` and reach that agent's keys and nothing
else. No such isolation is enforced in the running development office; agents
share one OS user and can reach the tenant's loopback Redis. Scoping at the
tenant level could not express a narrower policy later.

**Resources are a dotted suffix, not a level.** A resource is not an address —
nothing routes to it — so it does not get a tag. Dots group related resources
without adding depth:

```
  pod:acme:tenant:hq                 : roster        a tenant's resource
  pod:acme:tenant:hq:agent:backend     : egress        an agent's resources
  pod:acme:tenant:hq:agent:backend     : tasks.todo
  pod:acme:tenant:hq:agent:backend     : tasks.doing
  pod:acme:tenant:hq:agent:telegram  : inbox         an app client's mailbox
  pod:acme:tenant:hq:agent:backend     : activity      privacy-reduced CLI events
  pod:acme:tenant:hq:agent:backend     : pending.verify delivery evidence to judge
  pod:acme:tenant:hq:agent:backend     : delivery.markers usage attribution evidence
  pod:acme:tenant:hq:agent:backend     : usage.requests request-id deduplication
  pod:acme:tenant:hq                   : usage         retained tenant usage records
```

Tenant and agent addresses can carry resources; the current `prefix()` requires
both pod and tenant and therefore has no pod-only resource form. Envelope queues
are LISTs. Retained or independently judged observations use Streams: an app `inbox`, an agent's
`activity`, its transient `pending.verify` and `delivery.markers` observations,
and the tenant `usage` feed. The distinction is the
reader model: a queue is consumed once, while a mailbox or observation feed can
be read at independent positions and verification markers are deleted only
after judgment.

Address-segment rule: `^[a-z0-9][a-z0-9-]{0,62}$` — lowercase alnum and dash —
plus a rejection of all-digit values because tmux resolves a numeric window name
as an index. No glob metacharacters, so a prefix is safe to drop into a Redis
`SCAN MATCH`. No underscore, so that per-agent filesystem directories named
`<a>_<b>` stay unambiguous to split. A resource is one or more such segments
separated by dots; each sub-segment is validated, may not be a reserved word,
and is subject to the same all-digit rejection.

**Every Redis key goes through `prefix()`.** There is no API that yields a flat
Redis key. This prevents tenant-scope collisions and makes the scope of every
state access checkable, even though the running deployment gives each tenant
its own container and Redis. The invariant must survive every change.

### 3.2 Participants

Everything addressable is a participant. There is no separate addressing
concept for terminal agents and app clients:

| Participant | port_type | Notes |
|---|---|---|
| terminal agents | `tmux` | dynamic; an enrolled name backed by a window and CLI |
| app clients | `api` | dynamic; an enrolled name backed by a mailbox, with no window |
| sandbox agents | `openshell` | dynamic; an enrolled name backed by a disposable OpenShell sandbox, with no tmux window |
| `api` | `api` | fixed default identity for the REST door |
| `host` | `control` | fixed lifecycle-control provider |
| `gateway` | deferred | future cross-tenant traffic (§7) |

Named participants come from a roster that changes while the switch is running,
so the subscribe set is **derived from the roster and rebuilt when it changes**,
not read from a constant. Adding a kind of participant is adding a name and a
port_type delivery routine, not altering the addressing scheme — that is what makes
the scheme scale.

**The roster is live state, not boot configuration.** Participants join and
leave while the switch runs, and the subscribe set follows. It is also the only
source of membership: the switch builds its egress subscribe set from it, and
anything that needs "every participant in this tenant" — aggregating a board,
fanning out a raw broadcast — walks the same list rather than scanning the
keyspace. One source, several readers.

The tenant also has a scalar `<prefix>:lead`. Boot writes the **first ordered
name in `AGENTS`**, rather than deriving authority from the roster hash or a
sorted name. The switch does not route on it; `office peers` and the generated
agent guides read it so leadership remains stable when names happen to sort in
a different order.

Since several modules read it, its shape is part of the contract:

| | |
|---|---|
| **Key** | `pod:<pod>:tenant:<tenant>:roster` |
| **Type** | `HASH` |
| **Field** | a participant name, matching the segment rule |
| **Value** | its **port_type** — the virtual agent base attached to it: `tmux`, `api`, `control`, `openshell` |

**This is the MAC address table.** A name resolves to a port and to what is
attached to that port, and nothing else about the participant lives here.

The port itself is not stored, because it is computed:
`prefix(pod, tenant, agent, "ingress")` is a pure function of the name. Nothing
is duplicated, so nothing can drift.

**The switch reads the fields. Port-side delivery reads the values.**

| | Reads | Asks |
|---|---|---|
| switch | `HKEYS`, `HEXISTS` | who exists; does this destination resolve |
| port/control | `HGET <agent>` | how do I deliver to or stop this one |

That split is what makes invariant 8 structural rather than a promise: the
switch never reads the column that says how an agent is hosted, so it cannot
know. A hash answers both membership questions in a single command, exactly as a
set did, so nothing is lost by carrying a value alongside.

**Why the port_type is here and not in the address.** Putting it in the key —
`…:port_type:tmux:agent:frontend:ingress` — would make the queue self-describing, but
moving an agent between bases would rename its entire keyspace: queues, board,
dead-letter, everything, with in-flight envelopes stranded in the old queue.
§3.1 already rejected exactly this trade — a marker segment lengthening every key
to answer a question one lookup answers.

**Why it is not in the envelope.** A source knows its own name and the name it
is addressing, and nothing else (§1). If an envelope carried `port_type: tmux`, every
source would need to know how its destination is hosted, and would be wrong the
moment that changes. The port_type is a property of the destination, not of the message.
This holds regardless of the header-versus-payload line — reading a header is
legitimate (§5), but the sender has no business knowing this in the first place.

**Noticing a change: the readers that need it poll.** A hash has no wake-up, so
each re-reads it. There is no notification to enable, and no obligation on
whatever writes the roster beyond writing it.

Two long-lived readers need polling and one does not. The **switch** reads the
roster when it builds each `BLPOP` set and once for each maintenance pass. The
**tmux host**, with no queue to block on, polls on a loop of its own. The
**port** does not poll at all: it holds nothing between deliveries, so it has
no set to keep in step. It is told which participant to deliver for, by the
thing that just wrote to that participant.

`ROSTER_POLL_SECONDS`, from the environment (`LLD-container` §4), defaults to 5
and bounds the switch's blocking pop and the tmux host's reconciliation loop.
With an empty roster there is no queue to block on, so the switch sleeps for the
same interval rather than spinning against repeated roster reads.
The switch's maintenance cadence is separately configurable as
`MAINTENANCE_POLL_SECONDS`, default 2; it shortens the switch's block when its
next housekeeping pass is due. The watchdog's filesystem observation cadence
is `ACTIVITY_POLL_SECONDS`, also default 2. These are distinct controls because
roster convergence, switch housekeeping, and filesystem observation have
different costs and owners.

Staleness is bounded by the relevant polling interval and is harmless in the two obvious
directions. A participant added a moment ago is simply not routed to yet; once a
removed destination disappears from the switch's next roster read, new envelopes
addressed to it dead-letter at their senders. Neither is a race worth closing,
and closing it — keyspace notifications, a watched version key — would add a
write-side obligation to every roster mutation.

Nothing else lives in the table. Whatever a participant *is* beyond its port_type —
what is started in its window, its credentials, its configuration — belongs to
whichever module starts it, not to membership.

Lifecycle branches on port_type. For `tmux`, desired state comes before actual state
in both directions: `StartAgent` writes the optional profile, optional provider
name and launch key **before the roster row becomes visible**. That row is
tmuxhost's reconciliation trigger, and tmuxhost is the sole window creator — so
boot and hire cannot drift on lead, account, or provider resolution. Re-hiring
an existing name with changed configuration removes its stale window only after
the new desired state is visible; the host recreates it canonically. `StopAgent`
reads the port_type, removes the roster
row, purges all classified identity state, and only then kills the window.
Queues and board columns are retained data, so re-hiring the same name gets a
clean identity and its old work. That ordering makes a crash recoverable through
tmux-host reconciliation. There remains a narrow start interval in which
delivery can reach the roster row before its window exists and dead-letter;
reversing the desired-state-before-roster order would instead allow a window to
be built from incomplete state. For `api`, enrolment writes only the roster row
— no launch key, home, window or CLI — and stopping performs the same identity
purge without touching tmux. Its retained inbox is data, not identity state, so
unread entries survive retirement and are available if the client is enrolled
again. The fixed `api` and `host` participants cannot be stopped through
`StopAgent`; removing either would remove a tenant door rather than retire a
dynamic participant.

For `openshell`, StartAgent publishes policy/launch/profile and the roster row,
then synchronously creates the agent's disposable sandbox through the gateway;
there is no tmuxhost reconciler or window. StopAgent removes membership and
classified identity state before synchronously deleting that sandbox. The
delivery port atomically drains an ingress snapshot and runs each supported
kind through a one-shot sandbox operation, including a bus reply for Message or
Command output (`LLD-port-openshell`).

Retention includes both directions of envelope data. A retired participant's
ingress waits to be consumed after re-enrolment, and its egress waits to be
routed after the name returns to the roster. The latter may deliver an envelope
authored before retirement under the re-hired identity; this is the same
name-continuity decision as retaining unread client inbox entries and board work,
not a queue-drain omission. Retirement removes identity state, not queued data.

### 3.3 Queues

Direction is relative to the **participant**, as it is on a network device:
egress is traffic leaving the participant, ingress is traffic arriving at it.
The switch sits on the opposite end of both.

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<prefix>:egress` | LIST | the participant | the switch |
| `<prefix>:ingress` | LIST | the switch | the participant's port |
| `<prefix>:dead` | LIST | the switch, or an edge port | entries by hand; depth by `api` |
| `<prefix>:inbox` | STREAM | the `api` delivery routine | app clients, by cursor |
| `<prefix>:activity` | STREAM | the watchdog's session tailer | api reads and presence/verification sampling |
| `<prefix>:pending.verify` | STREAM | the tmux delivery opener | the watchdog's verifier |
| `<prefix>:delivery.markers` | STREAM | the tmux delivery opener | the watchdog's usage correlator |
| `<prefix>:usage.requests` | SET | the watchdog activity tailer | the same tailer's per-agent request deduplication |
| `<prefix>:usage.attributed` | SET | the watchdog activity tailer | the same tailer's per-agent delivery-attribution deduplication |
| `<prefix>:blocked` | HASH | the watchdog's verifier | office and watchdog reads |
| `<prefix>:unreplied` | HASH | the `send` door itself | the watchdog's §2d (LLD-watchdog) |
| tenant `<prefix>:alerts` | STREAM | the watchdog | api polling and SSE, by cursor |
| tenant `<prefix>:usage` | STREAM | the watchdog activity tailer | `office usage`, by range |

Envelope transport uses lists, not pub/sub, so a backlog survives a consumer
restart. The mailbox is retained, not consumed: `XRANGE` and `XREAD` let polling
and SSE readers keep independent cursors. Delivery appends one field named
`envelope`, capped approximately at 1,000 entries; the stream entry ID is the
cursor. The remaining Streams carry observations rather than envelopes and are
described below.

### 3.4 Observation and maintenance passes

None of these jobs sits in an envelope's data path. The watchdog runs the first
three observation jobs every `ACTIVITY_POLL_SECONDS` (default 2); the switch
runs the final two housekeeping jobs in its own loop every
`MAINTENANCE_POLL_SECONDS` (default 2). Keeping filesystem and Stream scans in
the separate watchdog process prevents a slow observation from stalling
forwarding (`src/flock/watchdog/service.py:373-407`,
`src/flock/switch/service.py:192-224`).

1. **Tail session files.** For each Claude, Codex or Antigravity agent, the
   tailer reads only bytes after the stored `activity.offset` in the newest
   session JSONL. It appends privacy-reduced events to `<prefix>:activity`:
   `input`, `output`, or `tool`, with a tool's **name only**. Arguments, paths
   and content have no field in the event. The Stream is approximately capped
   at 1,000 entries.
   CLIs without a supported session format produce no feed. Usage records in
   the same supported transcripts are separately appended to the tenant
   `<prefix>:usage` Stream. A request ID is deduplicated in the agent's
   `usage.requests` Set; when the first usage after a delivery marker can be
   correlated, `usage.attributed` prevents that stream ID being claimed twice.
   Absent correlation is omitted rather than guessed.

   ⚠ **A Codex session belongs to the workspace in its own `session_meta`, not
   to its directory.** `CODEX_HOME` is an account directory: agents using the
   default account or the same named profile share it. The tailer accepts a
   rollout for an agent only when its recorded `cwd` is `/workdir/<agent>`; a
   rollout with absent or different metadata is unknown and is not attributed.

   ⚠ **Offsets belong to paths, not to "the newest file".** When a different
   session file becomes newest its offset starts at zero deliberately — skipping
   to the previous file's byte count would discard the beginning of the new
   session. `activity.offset` retains a map of consumed offsets by path, so if
   modification times later make a previously tailed file newest again it
   resumes there instead of replaying the whole file. The reader accepts the
   original single-path state shape and rewrites it as the map.
2. **Sample presence.** The newest activity timestamp becomes a per-agent
   `presence` hash with `state` (`working`, `idle`, or `unknown`), `since`, and
   `last_activity`. `PRESENCE_WORKING_SECONDS`, default 30, is the working
   horizon; `since` is preserved while the state does not change. One reverse
   Stream read fetches at most the newest ten events for each agent, enough to
   step past a malformed newest observation without pulling the whole
   approximately-capped activity history to obtain one timestamp.
3. **Judge delivery evidence.** Before pasting a `Message`, the tmux port
   appends a marker to `<prefix>:pending.verify` when the agent's launch CLI is
   in the explicit `{claude, codex, agy}` allowlist. The marker is written
   **before** the paste: the CLI can record the resulting `input` in less time
   than a post-paste write takes, making the event appear older than its marker
   and a successful delivery look unverified. Measured live, that race
   misclassified five of six messages.

   ⚠ **The allowlist is a capability claim, not a list of exceptions.** A CLI
   is marked only when the watchdog can tail its session format. The old rule
   "anything except agy" also marked bare shell windows, whose deliveries can
   never be confirmed. An unknown future CLI must therefore remain unmarked
   until its activity feed is supported.

   Once a marker is at least `VERIFY_AFTER_SECONDS` old (default 120), the watchdog
   first asks whether the agent has ever produced observable activity: either
   `activity.offset` or the activity Stream exists. Without that history the
   agent is `unknown`, not blocked. The marker is deleted and a
   `delivery_unjudged` record states why; waiting longer would preserve the same
   category error with a larger constant.

   ⚠ **The first delivery to a new agent is never judged.** A new Claude session
   can create no session file, activity event or offset for longer than the
   verification window even though it is healthy. Skipping that delivery avoids
   a false `blocked` state that clients act on, at the deliberate cost of not
   detecting a genuinely lost first paste. No terminal is read to make the
   distinction.

   For an agent with activity history, a later activity event confirms the
   marker. Otherwise the verifier logs `delivery_unverified` and retains that
   first verdict in `<prefix>:blocked` as `{since, stream_id}`. A later verified
   delivery deletes the hash; another unverified delivery does not reset
   `since`. Either way the pending marker is deleted after judgment. The
   `waited` log field is the elapsed time from that marker's timestamp to the
   judgment, not the configured minimum; scheduler delay may make it larger
   than `VERIFY_AFTER_SECONDS`.

   ⚠ **`blocked` means an unverified delivery and no verified delivery since.**
   It does not mean the CLI is stuck. Credential-free Claude and Codex were both
   measured at their login prompts, with prior activity making them judgeable;
   both deliveries were unverified and set `blocked`. By contrast, an agent
   with no activity history receives no verdict at all. Bare shells produce no
   verifiable activity, so their deliveries are never marked and they cannot
   acquire this state.

   ⚠ **An unverified delivery is surfaced and never re-pasted.** Verification
   distinguishes "later CLI activity was observed" from "no later activity was
   observed"; it cannot distinguish an unsubmitted paste from text that landed
   in a stopped process, picker or slow CLI. A retry cannot help while the block
   remains, and after a human clears it both copies may be consumed.

   The choice is therefore possible loss over possible duplication: preserve
   at-most-once delivery, retain `<prefix>:blocked`, emit the watchdog alert and
   log `delivery_unverified` with the explicit no-retry reason. This also obeys
   the operational ceiling without adding a retry queue or timer. The trade is
   deliberate because an agent may execute a duplicated instruction twice,
   while a surfaced unverified instruction can be assessed and resent by a
   human who knows whether that is safe. The verifier never retries, re-pastes,
   or dead-letters the envelope.
4. **Carry window logs to stdout (switch).** Agent-side `office` records are written to
   `/home/ubuntu/.flock/window.log.jsonl`; the switch tails complete lines from
   a tenant byte offset so `sent` joins the central envelope log. If the spool
   exceeds `WINDOW_LOG_MAX_BYTES` (default 8 MiB), it is truncated only after
   the offset has reached the current end. A partial tail is left intact, so a
   record cannot be dropped between passes. A complete line containing invalid
   UTF-8 emits `window_log_decode_error` with its byte position and length, is
   skipped, and advances the offset; one poisoned line therefore cannot replay
   earlier records forever or prevent later truncation. An incomplete final line
   still waits for completion.

   `office` runs inside the agent's pane, so it sets `FLOCK_LOG_QUIET=1` only
   for the duration of its command. `log_record` still appends the record to the
   window file, but does not also print bus telemetry onto that pane. The switch
   subsequently tails the file and emits the record centrally, so observability
   is preserved without exposing module names, stream IDs or correlation IDs on
   the agent's own screen. Daemons do not set the quiet flag and continue to log
   to their stdout. Each h-flock JSON record on container stdout is also copied
   to `FLOCK_CUSTODY_FILE`; compose mounts that path from a named volume so the
   evidence survives ordinary container removal. The mirror is a byte copy, not
   a second schema, and never raises into delivery (`src/flock/bus/logging.py:27-51`).
5. **Apply retention (switch).** One pipeline trims each agent's `tasks.done` and `dead`
   LISTs to the newest `BOARD_DONE_MAX` and `DEAD_MAX` entries (both default
   500). Centralising the caps here covers every writer.

Each job isolates and records its own failure. An observer failure does not stop
the watchdog loop; switch housekeeping failure does not stop forwarding.

### 3.5 The watchdog boundary

`flock.watchdog` is a separate tenant process, not another switch pass. Its
observers write `activity`, `presence`, delivery verdicts and usage records; its
alerting pass reads `presence` and `blocked`, board state, tmux window-activity
metadata and credential files, then appends factual records to the tenant
`<prefix>:alerts` Stream. Ordinary watchdog alerts are for a human through the
api's polling and SSE routes and do not notify an agent directly. The scoped
exception is an overdue ticket in `doing`, `todo` or `hold`: the watchdog places
a `Message` directly on the lead's ingress and kicks its port, as HLD §8c
describes. Keeping it out of the switch loop means a slow external observation
cannot stall forwarding.

This is the bus-facing boundary, not the watchdog's complete design. Its
three-signal stall rule, credential/account walk, cooldowns, alert shapes and
failure policy are specified in [`LLD-watchdog.md`](LLD-watchdog.md); they are
independent of the addressing and custody decisions this document owns.

**Having written an ingress queue, the switch kicks delivery for that
participant.**

```
  RPUSH …:agent:frontend:ingress
  kick  flock.port frontend
```

**Only egress is watched for envelope delivery, and that asymmetry is the whole
design.** You have to sit on a queue when writes come from somewhere you do not control: nobody knows
when a participant will send, so the switch blocks on egress. But *every* ingress
write is made by the switch itself (invariant 3), so the switch already knows
the instant one lands. A second process waiting to be told something the writer
already knew is pure redundancy — and it is redundancy with a cost, because
waiting means a held ingress connection per participant, forever, for an office
that is idle almost all of the time.

Three rails keep the kick from turning the switch into a middlebox. They are
invariants, not intentions:

1. **The switch reads the header and the roster's fields. Never a payload, never
   a roster value.**
2. **The kick is one fixed command with an agent name.** Not a type, not a
   table of adapters, not a choice. The executor is ours, so it does its own
   `HGET` to find the port_type and dispatches itself. The switch hands over a name.
3. **Fire and forget, exactly like the envelope.** No wait, no return code and no
   retry. Failure to start the process is logged and ignored; the envelope stays
   safely on ingress. The moment the switch tracks a kick outcome it is holding
   delivery state, and that is the slide this list exists to prevent.

Rail 2 is what keeps invariant 8 true here. The switch does not know a port
by name, by type or by capability — it knows one command, and the knowledge of
what to do lives on the far side of it.

**One port owns a participant at a time.** The number of port processes started
for `frontend` is the number of kicks fired. Without serialisation, two of them
can interleave against one window: two pastes, then two `Enter`s, fusing both
messages into one input. `send-keys` targets a window, not a delivery.

A **busy tag** serialises them, written by the port and cleared by it:

```
  HSETNX …:tenant:<t>:delivering  frontend  <started_at>  1 = acquired; deliver
                                                          0 = wait and retry
  HDEL   …:tenant:<t>:delivering  frontend                on finishing it

  kicked while another port holds the tag?  retry HSETNX until this one acquires it
```

`HSETNX` is the right primitive because testing absence and claiming the field
must be one atomic operation. `HEXISTS` followed by `HSET` has a race: two
ports can both observe no tag and then both claim it, recreating the concurrent
delivery this guard exists to prevent. A waiter loops on `HSETNX` rather than
exiting, then dispatches according to the participant's port_type:

- `tmux`, `api`, `openshell`, and the unknown-port fallback atomically drain the complete
  ingress snapshot with one Lua `LRANGE` + `DEL`. Tmux concatenates each
  consecutive run of `Message` envelopes into one paste; non-Message kinds open
  individually in arrival order. Api and unknown-port delivery handle every
  drained item individually.
- `control` retains the library `receive(..., blocking=False)` path and `LPOP`s
  one lifecycle envelope.

Every accepted ingress write produced a kick. Consequently, after one tmux or
api port drains a burst, already-waiting redundant kicks can acquire the tag,
find an empty queue, and exit. An envelope arriving after the atomic drain has
its own kick and remains in Redis until some port acquires the tag.

⚠ **A crashed port leaves the tag set, and that is deliberate.** Nothing
expires it, nothing checks whether the holder is alive, and nothing takes over.
Recovering automatically would mean guessing a timeout longer than the slowest
delivery, or a liveness check, or a heartbeat — machinery in the delivery path to
handle a case that should not be happening. §4 already made this trade for
envelopes: **do not recover, guarantee it is visible.**

And it is visible, without anything new being built:

```
  HGETALL …:delivering            who is mid-delivery, and since when
  LLEN …:agent:frontend:ingress        what has piled up behind it
```

The log bounds which failure it was. A port that dies **before** consuming
ingress leaves the queue intact — nothing lost, tag set, depth growing. On the
control path, one that dies after `LPOP` leaves `received` with no terminal
record if parsing completed. On a burst path, the atomic drain transfers the
whole snapshot into that process: parsed items have `received` and later an
`opened` or `dead_lettered`, but a crash can lose unparsed drained items before
they acquire a port-side record. That is the receiving edge's equivalent of the
switch's destructive-pop window in §4, and closing it would require a
reserve/ack journal rather than the current at-most-once transport. A wedged
port and a dead one still do not need distinguishing automatically: something
is wrong with frontend, go and look.

A port that diagnoses or repairs its own stuck deliveries is a real thing to
want, and it is not for a build that does not yet work end to end.

Note this property was free under a blocked-consumer-per-agent design — one
consumer, so nothing else could pop. It is not free here. That is the price of
adapters that do not exist between deliveries, and it is worth paying.

A dead-lettered envelope is parked under the prefix of **whoever failed to move
it on**, which differs by where it died:

- **The switch** parks under the *sender's* prefix. An envelope that failed
  because its destination could not be resolved has no destination prefix to park
  under, and the sender is the party who needs to see it.
- **A port** parks under *its own*. The envelope arrived; the failure was at
  this end. Parking it under the sender's prefix would put a port outside
  its own agent's keys, which §6.3 forbids.

The opener contract has exactly two declared terminal outcomes: return normally
only after opening the envelope, or raise `flock.bus.DeadLetter(reason)` to
reject it. The one-envelope `receive()` path and the burst delivery loops catch
that signal, park the raw envelope under the receiving agent and emit
`dead_lettered`; only a normal return emits `opened`. Openers must not write the
dead list or emit their own terminal record. Keeping custody and the terminal
record at the receive boundary prevents one stream from being logged as both
dead-lettered and opened, and applies the rule to every registered kind rather
than to a list of remembered opener implementations.

The sentinel uses an exception for an expected outcome, which is less ordinary
than a return value. That cost is deliberate: wrapper openers naturally
propagate it, while a return sentinel can be discarded by a wrapper and turn
the rejection back into `opened`. Other opener exceptions remain failures;
the one-envelope and burst paths park and log those as `opener failed` without
stopping the port.

## 4. Semantics

**Fire-and-forget, like UDP.** The source gets no acknowledgement, there is no
retransmit, and nothing at the bus layer promises delivery. A terminal agent
replies by addressing the source's name. When that source is an app client,
its `api` delivery routine stores the reply in the client's mailbox for polling
or SSE. That is an application return path, not a transport acknowledgement: a
reply may never come.

**Order is preserved per queue**, because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is tenant-scoped.** A raw broadcast fans out to the participants of
one tenant and stops there, the way a broadcast domain ends at a switch.
Reaching another tenant is explicit addressing, never implicit fan-out.

**`destination: "all"` is the broadcast address.** The switch walks the roster and
writes one copy to each member's ingress, skipping the sender derived from the
popped egress key — a participant does not receive its own broadcast.

That raw protocol broadcast includes every roster participant, so an enrolled
app client receives a copy in its mailbox. `office broadcast` is deliberately a
different, conversational surface: it sends N individual `Message` envelopes
only to port_type `tmux`, excluding app clients and fixed plumbing. The switch still
knows only the first form and never reads a port_type.

It has to be a value of `destination` and not anything else, because routing is
`destination` and nothing else (§6.4) — a `kind` of `Broadcast` would make the
switch branch on `kind`, which is exactly the coupling §5 exists to prevent. And
it has to be a name rather than a pattern: §3.1 excludes glob metacharacters so
that a prefix is safe in a `SCAN MATCH`, which rules out `*`. A reserved name is
what is left, and reserving it costs one entry in a list that already exists.

**Broadcast does not rewrite its destination.** Each copy keeps `destination:
"all"`, so a receiver can tell it was addressed to the room rather than to it.
The separate port-stamping rule below may rewrite a mismatched `source`
before either unicast or broadcast forwarding; no other field is changed.

The fan-out is one pop and one call to the shared
`flock.bus.queues.admit_ingress()` primitive over *n* ingress keys. Its Lua
operation first checks every depth against `INGRESS_MAX`, then pushes every
copy only if all recipients have capacity. A full recipient therefore rejects
the whole broadcast: no ingress receives a copy, the original frame is parked
once under the sender's dead list with `destination: "all"`, and no port is
kicked. The check and pushes are one atomic Redis execution, so a consuming port
cannot open a check-then-write or write-then-rollback race. This is stronger
than the transport's fire-and-forget promise; callers must still not infer an
acknowledgement or retry from it. A successful outcome is one `forwarded` record
carrying `count=N`, not *n* records. One pop, one outcome, as §4 requires.

Unicast uses the same shared admission operation with one key. The primitive
owns only atomic admission and reports the rejected participant and observed
depth; configuration, logging, dead-lettering, and kicking remain caller
policy. At capacity the switch appends nothing and parks the frame under the
sender; it never appends and compensates with `RPOP`. The bound remains a count
of queued envelopes rather than bytes.

A broadcast into a tenant of one is *n* = 0 — a successful broadcast to nobody,
not a dead-letter. There was no unresolvable destination; there was simply no one
else there.

**Loss after `popped` is visible; one earlier window is not.** `BLPOP` is
destructive, and Redis returns the removed value before the switch can emit its
first record. If the process or connection fails between those two operations,
the envelope can disappear without a `stream_id` record. Closing that window
requires a reserve/ack journal or a different queue primitive, which would be a
delivery-guarantee change and is deliberately not introduced here. Once
`popped` is emitted, the switch writes a second outcome record; a later crash is
therefore visible as "popped, no outcome". The transport remains at-most-once,
with no retry.

Switch and door connections deliberately use redis-py's zero command-retry
default. Retrying a failed destructive `BLPOP` is unsafe: the server may have
removed and returned an envelope even when the client never received the
reply, so replaying the command could remove a second envelope. A later loop
iteration may reconnect for later work, but the failed pop itself is never
reissued automatically.

`send` and `receive` log at their own ends too, so a delivered **unicast**
envelope leaves six transport records across its life:

```
  sent          the source's own end          (flock.bus.doors)
  popped        the switch took custody       (switch)
  forwarded     … and what it then did        (switch)
  kick_started  the switch woke the opener    (switch)
  received      the port took custody         (port)
  opened        … and what it then did        (port)
```

⚠ **`kick_started` was added in build 65 and this list did not gain it until
2026-08-21** — the prose above said "six" while the block showed five, for the
second time in this file's life. See the note below, which records the same
defect at four.

An opener may add a kind-specific lifecycle record between `received` and
`opened`; `AddTicket`, for example, emits `board_write_confirmed`, so its complete
trace has **seven** records. A corrected source adds `source_stamped` between
`popped` and `forwarded`; the event carries the corrected source and names the
original claim in `reason`. ⚠ **The pair-per-component rule no longer holds and
should not be used to check the count**: the switch emits three, not two, because
`kick_started` records an action taken on a *third* party — waking the opener —
rather than custody handed on. `send` has no pair either, because it is the
origin. **Count the list, do not derive it from a rule**; deriving it is what
produced "four" and then "six-listing-five".

⚠ **This said "four" until build 20, and the arithmetic never worked**: two
paired components plus `send` is 1+2+2. It read as true only because `sent` was
written into an agent's pane and never reached the log, so four was what anyone
counting actually saw. The claim was corrected when the record it was missing
started arriving.

A broadcast instead leaves the three shared records `sent`, `popped` and
`forwarded`, then a `kick_started`/`received`/`opened` **triple** per receiving
participant — `service.py:173` kicks each accepted recipient in turn, so the kick
is per-participant and not shared. Those triples retain the envelope address
`destination: "all"`; they are not
per-destination delivery records and cannot be distinguished from each other by
destination field alone. The `forwarded.count` field is the fan-out cardinality.

The `popped` record is emitted only after the destructive `BLPOP`, structural
parse and source stamp. It therefore carries the corrected source when the
claim differed from the egress queue. A malformed envelope has no trustworthy
structural fields, so its `popped` record contains none and is followed by
`dead_lettered`.

**The switch does not read payloads or L3.** It forwards on L2 `destination`, and derives
the sender from the queue the envelope was popped from. Nothing else in the
envelope affects where it goes. The moment routing depends on payload contents
it stops being a switch and becomes a middlebox, and every change to what a
message means becomes a change to the switch.

## 5. The frame

```json
{
  "v": 4,
  "kind": "Message",
  "stream_id": "<hex>",
  "correlation_id": "<hex>",
  "ts": "2026-08-07T18:00:00.000Z",
  "l2": {"source": "<participant>", "destination": "<participant>"},
  "ttl": 16,
  "hops": 0,
  "l3": {
    "source": "<pod>:<tenant>:<participant>",
    "destination": "<pod>:<tenant>:<participant>"
  },
  "payload": { }
}
```

Outer fields are structural and always present. Everything kind-specific lives
inside `payload`, and validating it is the consumer's job, never the bus's.
Unknown top-level fields are ignored, so a newer source cannot break an older
switch.

L2 `destination` is a **participant name, not a queue name**. The port accepts
either a bare destination or a qualified `pod:tenant:participant` address. It
resolves either local form to the same bare L2 destination and preserves the
qualified address in L3. A non-local qualified address fails and is logged at
the sender; routing between tenants is not implemented.

A bare name means "in my tenant". The local switch reads L2 only; qualification
rides through untouched in L3 for a future inter-tenant switch.

`kind` is **opaque to the switch**. Routing is `destination` and nothing else. A
switch that branches on `kind` has to change every time a new kind is added,
which is the coupling this design exists to avoid.

Where `kind` *is* read is at the far edge: the port keeps a `kind` → opener
table and dispatches on it. One opener knows how to put a message in front of an
agent, another does something else entirely. Adding a kind means adding an
opener, and nothing between the two ends changes.

An envelope whose kind has no opener is **dead-lettered and logged**, not
dropped. The `api` port_type deliberately registers a catch-all opener, so every kind
is mailbox data there; tmux and control still dead-letter kinds they cannot open.

L2 `source` and `destination` are header fields, so reading them is not reading
the payload — §6.4 holds.

L2 `source` is **port-stamped attribution**. `send` initially writes the caller's
claim, but before any forwarding the switch compares it with the participant
name in the popped egress key and overwrites a mismatch. It does not reject the
envelope: rejection would let any process able to write that queue destroy its
owner's traffic. A changed value emits `source_stamped`; a matching value adds
no record. This is not agent isolation or writer authentication — all agents are
colleagues inside one development office, using one reachable Redis.

## 6. Invariants

1. **`prefix()` on every Redis key.** No flat Redis keys, anywhere, ever.
2. **L2 `source` is stamped from the popped egress queue before forwarding.** The
   switch uses that queue-derived sender for dead-letter placement and broadcast
   exclusion, overwrites a mismatched claim, and logs `source_stamped` only
   when the value changes. This guarantees queue attribution, not the identity
   of the process that wrote the queue.
3. **Supported participant tools write to their own `egress`; the switch is the
   only supported writer of `ingress`.** This is an API boundary, not an enforced
   Redis ACL: `send(source=...)` accepts any valid participant name. The switch
   remains load-bearing because supported sends name a destination rather than
   writing its ingress directly.
4. **The switch never reads the payload or L3.** It forwards on L2 `destination` and
   derives the sender from the queue key. Nothing else in an envelope affects
   where it goes. Reading a payload to route makes it a middlebox, and every
   change to what a message means becomes a change to the switch.
5. **The bus is lifecycle-agnostic.** It validates the envelope's structural
   fields, while `kind` and the meaning of `payload` remain opaque to the switch.
   Task state and session context live above it.
6. **Envelope queues are lists, not pub/sub.** Retained mailboxes and
   observation records use Streams where cursors or later judgment require
   them; they are not envelope queues.
7. **Nothing in the data path reads a terminal.** Delivery never branches on
   terminal rendering. Observation may inspect session files or tmux metadata and may only
   report, on its own schedule; it never changes the path an envelope travels.
8. **The switch knows nothing about how a participant is implemented.** It reads
   the roster's *fields*, never its *values*, so it cannot know a participant's
   port_type. It kicks one fixed command with a name. This is structural, not a
   convention anyone has to remember.
9. **One bad envelope never stops the loop.** Malformed JSON and an unresolvable
   destination are logged and dead-lettered per envelope. Queue names are generated
   from validated roster members rather than parsed as untrusted envelope data.

## 7. Built extensions and deferred work

The layer split has survived the extensions built above it. The remaining item
is intentionally outside the running single-tenant system; do not solve it
pre-emptively.

*(Concurrent delivery to one participant used to be listed here as open. It is
settled — see §3.3, "one port owns a participant at a time".)*

**Cross-tenant routing.** Not a separate component — a branch in the switch.
When a `destination` does not resolve inside the local tenant, look it up in a
registry of enrolled tenants and write the envelope to that tenant's Redis.
Registration supplies the discovery half; what remains undesigned is the
enrolment handshake, qualified destination names, and what happens to an envelope
for a tenant that is known but offline.

⚠ Keep remote forwarding **off the hot path**. A local forward is a Redis round
trip; a remote one is a network round trip, and doing that inline turns a
microsecond loop into a tens-of-milliseconds one. That is the one thing that
would make subscribe-set fairness matter — see below.

**Participant lifecycle over the bus is built.** A control participant owns the
roster write path, and it is reached over the bus like anything else:

```
  POST /agents/host/envelopes  {"kind":"StartAgent",
                                "payload":{"agent":"networking"}}
        │
        ▼  api egress ──► switch ──► …:agent:host:ingress ──kick──► port host
                                                                        │
                                            port_type `control` → StartAgent opener:
                                            write profile/provider/launch state,
                                            resolve provider, create the window
```

Nothing in the switch or the bus changes to allow this, which is the point. The
host becomes an addressable participant with its own port_type, so it needs a name and
a queue pair and nothing else. `kind` stays
opaque to the switch; the control opener reads it at the far edge, exactly as §5
describes. All three rails in §3.3 hold untouched.

The same mechanism carries `StopAgent`, `PauseAgent` and `ResumeAgent`. Pause
deliberately leaves the roster and window intact; resume clears the marker,
restarts the CLI and kicks once per queued ingress envelope. Runtime lifecycle
writes remain in the control opener; container boot seeding is the other roster
writer and establishes the initial fixed and tmux rows.

`StartAgent` also accepts `port_type: "api"`. That path writes the named client's
roster row and nothing tmux-related. Replies addressed to that name route through
the same ingress and kick, then the API delivery routine appends the envelope to
`…:agent:<client>:inbox`. `StopAgent` removes the row and every classified item
of per-agent identity state; queues and board data remain. The switch
does not change for any of this; it still routes a name without reading its port_type.

For `port_type: "openshell"`, StartAgent publishes launch/profile/policy and the
roster row, then synchronously provisions the real sandbox; StopAgent performs
the classified identity purge and synchronously deletes it. Delivery atomically
drains ingress and resolves the lazy OpenShell handler, with no tmux window or
tmuxhost reconciliation involved (`LLD-port-openshell`).

**The agent-facing command is a deliberately narrow edge.** `office send` and
`office broadcast` treat every token after the destination as literal message
text, including option-looking tokens such as `-a`; explaining an `office`
command to another agent must not let the outer parser consume the inner
command's flags. `office status` is read-only: it combines presence, the single
open ticket and its age, last activity and any `blocked` verdict, but never
creates, clears or repairs those signals.

`office cloneToAll` is the filesystem-shaped exception. It selects live `tmux`
participants, fetches the upstream repository once, clones locally for the
remaining workspaces, and then points **every** clone's `origin` at the supplied
upstream rather than at the first local clone. Existing target directories are
skipped, and `--dry-run` performs no writes.

**The ticket board is pulled at the agent edge.** `AddTicket` is the one bus
delivery that mutates a board: its opener appends to the destination's
`tasks.todo` and pastes nothing. The write does not require a current window;
the opener confirms the returned list length synchronously, while a failed or
unconfirmed write dead-letters. It never uses `pending.verify` or `blocked`,
because an untaken ticket is normal board state rather than an unconsumed
terminal delivery. The destination later moves its own ticket; no command directly
mutates another participant's board. `office take` refuses
while `tasks.doing` is non-empty, so the one-open-ticket rule is explicit rather
than an emergent property of pull delivery. It distinguishes that refusal from
an empty `tasks.todo`, because callers act differently on those outcomes.

Board mutations are recorded by the component that performs them. Both the
`AddTicket` opener and local `office` transitions call the shared
`flock.bus.record_task_event`, which appends one JSONL record to `TASK_RECORD`
and swallows recording failures so history cannot break the mutation. Listing
prints ticket IDs and titles, while taking prints the structured ticket; title
and description remain opaque text.

**Subscribe-set fairness.** `BLPOP` returns from the first non-empty key in
argument order, so a fixed order can starve later queues whenever an earlier
source keeps its queue non-empty. The code makes no claim about source rate:
the switch rotates the sorted key list one position per pass, ensuring that a
permanently busy first queue does not permanently occupy the first position.

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. Anything a participant does with an envelope after
consuming it is out of scope — the bus carries signals, the switch forwards
them, and neither decides what is done with them.
