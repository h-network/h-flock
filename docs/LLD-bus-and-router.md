# LLD — the bus and the router

> **Status: built and running.** Decisions taken are stated as such; what is
> deferred is listed in §7.

## 1. Purpose & layer

A **participant** is anything that talks on the bus: a terminal agent, an app
client, or a control endpoint. It is a roster row and a name. An adapter
produces onto the participant's egress and consumes from its ingress on its
behalf; its VAB says what is attached at the far end. The bus carries envelopes
and the router forwards them between participants. What a participant *is* — a
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
  │  L2  ROUTER    subscribe set · sender from the queue key     │
  │                resolve recipient → queue · dead-letter       │
  │                observation and retention pass                │
  ├──────────────────────────────────────────────────────────────┤
  │  L3  EDGE      adapters: send onto <prefix>:egress           │
  │                          receive from <prefix>:ingress       │
  └──────────────────────────────────────────────────────────────┘
```

The load-bearing test for the split: **the router must forward an envelope
without knowing anything about how the receiving agent is implemented or
hosted.** If routing and delivery live in one component, the bus can only ever
reach the kind of agent that component knows how to drive.

**Everything reaches the bus through an adapter.** Not a workaround for agents
that cannot speak Redis — the rule for all of them. For registered VABs, `send`
writes what its participant emits onto egress and `receive` takes what arrives
on ingress and passes it to an opener. The router owns the middle, where it pops
egress and writes ingress. There is one explicit fallback: an unknown roster VAB
uses `deliver_unroutable`, which directly pops one ingress item, validates it and
parks it with an `unroutable VAB` reason because there is no opener table to
dispatch to.

What differs between participants is only the far end. One delivery routine
types into a terminal window; another appends the unchanged envelope to a
client's mailbox. The bus side of the adapter is identical for every one of
them.

Opening is where an envelope stops being opaque. The adapter reads the header to
choose a kind-specific opener; that opener may interpret the payload to paste a
message, mutate lifecycle state or add a ticket. Which is precisely the line the
router cannot cross: it never touches the payload at all, not even to pass it
through.

### The two doors

**Normal envelope traffic enters and leaves an edge through two tools.** The
router necessarily performs raw queue operations in the middle; the unknown-VAB
fallback above is the sole edge exception. The doors are the normal edge
inspectors:

| | Does | Rejects |
|---|---|---|
| **send** | builds the envelope, writes the egress selected by `producer`, logs | nothing malformed can be constructed |
| **receive** | validates what came off ingress, dispatches on `kind` to an opener, logs | unknown kind → dead-letter |

For registered VABs, each check therefore has one home. An envelope built by
`send` cannot be malformed because only one thing builds it, and `receive` owns
normal ingress validation and terminal logging. `deliver_unroutable` duplicates
that parse/park boundary for the exceptional VAB case. `send` does **not**,
however, authenticate its caller: its
`producer` argument selects both the envelope field and the egress prefix. The
agent CLI supplies that argument from `AGENT_NAME`. At the router, the popped
egress key is authoritative: a mismatched `producer` field is overwritten with
the queue owner and logged as `producer_stamped`. This makes attribution honest,
but does not authenticate which process wrote that queue or prevent a direct
caller from choosing another participant's valid egress prefix.

A consequence worth stating: **an agent never learns a queue name.** Components
at the edge use `send` and `receive`; a terminal agent sees the `office` verbs
and the name of whoever it is addressing.

**Why a router exists at all.** A producer could write straight into its
recipient's queue, and then no router would be needed — this is what h-office
does, and its envelope has no `recipient` field at all: the address is the queue,
and the courier derives everything from the key it popped. Simpler, and it works.

**The router is what buys scale.** A producer names a **recipient**, never a
route, so where that recipient actually is can change without touching a single
sender:

- **another tenant.** A producer cannot know a foreign tenant's topology, and
  should not. Cross-tenant routing has one home (§7) instead of needing every
  producer to learn a second address space.
- **another base.** An agent moving from a tmux window to something else changes
  nothing for anyone addressing it, because nobody was addressing a queue.
- **gone.** An unresolvable name dead-letters in one place with a reason, rather
  than each sender discovering it separately.
- **many tenants on one Redis.** One router watches only the validated prefixes
  for its configured tenant. The present shared Redis credential is not a
  security boundary between direct callers; tenant isolation here is routing
  scope, not authorization.

⚠ Note what this is *not* justified by, because the tempting argument is the
weak one: it is **not** about hiding topology from producers. In this build every
terminal agent has `REDIS_URL` and `redis-cli`, and one read the whole roster
within minutes of starting. Topology is a command away. The router earns its
place by being the single component that has to change when the answer to
"where is that recipient" changes — not by keeping the answer secret.

## 2. The model, in one picture

Producers emit frames; a switch forwards them by address without reading the
payload. That is the whole design.

```
  ┌──────────── tenant — pod:acme:tenant:hq:agent:* ───────────────────┐
  │                                                                    │
  │  L3 EDGE                                       L2 ROUTER           │
  │                                                                    │
  │  ┌───────┐  produce  ┌────────────────┐ BLPOP  ┌────────────────┐  │
  │  │       │──────────►│ …:backend:egress │───────►│                │  │
  │  │ backend │           └────────────────┘        │     router     │  │
  │  │       │  consume  ┌────────────────┐ RPUSH  │                │  │
  │  │       │◄──────────│ …:backend:ingress│◄───────│  recipient →   │  │
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
calls `send` with its own `AGENT_NAME`, and the router decides what happens next.
Routing decisions therefore happen in exactly one place. This is not a Redis
authorization boundary: a direct library caller can supply another valid name
as `producer` and thereby select that participant's egress queue. The router
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
| `tenant` | participants | one router serves exactly one tenant |
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
recipient (§4), so an agent by that name would be unaddressable.

