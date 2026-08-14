# Build 45 — bus and switch naming inventory

Inventory only. This document records the vocabulary on main at
`8a37a6123914ddc69505b8c4acbb26aa6562f2b7`; it proposes and performs no
renames. Tier A is documentation, B internal code, C Redis or environment, and
D wire compatibility.

## `flock.bus`

| name | where it lives | kind | tier | what it means, in one line | networking analogue, if any |
|---|---|---|---|---|---|
| bus | `src/flock/bus/__init__.py:1` | doc term | A | The shared library for envelopes, Redis addresses, queue doors, roster reads, logs, and retirement policy; broader than transport alone. | The data-link service plus some control-plane utilities. |
| door | `src/flock/bus/doors.py:1` | doc term | A | One of the library operations that puts an envelope onto an egress queue or takes one from ingress and opens it. | An interface to the switching fabric. |
| send | `src/flock/bus/doors.py:15` | identifier | B | Builds an envelope and appends it to the queue selected by its producer argument. | Transmit through a named source port. |
| receive | `src/flock/bus/doors.py:33` | identifier | B | Pops one recipient queue, validates and dispatches its envelope, then records the outcome. | Receive and demultiplex at a destination port. |
| opener | `src/flock/bus/doors.py:54` | identifier | B | A kind-indexed callback that consumes an already received envelope. | Protocol handler selected by an ethertype. |
| DeadLetter | `src/flock/bus/doors.py:11` | identifier | B | An opener's explicit signal that a received envelope must go to the dead queue. | Reject after receive custody; no exact network analogue. |
| envelope | `src/flock/bus/envelope.py:40` | doc term | A | The versioned JSON object routed between participants. | Frame. |
| EnvelopeError | `src/flock/bus/envelope.py:10` | identifier | B | Invalid envelope structure or addressing, both while building and parsing. | Malformed frame error. |
| build | `src/flock/bus/envelope.py:33` | identifier | B | Validates application fields, adds identity and time fields, and constructs a v1 envelope. | Frame construction. |
| parse | `src/flock/bus/envelope.py:60` | identifier | B | Decodes and structurally validates a v1 envelope while retaining unknown outer fields. | Frame decoding and header validation. |
| kind | `src/flock/bus/envelope.py:50` | wire | D | An opaque non-empty string selecting the recipient opener. | Ethertype or next-protocol discriminator. |
| producer | `src/flock/bus/envelope.py:54` | wire | D | Claimed source participant when built; the switch later stamps it from the popped egress queue. | Source address, corrected from the ingress port. |
| recipient | `src/flock/bus/envelope.py:55` | wire | D | Destination participant or the reserved broadcast value `all`. | Destination address. |
| payload | `src/flock/bus/envelope.py:56` | wire | D | Opaque kind-specific JSON object. | Frame payload. |
| stream_id | `src/flock/bus/envelope.py:51` | wire | D | Unique identity for one envelope and the join key for its lifecycle records. | Frame identity for observability; no normal Ethernet equivalent. |
| correlation_id | `src/flock/bus/envelope.py:52` | wire | D | Identity propagated across related envelopes, or minted for the first one. | Trace or conversation identity; no data-link equivalent. |
| v | `src/flock/bus/envelope.py:49` | wire | D | Envelope schema version. | Protocol version. |
| ts | `src/flock/bus/envelope.py:53` | wire | D | Envelope construction timestamp. | Transmit timestamp. |
| prefix | `src/flock/bus/keys.py:51` | identifier | B | The sole constructor for structurally scoped Redis key names, not merely a prefix fragment. | Hierarchical address encoder. |
| segment | `src/flock/bus/keys.py:5` | doc term | A | One validated value between structural separators; resource names are dot-composed segments. | One address component. |
| reserved | `src/flock/bus/keys.py:8` | doc term | A | Names prohibited in every segment because some are structural tags and `all` is a broadcast address. | Reserved addresses and address syntax words. |
| roster | `src/flock/bus/roster.py:1` | doc term | A | Tenant hash whose fields are participant names and whose values are their VABs. | MAC/address table, although it also stores attachment type. |
| members | `src/flock/bus/roster.py:6` | identifier | B | Returns only the participant names from the roster. | Enumerate learned/enrolled addresses. |
| is_member | `src/flock/bus/roster.py:11` | identifier | B | Tests whether a participant name is enrolled in the tenant roster. | Address-table membership test. |
| vab | `src/flock/bus/roster.py:15` | identifier | B | Returns the roster value used to choose the participant's delivery mechanism. The repository expands VAB as “virtual agent base,” but I could not tell what that phrase means for `api` or `control` without asking. | Port/attachment type is the behavior; the expansion has no clear analogue. |
| resource | `src/flock/bus/keys.py:55` | identifier | B | Final Redis-key suffix naming stored state beneath tenant or participant scope. | Named table/queue at an address, not a routing level. |
| AGENT_STATE_RESOURCES | `src/flock/bus/resources.py:6` | identifier | B | Redis resources deleted when a participant identity is retired. “State” does not reveal why activity and presence are disposable while inbox and board are not; I could not infer the boundary from the name alone. | Ephemeral control-plane state. |
| AGENT_DATA_RESOURCES | `src/flock/bus/resources.py:21` | identifier | B | Redis resources retained when a participant identity is retired. “Data” does not reveal that these are specifically custody and work-history stores. | Durable traffic and application state. |
| PER_AGENT_RESOURCES | `src/flock/bus/resources.py:34` | identifier | B | Union of the two classified per-participant resource sets. | Per-address state inventory. |
| TENANT_RESOURCES | `src/flock/bus/resources.py:35` | identifier | B | Known Redis resources stored at tenant rather than participant scope. | Routing-domain state inventory. |
| DYNAMIC_RESOURCE_PATTERNS | `src/flock/bus/resources.py:38` | identifier | B | Wildcard inventory of resource families that may exist beyond the fixed sets; currently only board lists. | Resource-family pattern. |
| purge_agent | `src/flock/bus/resources.py:41` | identifier | B | Deletes classified identity state but deliberately retains queues and board data. “Purge” alone overstates what it removes. | De-enrol an address while retaining buffered traffic. |
| emit | `src/flock/bus/logging.py:88` | identifier | B | Projects envelope fields into one lifecycle log record. | Emit a per-frame trace event. |
| log_record | `src/flock/bus/logging.py:20` | identifier | B | Constructs and outputs a contract-shaped observation record. | Telemetry event. |
| record_task_event | `src/flock/bus/logging.py:108` | identifier | B | Appends the separate operator board-history schema, despite living in the bus logging module. | Operator audit record; no switching analogue. |
| module | `src/flock/bus/logging.py:42` | wire | D | Component name in a lifecycle record, not a Python module necessarily. | Reporting node/component. |
| event | `src/flock/bus/logging.py:43` | wire | D | Lifecycle or operator-history action name; the same field name also wraps serialized activity events in Redis. | Event type; overloaded across telemetry schemas. |
| local_redis_url | `src/flock/bus/connection.py:6` | identifier | B | Constructs the password-bearing loopback Redis connection URL used by infrastructure. | Local switch-management connection string. |
| FLOCK_LOG_FILE | `src/flock/bus/logging.py:75` | env var | C | Optional JSONL spool receiving observation records in addition to permitted stdout. | Telemetry sink path. |
| FLOCK_LOG_QUIET | `src/flock/bus/logging.py:76` | env var | C | Value `1` suppresses observation records on stdout, primarily inside an agent pane. | Disable local telemetry egress. |
| FLOCK_LOG_FILE_AGENT_ONLY | `src/flock/bus/logging.py:79` | env var | C | Makes file spooling conditional on `AGENT_NAME`; the name says who may write rather than what the file contains. | Source filter on a telemetry sink. |
| TASK_RECORD | `src/flock/bus/logging.py:119` | env var | C | Path for the separate board action JSONL history. | Operator-audit sink path. |