Putting the agent in the address rather than in the queue name is what makes
per-agent isolation structural: a credential can be scoped to
`~pod:acme:tenant:hq:agent:backend:*` and reach that agent's keys and nothing
else. Scoping at the tenant level could not express that.

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
```

Tenant and agent addresses can carry resources; the current `prefix()` requires
both pod and tenant and therefore has no pod-only resource form. Envelope queues
are LISTs. Retained or independently judged observations use Streams: an app `inbox`, an agent's
`activity`, and its transient `pending.verify` markers. The distinction is the
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

**Every key goes through `prefix()`.** There is no API that yields a flat key.
This is what makes many tenants on one Redis safe, and it is the invariant that
must survive every change.

### 3.2 Participants

Everything addressable is a participant. There is no separate addressing
concept for terminal agents and app clients:

| Participant | VAB | Notes |
|---|---|---|
| terminal agents | `tmux` | dynamic; an enrolled name backed by a window and CLI |
| app clients | `api` | dynamic; an enrolled name backed by a mailbox, with no window |
| `api` | `api` | fixed default identity for the REST door |
| `host` | `control` | fixed lifecycle-control endpoint |
| `gateway` | deferred | future cross-tenant traffic (§7) |

Named participants come from a roster that changes while the router is running,
so the subscribe set is **derived from the roster and rebuilt when it changes**,
not read from a constant. Adding a kind of participant is adding a name and a
VAB delivery routine, not altering the addressing scheme — that is what makes
the scheme scale.

**The roster is live state, not boot configuration.** Participants join and
leave while the router runs, and the subscribe set follows. It is also the only
source of membership: the router builds its egress subscribe set from it, and
anything that needs "every participant in this tenant" — aggregating a board,
fanning out a raw broadcast — walks the same list rather than scanning the
keyspace. One source, several readers.

The tenant also has a scalar `<prefix>:lead`. Boot writes the **first ordered
name in `AGENTS`**, rather than deriving authority from the roster hash or a
sorted name. The router does not route on it; `office peers` and the generated
agent guides read it so leadership remains stable when names happen to sort in
a different order.

Since several modules read it, its shape is part of the contract:

| | |
|---|---|
| **Key** | `pod:<pod>:tenant:<tenant>:roster` |
| **Type** | `HASH` |
| **Field** | a participant name, matching the segment rule |
| **Value** | its **VAB** — the virtual agent base attached to it: `tmux`, `api`, `control` |

**This is the MAC address table.** A name resolves to a port and to what is
attached to that port, and nothing else about the participant lives here.

The port itself is not stored, because it is computed:
`prefix(pod, tenant, agent, "ingress")` is a pure function of the name. Nothing
is duplicated, so nothing can drift.

**The router reads the fields. Adapter-side delivery reads the values.**

| | Reads | Asks |
|---|---|---|
| router | `HKEYS`, `HEXISTS` | who exists; does this recipient resolve |
| adapter/control | `HGET <agent>` | how do I deliver to or stop this one |

That split is what makes invariant 8 structural rather than a promise: the
router never reads the column that says how an agent is hosted, so it cannot
know. A hash answers both membership questions in a single command, exactly as a
set did, so nothing is lost by carrying a value alongside.

**Why the VAB is here and not in the address.** Putting it in the key —
`…:vab:tmux:agent:frontend:ingress` — would make the queue self-describing, but
moving an agent between bases would rename its entire keyspace: queues, board,
dead-letter, everything, with in-flight envelopes stranded in the old queue.
§3.1 already rejected exactly this trade — a marker segment lengthening every key
to answer a question one lookup answers.

**Why it is not in the envelope.** A producer knows its own name and the name it
is addressing, and nothing else (§1). If an envelope carried `vab: tmux`, every
producer would need to know how its recipient is hosted, and would be wrong the
moment that changes. The VAB is a property of the recipient, not of the message.
This holds regardless of the header-versus-payload line — reading a header is
legitimate (§5), but the sender has no business knowing this in the first place.

**Noticing a change: the readers that need it poll.** A hash has no wake-up, so
each re-reads it. There is no notification to enable, and no obligation on
whatever writes the roster beyond writing it.

Two long-lived readers need polling and one does not. The **router** reads the
roster when it builds each `BLPOP` set and once for each maintenance pass. The
**tmux host**, with no queue to block on, polls on a loop of its own. The
**adapter** does not poll at all: it holds nothing between deliveries, so it has
no set to keep in step. It is told which participant to deliver for, by the
thing that just wrote to that participant.

`ROSTER_POLL_SECONDS`, from the environment (`LLD-container` §4), defaults to 5
and bounds the router's blocking pop and the tmux host's reconciliation loop.
With an empty roster there is no queue to block on, so the router sleeps for the
same interval rather than spinning against repeated roster reads.
The router's maintenance cadence is separately configurable as
`ACTIVITY_POLL_SECONDS`, default 2; it shortens the router's block when its next
pass is due. These are distinct controls because roster convergence and
filesystem observation have different costs.

Staleness is bounded by the relevant polling interval and is harmless in the two obvious
directions. A participant added a moment ago is simply not routed to yet; once a
removed recipient disappears from the router's next roster read, new envelopes
addressed to it dead-letter at their senders. Neither is a race worth closing,
and closing it — keyspace notifications, a watched version key — would add a
write-side obligation to every roster mutation.

Nothing else lives in the table. Whatever a participant *is* beyond its VAB —
what is started in its window, its credentials, its configuration — belongs to
whichever module starts it, not to membership.

Lifecycle branches on VAB. For `tmux`, desired state comes before actual state
in both directions: `StartAgent` writes the optional profile, optional endpoint
name and launch key **before the roster row becomes visible**, then creates the
window. Both the control path and tmux-host resolve the endpoint name against
the tenant's `ENDPOINT_<NAME>_*` environment before calling the name-idempotent
window creator. The roster
row is tmux-host's reconciliation trigger; publishing it first races the host
into creating a window with the wrong CLI or account, and the name-idempotent
create cannot correct that window. `StopAgent` reads the VAB, removes the roster
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

### 3.3 Queues

Direction is relative to the **participant**, as it is on a network device:
egress is traffic leaving the participant, ingress is traffic arriving at it.
The router sits on the opposite end of both.

| Key | Type | Producer | Consumer |
|---|---|---|---|
| `<prefix>:egress` | LIST | the participant | the router |
| `<prefix>:ingress` | LIST | the router | the participant's adapter |
| `<prefix>:dead` | LIST | the router, or an edge adapter | entries by hand; depth by `api` |
| `<prefix>:inbox` | STREAM | the `api` delivery routine | app clients, by cursor |
| `<prefix>:activity` | STREAM | the router's session tailer | api reads and presence/verification sampling |
| `<prefix>:pending.verify` | STREAM | the tmux delivery opener | the router's verifier |
| `<prefix>:blocked` | HASH | the router's verifier | office and watchdog reads |
| tenant `<prefix>:alerts` | STREAM | the watchdog | api polling and SSE, by cursor |

Envelope transport uses lists, not pub/sub, so a backlog survives a consumer
restart. The mailbox is retained, not consumed: `XRANGE` and `XREAD` let polling
and SSE readers keep independent cursors. Delivery appends one field named
`envelope`, capped approximately at 1,000 entries; the stream entry ID is the
cursor. The other two Streams carry observation rather than envelopes and are
described below.

### 3.4 The router's maintenance pass

The router uses its existing loop for observation and retention; there is no
second daemon and none of these jobs sits in an envelope's data path. Every
`ACTIVITY_POLL_SECONDS` (default 2), one roster snapshot drives five jobs:

1. **Tail session files.** For each Claude or Codex agent, the tailer reads only
   bytes after the stored `activity.offset` in the newest session JSONL. It
   appends privacy-reduced events to `<prefix>:activity`: `input`, `output`, or
   `tool`, with a tool's **name only**. Arguments, paths and content have no
   field in the event. The Stream is approximately capped at 1,000 entries.
   CLIs without a supported session format produce no feed. When a different
   session file becomes newest, its offset starts at zero deliberately: offsets
   belong to paths, and skipping to the previous file's byte count would discard
   the beginning of the new session. `activity.offset` retains a map of consumed
   offsets by path, so if modification times later make a previously tailed file
   newest again it resumes there instead of replaying the whole file. The reader
   accepts the original single-path state shape and rewrites it as the map.
2. **Sample presence.** The newest activity timestamp becomes a per-agent
   `presence` hash with `state` (`working`, `idle`, or `unknown`), `since`, and
   `last_activity`. `PRESENCE_WORKING_SECONDS`, default 30, is the working
   horizon; `since` is preserved while the state does not change.
3. **Judge delivery evidence.** Before pasting a `Message`, the tmux adapter
   appends a marker to `<prefix>:pending.verify` when the agent's launch CLI is
   in the explicit `{claude, codex}` allowlist. The marker is written **before**
   the paste: the CLI can record the resulting `input` in less time than a
   post-paste write takes, making the event appear older than its marker and a
   successful delivery look unverified. Measured live, that race misclassified
   five of six messages.

   ⚠ **The allowlist is a capability claim, not a list of exceptions.** A CLI
   is marked only when the router can tail its session format. The old rule
   "anything except agy" also marked bare shell windows, whose deliveries can
   never be confirmed. An unknown future CLI must therefore remain unmarked
   until its activity feed is supported.

   Once a marker is at least `VERIFY_AFTER_SECONDS` old (default 10), the router
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

   For an agent with activity history, a later `input` event confirms the
   marker. Otherwise the router logs `delivery_unverified` and retains that
   first verdict in `<prefix>:blocked` as `{since, stream_id}`. A later verified
   delivery deletes the hash; another unverified delivery does not reset
   `since`. Either way the pending marker is deleted after judgment.

   ⚠ **`blocked` means an unverified delivery and no verified delivery since.**
   It does not mean the CLI is stuck. Credential-free Claude and Codex were both
   measured at their login prompts, with prior activity making them judgeable;
   both deliveries were unverified and set `blocked`. By contrast, an agent
   with no activity history receives no verdict at all. `agy` and bare shells
   produce no verifiable activity, so their deliveries are never marked and
   they cannot acquire this state.

   ⚠ **An unverified delivery is surfaced and never re-pasted.** Verification
   distinguishes "a later input was observed" from "no later input was
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
4. **Carry window logs to stdout.** Agent-side `office` records are written to
   `/home/ubuntu/.flock/window.log.jsonl`; the router tails complete lines from
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
   window file, but does not also print bus telemetry onto that pane. The router
   subsequently tails the file and emits the record centrally, so observability
   is preserved without exposing module names, stream IDs or correlation IDs on
   the agent's own screen. Daemons do not set the quiet flag and continue to log
   to their stdout.
5. **Apply retention.** One pipeline trims each agent's `tasks.done` and `dead`
   LISTs to the newest `BOARD_DONE_MAX` and `DEAD_MAX` entries (both default
   500). Centralising the caps here covers every writer.

An exception in this pass is logged and the forwarding loop continues. That is
also the boundary on its authority: observation may look and may only report;
it does not change delivery decisions.

### 3.5 The watchdog boundary

`flock.watchdog` is a separate tenant process, not another router pass. It reads
the router's `presence` and `blocked` state, board state, tmux window-activity
metadata and credential files, then appends factual records to the tenant
`<prefix>:alerts` Stream. It sends **no envelope**: alerts are for a human through
the api's polling and SSE routes, never for the lead or another agent. Keeping
it out of this loop means a slow external observation cannot stall forwarding.

This is the bus-facing boundary, not the watchdog's complete design. Its
three-signal stall rule, credential/account walk, cooldowns, alert shapes and
failure policy are specified in [`LLD-watchdog.md`](LLD-watchdog.md); they are
independent of the addressing and custody decisions this document owns.

**Having written an ingress queue, the router kicks delivery for that
participant.**

```
  RPUSH …:agent:frontend:ingress
  kick  flock.adapter frontend
```

**Only egress is watched for envelope delivery, and that asymmetry is the whole
design.** You have to sit on a queue when writes come from somewhere you do not control: nobody knows
when a participant will send, so the router blocks on egress. But *every* ingress
write is made by the router itself (invariant 3), so the router already knows
the instant one lands. A second process waiting to be told something the writer
already knew is pure redundancy — and it is redundancy with a cost, because
waiting means a held ingress connection per participant, forever, for an office
that is idle almost all of the time.

Three rails keep the kick from turning the router into a middlebox. They are
invariants, not intentions:

1. **The router reads the header and the roster's fields. Never a payload, never
   a roster value.**
2. **The kick is one fixed command with an agent name.** Not a type, not a
   table of adapters, not a choice. The executor is ours, so it does its own
   `HGET` to find the VAB and dispatches itself. The router hands over a name.
3. **Fire and forget, exactly like the envelope.** No wait, no return code and no
   retry. Failure to start the process is logged and ignored; the envelope stays
   safely on ingress. The moment the router tracks a kick outcome it is holding
   delivery state, and that is the slide this list exists to prevent.

Rail 2 is what keeps invariant 8 true here. The router does not know an adapter
by name, by type or by capability — it knows one command, and the knowledge of
what to do lives on the far side of it.

**One delivery per participant at a time.** The number of adapters running for
frontend is the number of kicks fired, so two envelopes landing close together start two of
them — and they do not merely reorder, they interleave against one window: two
pastes, then two `Enter`s, fusing both messages into one input. `send-keys`
targets a window, not a delivery.

A **busy tag** serialises them, written by the adapter and cleared by it:

```
  HSETNX …:tenant:<t>:delivering  frontend  <started_at>  1 = acquired; deliver
                                                          0 = wait and retry
  HDEL   …:tenant:<t>:delivering  frontend                on finishing it

  kicked while another adapter holds the tag?  retry HSETNX until this one acquires it