## `flock.switch`

| name | where it lives | kind | tier | what it means, in one line | networking analogue, if any |
|---|---|---|---|---|---|
| switch | `src/flock/switch/service.py:19` | doc term | A | Tenant-local process that switches egress to ingress and also schedules activity, presence, verification, log-spool, and retention maintenance. | Primarily a switch, plus unrelated control/telemetry maintenance. |
| Switch | `src/flock/switch/service.py:19` | identifier | B | Stateful queue-forwarder whose offset rotates the first queue checked for fairness. | Switching loop. |
| step | `src/flock/switch/service.py:37` | identifier | B | Performs at most one forwarding attempt after one blocking pop. | One receive/switch iteration. |
| run | `src/flock/switch/service.py:98` | identifier | B | Repeats forwarding and periodically invokes all switch-hosted maintenance services. | Data-plane loop plus control-plane scheduler. |
| sender | `src/flock/switch/service.py:54` | identifier | B | Participant name derived from the popped egress key and used as authoritative producer attribution. | Source port identity. |
| source_key | `src/flock/switch/service.py:51` | identifier | B | Full Redis egress key returned by BLPOP; “source” here means queue source, not envelope producer claim. | Ingress interface on the switching process. |
| claimed_producer | `src/flock/switch/service.py:63` | identifier | B | Envelope producer value before correction from the queue-derived sender. | Untrusted claimed source address. |
| _kick | `src/flock/switch/service.py:31` | identifier | B | Fire-and-forget launch of a delivery port after ingress is written. | Interrupt/doorbell to the destination port driver. |
| offset | `src/flock/switch/service.py:25` | identifier | B | Index rotating roster order between BLPOP calls; distinct from file-tail offsets stored in Redis. | Fairness cursor. |
| maintenance pass | `src/flock/switch/service.py:123` | doc term | A | One scheduled batch of activity, presence, verification, log-tail, and retention work. | Control/management-plane polling cycle. |
| ActivityTailer | `src/flock/switch/activity.py:67` | identifier | B | Reads agent CLI session files and writes privacy-reduced input/output/tool events. | Traffic/activity monitor, not a packet tailer. |
| activity | `src/flock/switch/activity.py:153` | doc term | A | Reduced history of observable CLI input, output, and tool-use events. | Link activity/traffic observation. |
| input / output / tool | `src/flock/switch/activity.py:29` | wire | D | Values of activity event `kind`, classifying user input, agent text, and tool invocation. | Traffic classes, not envelope kinds. |
| flavor | `src/flock/switch/activity.py:118` | identifier | B | Session-log format/parser family, currently Claude or Codex. | Decoder type. |
| PresenceSampler | `src/flock/switch/presence.py:32` | identifier | B | Derives current working, idle, or unknown presence from launch type and recent activity. | Link/host state estimator. |
| presence | `src/flock/switch/presence.py:97` | doc term | A | Current derived availability state with transition and last-activity times. | Operational state, not reachability alone. |
| tailable | `src/flock/switch/presence.py:41` | identifier | B | Whether the configured CLI is expected to produce a session file this process understands. | Observable by this monitor. |
| DeliveryVerifier | `src/flock/switch/verification.py:37` | identifier | B | Judges aged paste markers by looking for later CLI input activity; it does not verify every delivery kind. | Deferred receive heuristic, not acknowledgement protocol. |
| pending | `src/flock/switch/verification.py:76` | identifier | B | Paste markers old enough to await a later activity judgment; unrelated to a board ticket waiting to be taken. | Unacknowledged delivery observations. |
| eligible | `src/flock/switch/verification.py:77` | identifier | B | Pending markers at least `verify_after_seconds` old. | Timed-out candidates for acknowledgement judgment. |
| verified | `src/flock/switch/verification.py:102` | identifier | B | A later input event exists; this proves consumption heuristically, not merely queue forwarding. | Inferred acknowledgement. |
| blocked | `src/flock/switch/verification.py:75` | doc term | A | Participant state set when a paste cannot be confirmed after activity history exists; not general inability to work or queued board work. | Suspected receive-path fault. |
| delivery_unjudged | `src/flock/switch/verification.py:91` | wire | D | First paste marker discarded from judgment because no activity history exists. | Delivery with insufficient observation for an ACK decision. |
| delivery_unverified | `src/flock/switch/verification.py:116` | wire | D | Paste marker lacked a later input event after the wait and caused or preserved blocked state. | Missing inferred ACK. |
| WindowLogTailer | `src/flock/switch/windowlog.py:8` | identifier | B | Copies complete JSONL records from the agent-window spool to container stdout and manages truncation. | Telemetry collector. |
| RetentionTrimmer | `src/flock/switch/retention.py:6` | identifier | B | Applies count caps to completed-ticket and dead-letter lists during the switch maintenance pass. | Buffer retention policy. |
| poll | `src/flock/switch/retention.py:16` | identifier | B | Name shared by five maintenance components for one non-blocking pass, not network polling in every case. | One management-plane scan. |
| REDIS_URL | `src/flock/switch/service.py:143` | env var | C | Infrastructure connection string for the tenant's loopback Redis. | Switching-fabric management/data connection. |
| POD / TENANT | `src/flock/switch/service.py:146` | env var | C | Values selecting the switch's Redis address namespace and routing domain. | Network namespace and broadcast/routing domain. |
| ROSTER_POLL_SECONDS | `src/flock/switch/service.py:148` | env var | C | BLPOP wait and empty-roster sleep interval; its name understates that it controls the forwarding loop even though the roster is read each step. | Forwarding-loop wait, not only address-table polling. |
| ACTIVITY_POLL_SECONDS | `src/flock/switch/service.py:155` | env var | C | Period for the entire switch maintenance batch, not activity tailing alone. | Management-plane polling interval. |
| VERIFY_AFTER_SECONDS | `src/flock/switch/service.py:160` | env var | C | Minimum paste-marker age before delivery verification judges it. | Inferred-ACK timeout. |
| PRESENCE_WORKING_SECONDS | `src/flock/switch/service.py:166` | env var | C | Activity recency window classified as working presence. | Active-state hold time. |
| WINDOW_LOG_MAX_BYTES | `src/flock/switch/service.py:172` | env var | C | Size cap triggering truncation after the window spool is fully consumed. | Telemetry spool cap. |
| BOARD_DONE_MAX | `src/flock/switch/service.py:178` | env var | C | Maximum retained completed-ticket entries per participant. | Application history cap. |
| DEAD_MAX | `src/flock/switch/service.py:179` | env var | C | Maximum retained dead-letter entries per participant. | Error-queue cap. |