```

`HSETNX` is the right primitive because testing absence and claiming the field
must be one atomic operation. `HEXISTS` followed by `HSET` has a race: two
adapters can both observe no tag and then both claim it, recreating the
concurrent delivery this guard exists to prevent. A waiter loops on `HSETNX`
rather than exiting, so each kick delivers the envelope it was fired for;
nothing has to drain a backlog on another kick's behalf and there is no seam
where an envelope lands just after a drain finished.

⚠ **A crashed adapter leaves the tag set, and that is deliberate.** Nothing
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

The log says which failure it was. An adapter that died **before** popping leaves
its envelope in the queue — nothing lost, tag set, depth growing. One that died
**after** popping leaves a `received` with no `opened` on that `stream_id`, which
is precisely the signature §4's two-record rule exists to produce. A wedged
adapter and a dead one look the same from outside, and they do not need telling
apart: something is wrong with frontend, go and look.

An adapter that diagnoses or repairs its own stuck deliveries is a real thing to
want, and it is not for a build that does not yet work end to end.

Note this property was free under a blocked-consumer-per-agent design — one
consumer, so nothing else could pop. It is not free here. That is the price of
adapters that do not exist between deliveries, and it is worth paying.

A dead-lettered envelope is parked under the prefix of **whoever failed to move
it on**, which differs by where it died:

- **The router** parks under the *sender's* prefix. An envelope that failed
  because its recipient could not be resolved has no recipient prefix to park
  under, and the sender is the party who needs to see it.
- **An adapter** parks under *its own*. The envelope arrived; the failure was at
  this end. Parking it under the sender's prefix would put an adapter outside
  its own agent's keys, which §6.3 forbids.

The opener contract has exactly two declared terminal outcomes: return normally
only after opening the envelope, or raise `flock.bus.DeadLetter(reason)` to
reject it. `receive()` catches that signal, parks the raw envelope under the
receiving agent and emits
`dead_lettered`; only a normal return emits `opened`. Openers must not write the
dead list or emit their own terminal record. Keeping custody and the terminal
record in the door prevents one stream from being logged as both dead-lettered
and opened, and applies the rule to every registered kind rather than to a list
of remembered opener implementations.

The sentinel uses an exception for an expected outcome, which is less ordinary
than a return value. That cost is deliberate: wrapper openers naturally
propagate it, while a return sentinel can be discarded by a wrapper and turn
the rejection back into `opened`. Other opener exceptions remain failures;
`receive()` parks and logs those as `opener failed` without stopping the adapter.

## 4. Semantics

**Fire-and-forget, like UDP.** The producer gets no acknowledgement, there is no
retransmit, and nothing at the bus layer promises delivery. A terminal agent
replies by addressing the producer's name. When that producer is an app client,
its `api` delivery routine stores the reply in the client's mailbox for polling
or SSE. That is an application return path, not a transport acknowledgement: a
reply may never come.

**Order is preserved per queue**, because Redis lists are FIFO. Nothing should
come to depend on ordering *across* queues.

**Broadcast is tenant-scoped.** A raw broadcast fans out to the participants of
one tenant and stops there, the way a broadcast domain ends at a router.
Reaching another tenant is explicit addressing, never implicit fan-out.

**`recipient: "all"` is the broadcast address.** The router walks the roster and
writes one copy to each member's ingress, skipping the sender derived from the
popped egress key — a participant does not receive its own broadcast.

That raw protocol broadcast includes every roster participant, so an enrolled
app client receives a copy in its mailbox. `office broadcast` is deliberately a
different, conversational surface: it sends N individual `Message` envelopes
only to VAB `tmux`, excluding app clients and fixed plumbing. The router still
knows only the first form and never reads a VAB.

It has to be a value of `recipient` and not anything else, because routing is
`recipient` and nothing else (§6.4) — a `kind` of `Broadcast` would make the
router branch on `kind`, which is exactly the coupling §5 exists to prevent. And
it has to be a name rather than a pattern: §3.1 excludes glob metacharacters so
that a prefix is safe in a `SCAN MATCH`, which rules out `*`. A reserved name is
what is left, and reserving it costs one entry in a list that already exists.

**The router does not rewrite the envelope.** Each copy keeps
`recipient: "all"`, so a receiver can tell it was addressed to the room rather
than to it. The router has no other case where it modifies what it forwards, and
this is not worth being the first.

The fan-out is one pop and *n* pushes, pipelined, not atomic — nothing at this
layer promises delivery, so a partial fan-out is the same fire-and-forget as a
partial anything. Two log records still, not *n*: the outcome is a single
`forwarded` carrying `count`. One pop, one outcome, as §4 requires.

A broadcast into a tenant of one is *n* = 0 — a successful broadcast to nobody,
not a dead-letter. There was no unresolvable recipient; there was simply no one
else there.

**Loss after `popped` is visible; one earlier window is not.** `BLPOP` is
destructive, and Redis returns the removed value before the router can emit its
first record. If the process or connection fails between those two operations,
the envelope can disappear without a `stream_id` record. Closing that window
requires a reserve/ack journal or a different queue primitive, which would be a
delivery-guarantee change and is deliberately not introduced here. Once
`popped` is emitted, the router writes a second outcome record; a later crash is
therefore visible as "popped, no outcome". The transport remains at-most-once,
with no retry.

`send` and `receive` log at their own ends too, so every delivered envelope
leaves **five transport records** across its life:

```
  sent        the producer's own end            (flock.bus.doors)
  popped      the router took custody           (router)
  forwarded   … and what it then did            (router)
  received    the adapter took custody          (adapter)
  opened      … and what it then did            (adapter)
```

An opener may add a kind-specific lifecycle record between `received` and
`opened`; `AddTicket`, for example, emits `board_write_confirmed`, so its complete
trace has six records. A corrected producer adds `producer_stamped` between
`popped` and `forwarded`; the event carries the corrected producer and names the
original claim in `reason`. The pair-per-component is what matters: each
component records that it took custody and what it then did. `send` has no pair
because it has no custody to hand on — it is the origin.

⚠ **This said "four" until build 20, and the arithmetic never worked**: two
paired components plus `send` is 1+2+2. It read as true only because `sent` was
written into an agent's pane and never reached the log, so four was what anyone
counting actually saw. The claim was corrected when the record it was missing
started arriving.

**The router does not read payloads.** It forwards on `recipient`, and derives
the sender from the queue the envelope was popped from. Nothing else in the
envelope affects where it goes. The moment routing depends on payload contents
it stops being a switch and becomes a middlebox, and every change to what a
message means becomes a change to the router.

## 5. The envelope

```json
{
  "v": 1,
  "kind": "Message",
  "stream_id": "<hex>",
  "correlation_id": "<hex>",
  "ts": "2026-08-07T18:00:00.000Z",
  "producer": "<participant>",
  "recipient": "<participant>",
  "payload": { }
}
```

Outer fields are structural and always present. Everything kind-specific lives
inside `payload`, and validating it is the consumer's job, never the bus's.
Unknown top-level fields are ignored, so a newer producer cannot break an older
router.

`recipient` is a **participant name, not a queue name**. A producer writes
`"recipient": "frontend"`; it never constructs `…:frontend:ingress` and never names a
tenant. Resolving the name to a queue is the router's only real decision, and
keeping it there is what stops topology knowledge spreading into every agent. An
unresolvable name is a dead-letter, not a crash.

A bare name means "in my tenant", which is the only case the running router
handles. Qualified names for reaching another tenant or pod arrive with the
gateway (§7) — until then, an unqualified name that does not resolve inside the
sender's own tenant is dead-lettered.

`kind` is **opaque to the router**. Routing is `recipient` and nothing else. A
router that branches on `kind` has to change every time a new kind is added,
which is the coupling this design exists to avoid.

Where `kind` *is* read is at the far edge: the adapter keeps a `kind` → opener
table and dispatches on it. One opener knows how to put a message in front of an
agent, another does something else entirely. Adding a kind means adding an
opener, and nothing between the two ends changes.

An envelope whose kind has no opener is **dead-lettered and logged**, not
dropped. The `api` VAB deliberately registers a catch-all opener, so every kind
is mailbox data there; tmux and control still dead-letter kinds they cannot open.

Both `producer` and `recipient` are header fields, so reading them is not
reading the payload — §6.4 holds.

`producer` is **port-stamped attribution**. `send` initially writes the caller's
claim, but before any forwarding the router compares it with the participant
name in the popped egress key and overwrites a mismatch. It does not reject the
envelope: rejection would let any process able to write that queue destroy its
owner's traffic. A changed value emits `producer_stamped`; a matching value adds
no record. This is not agent isolation or writer authentication — all agents are
colleagues inside one development office, using one reachable Redis.

## 6. Invariants

1. **`prefix()` on every key.** No flat keys, anywhere, ever.
2. **`producer` is stamped from the popped egress queue before forwarding.** The
   router uses that queue-derived sender for dead-letter placement and broadcast
   exclusion, overwrites a mismatched claim, and logs `producer_stamped` only
   when the value changes. This guarantees queue attribution, not the identity
   of the process that wrote the queue.
3. **Supported participant tools write to their own `egress`; the router is the
   only supported writer of `ingress`.** This is an API boundary, not an enforced
   Redis ACL: `send(producer=...)` accepts any valid participant name. The router
   remains load-bearing because supported sends name a recipient rather than
   writing its ingress directly.
4. **The router never reads the payload.** It forwards on `recipient` and
   derives the sender from the queue key. Nothing else in an envelope affects
   where it goes. Reading a payload to route makes it a middlebox, and every
   change to what a message means becomes a change to the router.
5. **The bus is lifecycle-agnostic.** It validates the envelope's structural
   fields, while `kind` and the meaning of `payload` remain opaque to the router.
   Task state and session context live above it.
6. **Envelope queues are lists, not pub/sub.** Retained mailboxes and
   observation records use Streams where cursors or later judgment require
   them; they are not envelope queues.
7. **Nothing in the data path reads a terminal.** Delivery never branches on
   terminal rendering. Observation may inspect session files or tmux metadata and may only
   report, on its own schedule; it never changes the path an envelope travels.
8. **The router knows nothing about how a participant is implemented.** It reads
   the roster's *fields*, never its *values*, so it cannot know a participant's
   VAB. It kicks one fixed command with a name. This is structural, not a
   convention anyone has to remember.
9. **One bad envelope never stops the loop.** Malformed JSON and an unresolvable
   recipient are logged and dead-lettered per envelope. Queue names are generated
   from validated roster members rather than parsed as untrusted envelope data.

## 7. Built extensions and deferred work

The layer split has survived the extensions built above it. The remaining item
is intentionally outside the running single-tenant system; do not solve it
pre-emptively.

*(Concurrent delivery to one participant used to be listed here as open. It is
settled — see §3.3, "one delivery per participant".)*

**Cross-tenant routing.** Not a separate component — a branch in the router.
When a `recipient` does not resolve inside the local tenant, look it up in a
registry of enrolled tenants and write the envelope to that tenant's Redis.
Registration supplies the discovery half; what remains undesigned is the
enrolment handshake, qualified recipient names, and what happens to an envelope
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
        ▼  api egress ──► router ──► …:agent:host:ingress ──kick──► adapter host
                                                                        │
                                            VAB `control` → StartAgent opener:
                                            write profile/endpoint/launch state,
                                            resolve endpoint, create the window
```