## Redis key shapes defined or classified by the bus

All shapes begin with `pod:<pod>:tenant:<tenant>` as constructed at
`src/flock/bus/keys.py:58`. Participant shapes add `:agent:<agent>` at
`src/flock/bus/keys.py:60`. The rows below inventory the resource suffixes; all
are tier C.

| name | where it lives | kind | tier | what it means, in one line | networking analogue, if any |
|---|---|---|---|---|---|
| pod | `src/flock/bus/keys.py:58` | redis key | C | Outermost namespace value containing tenants; current deployment does not use it as an independent runtime boundary. I could not tell why this level is named pod, rather than installation or network, from code and docs alone. | Parent routing namespace; exact analogue unclear. |
| tenant | `src/flock/bus/keys.py:58` | redis key | C | Routing and roster scope served by one switch. | Broadcast/routing domain. |
| agent | `src/flock/bus/keys.py:60` | redis key | C | Participant-address scope; it also contains non-agent API and control participants. | Host/port address, not necessarily an autonomous agent. |
| roster | `src/flock/bus/resources.py:36` | redis key | C | Tenant hash mapping participant names to VAB delivery types. | Address/MAC table with port type as value. |
| lead | `src/flock/bus/resources.py:36` | redis key | C | Tenant scalar naming the participant treated as office lead. | Designated controller address. |
| window.log.offset | `src/flock/bus/resources.py:36` | redis key | C | Tenant byte cursor into the shared window log spool. | Telemetry collector cursor. |
| delivering | `src/flock/bus/resources.py:36` | redis key | C | Tenant hash of participants currently holding delivery locks/leases; classification alone does not explain its value shape. | Port-busy/dispatch-lock table. |
| alerts | `src/flock/bus/resources.py:36` | redis key | C | Tenant alert collection; I could not tell its element schema or producer/consumer from the bus and switch code alone. | Management alarms. |
| credential.alerted | `src/flock/bus/resources.py:36` | redis key | C | Tenant marker suppressing repeated credential alerts; I could not tell its exact value shape here. | Alarm deduplication state. |
| egress | `src/flock/bus/resources.py:24` | redis key | C | Per-participant FIFO written by send and popped by the switch. | Transmit queue from a participant; switch ingress port in switching terms. |
| ingress | `src/flock/bus/resources.py:23` | redis key | C | Per-participant FIFO written by the switch and popped by a receiving port. | Receive queue to a participant; output port from the switch. |
| dead | `src/flock/bus/resources.py:25` | redis key | C | Per-participant list holding malformed, unroutable, or opener-rejected envelopes. | Dead-letter/error queue, not packet drop telemetry alone. |
| inbox | `src/flock/bus/resources.py:26` | redis key | C | Retained mailbox for API participants after their port opens an envelope. | Application receive buffer beyond the port. |
| tasks.todo | `src/flock/bus/resources.py:27` | redis key | C | Board FIFO of offered work not yet taken. | Application work queue; no network analogue. |
| tasks.doing | `src/flock/bus/resources.py:28` | redis key | C | Board list containing the participant's current claimed work. | No network analogue. |
| tasks.hold | `src/flock/bus/resources.py:29` | redis key | C | Board list of explicitly deferred claimed work. | No network analogue. |
| tasks.done | `src/flock/bus/resources.py:30` | redis key | C | Board history of completed work, count-trimmed by the switch. | No network analogue. |
| blocked | `src/flock/bus/resources.py:8` | redis key | C | Hash recording the first unverified terminal delivery that currently marks the participant blocked. | Suspected receive fault state. |
| launch | `src/flock/bus/resources.py:9` | redis key | C | Scalar CLI name desired for a tmux participant. | Port-driver type/configuration. |
| profile | `src/flock/bus/resources.py:10` | redis key | C | Scalar configuration/account profile used to locate CLI state. | Port configuration profile. |
| endpoint | `src/flock/bus/resources.py:11` | redis key | C | Scalar local-model endpoint name for one participant, not a network termination point despite the network model. | Model-service selection; collides with the ordinary network meaning of endpoint. |
| paused | `src/flock/bus/resources.py:12` | redis key | C | Marker that desired membership remains but the participant CLI should not run. | Administratively down while address remains enrolled. |
| activity | `src/flock/bus/resources.py:13` | redis key | C | Redis stream of reduced CLI input/output/tool observations. | Activity telemetry stream. |
| activity.offset | `src/flock/bus/resources.py:14` | redis key | C | JSON map of session-file paths to byte cursors for the activity tailer. | Telemetry ingestion cursors. |
| alerted | `src/flock/bus/resources.py:15` | redis key | C | Per-participant alert marker; I could not tell which alert it suppresses or its value shape from bus/switch code alone. | Alarm deduplication state. |
| presence | `src/flock/bus/resources.py:16` | redis key | C | Hash holding derived `state`, `since`, and `last_activity`. | Operational state record. |
| pending.verify | `src/flock/bus/resources.py:17` | redis key | C | Stream of terminal-paste markers awaiting later activity judgment. | Pending inferred acknowledgements. |

## Explicit collisions and drift

- `ingress` and `egress` are named from the participant's perspective, while
  `src/flock/switch/service.py:65` calls the popped egress queue the switch's
  “ingress port.” Both usages are locally coherent and reverse at the switch.
- `kind` exists in the envelope at `src/flock/bus/envelope.py:50` and inside an
  activity event at `src/flock/switch/activity.py:149`; the first selects an
  opener and the second classifies observed CLI behavior.
- `event` is the lifecycle action at `src/flock/bus/logging.py:43`, the field
  wrapping a serialized activity observation at `src/flock/switch/activity.py:154`,
  and the action in the separate task-history record at
  `src/flock/bus/logging.py:124`.
- `offset` is the switch's fairness cursor at `src/flock/switch/service.py:25`,
  per-session byte cursors in `activity.offset` at
  `src/flock/switch/activity.py:132`, and the window-spool byte cursor at
  `src/flock/switch/windowlog.py:23`.
- `agent` names every roster participant in Redis addressing, but roster values
  include API clients and control, not only agent CLIs.
- `switch` accurately names recipient resolution but understates that the same
  process owns five maintenance jobs at `src/flock/switch/service.py:110-121`;
  in the documented network model its queue forwarding behavior is closer to a
  switch than an inter-network switch.