Nothing in the router or the bus changes to allow this, which is the point. The
host becomes an addressable participant with its own VAB, so it needs a name and
a queue pair and nothing else. `kind` stays
opaque to the router; the control opener reads it at the far edge, exactly as §5
describes. All three rails in §3.3 hold untouched.

The same mechanism carries `StopAgent`, `PauseAgent` and `ResumeAgent`. Pause
deliberately leaves the roster and window intact; resume clears the marker,
restarts the CLI and kicks once per queued ingress envelope. Runtime lifecycle
writes remain in the control opener; container boot seeding is the other roster
writer and establishes the initial fixed and tmux rows.

`StartAgent` also accepts `vab: "api"`. That path writes the named client's
roster row and nothing tmux-related. Replies addressed to that name route through
the same ingress and kick, then the API delivery routine appends the envelope to
`…:agent:<client>:inbox`. `StopAgent` removes the row and every classified item
of per-agent identity state; queues and board data remain. The switch
does not change for any of this; it still routes a name without reading its VAB.

**The agent-facing command is a deliberately narrow edge.** `office send` and
`office broadcast` treat every token after the recipient as literal message
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
delivery that mutates a board: its opener appends to the recipient's
`tasks.todo` and pastes nothing. The write does not require a current window;
the opener confirms the returned list length synchronously, while a failed or
unconfirmed write dead-letters. It never uses `pending.verify` or `blocked`,
because an untaken ticket is normal board state rather than an unconsumed
terminal delivery. The recipient later moves its own ticket; no command directly
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
producer keeps its queue non-empty. The code makes no claim about producer rate:
the router rotates the sorted key list one position per pass, ensuring that a
permanently busy first queue does not permanently occupy the first position.

## 8. What this is not

Not a task system. Not an orchestrator in the "supervisor delegates to workers"
sense. Not a scheduler. Anything a participant does with an envelope after
consuming it is out of scope — the bus carries signals, the router forwards
them, and neither decides what is done with them.
