# Naming inventory — tmux lane

Inventory only: this document proposes no rename and changes no interface.
Tier A is documentation, B internal code, C Redis/environment, and D wire.

## `flock.tmux`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `tmux` | `src/flock/tmux/ops.py:56` | doc term | Shared library for driving a tenant's terminal multiplexer, plus guide/trust setup. | Physical terminal fabric behind a port. | B |
| `run_tmux` | `src/flock/tmux/ops.py:56` | identifier | Checked entry point for one tmux subprocess invocation. | Device-driver operation. | B |
| `require_isolated_tmux` | `src/flock/tmux/ops.py:33` | identifier | Refuses ambient tmux unless an explicit socket namespace exists. | Refusing an unspecified network namespace. | B |
| `socket` | `src/flock/tmux/ops.py:33` | identifier | Optional explicit tmux server socket path, not a network socket. | None; collision with network sockets. | B |
| `TMUX_SOCKET` | `src/flock/tmux/ops.py:45` | env var | Explicit tmux socket path accepted as isolation authority. | None; local control provider. | C |
| `TMUX_TMPDIR` | `src/flock/tmux/ops.py:45` | env var | Directory that namespaces tmux's default socket. | Network namespace, approximately. | C |
| `AmbientTmuxError` | `src/flock/tmux/ops.py:19` | identifier | Attempt to drive whichever tmux server happens to be ambient. | Accidental use of the default routing domain. | B |
| `TmuxCommandError` | `src/flock/tmux/ops.py:23` | identifier | Non-zero tmux command result, distinct from empty success. | Link-operation failure. | B |
| `window` | `src/flock/tmux/ops.py:66` | doc term | One named terminal hosting one `port_type: tmux` agent. | A switch port's attached terminal. | A |
| `create_window` / `kill_window` / `list_windows` | `src/flock/tmux/ops.py:66`, `src/flock/tmux/ops.py:321`, `src/flock/tmux/ops.py:367` | identifier | Idempotent named-window lifecycle operations. | Port provisioning and inventory. | B |
| `window_env` | `src/flock/tmux/ops.py:229` | identifier | Builds the command-scoped environment inherited by an agent pane. | Port attachment configuration. | B |
| `paste_text` | `src/flock/tmux/ops.py:371` | identifier | Performs the complete bracketed paste, delay, and Enter delivery sequence. | Frame transmission onto a terminal link. | B |
| `PASTE_ENTER_DELAY` | `src/flock/tmux/ops.py:15` | env var | Delay separating paste from Enter to prevent CLI input coalescing. | Inter-frame gap, loosely. | C |
| `agent guide` | `src/flock/tmux/ops.py:296` | doc term | Generated `AGENTS.md`/`CLAUDE.md` instructions placed in an agent workdir. | Port-local configuration. | A |
| `project trusted` | `src/flock/tmux/ops.py:112` | doc term | Pre-acceptance of a workdir in each supported CLI's own configuration. | None. | A |
| `profile` | `src/flock/tmux/ops.py:112` | identifier | Named CLI configuration/account directory, not an agent behavioral profile. | None; “profile” is underspecified. | B |
| `provider` | `src/flock/tmux/ops.py:235` | identifier | Model-service configuration selected for an agent. | Contradicts the network-model sense of provider. | B |

## `flock.tmuxhost`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `tmuxhost` / `TmuxHost` | `src/flock/tmuxhost/host.py:14` | identifier | Long-running reconciler that makes tmux windows match desired roster state. | Port manager/controller. | B |
| `host` | `container/entrypoint.sh:292` | doc term | Here means the tmux reconciler, while roster name `host` means lifecycle control. | Collision between physical host and control-plane address. | A |
| `reconcile_once` | `src/flock/tmuxhost/host.py:165` | identifier | One desired-versus-actual window convergence pass. | Control-plane reconciliation. | B |
| `ensure_server_and_session` | `src/flock/tmuxhost/host.py:80` | identifier | Creates missing tmux server/session and applies global options. | Ensuring a switching fabric exists. | B |
| `session_name` | `src/flock/tmuxhost/host.py:21` | identifier | Tmux session target, normally identical to tenant name. | Routing-domain instance name. | B |
| `TMUX_SESSION` | `src/flock/tmuxhost/__main__.py:14` | env var | Override for tmux session name independently of tenant. | Routing-domain override. | C |
| `ROSTER_POLL_SECONDS` | `src/flock/tmuxhost/__main__.py:13` | env var | Delay between desired-state reconciliation passes. | Control-plane refresh interval. | C |
| `get_agent_cli` | `src/flock/tmuxhost/host.py:31` | identifier | Reads the agent's launch program from Redis. | Resolves port attachment implementation. | B |
| `launch` | `src/flock/tmuxhost/host.py:32` | redis key | CLI name tmuxhost must start for an agent. | Port attachment type. | C |
| `profile` | `src/flock/tmuxhost/host.py:39` | redis key | Agent's shared CLI configuration/account name. | None. | C |
| `provider` | `src/flock/tmuxhost/host.py:53` | redis key | Indirection name used to find model URL/token environment variables. | Misleading: a model uplink, not the participant provider. | C |
| `PROVIDER_<NAME>_*` | `src/flock/tmuxhost/host.py:61` | env var | URL, token, and model settings for a named model service. | Upstream service configuration. | C |
| `lead` | `src/flock/tmuxhost/host.py:75` | redis key | Tenant-level agent whose generated guide receives leadership instructions. | None. | C |
| `__init__` | `src/flock/tmuxhost/host.py:83` | identifier | Non-agent placeholder window used to keep an empty session alive. | Null/management port, loosely. | B |

## `flock.port`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `port` | `src/flock/port/send.py:9`, `src/flock/port/deliver.py:265` | doc term | Names both outbound agent sending and inbound per-envelope delivery—opposite sides of the switch. | Two different NIC directions collapsed into one component name. | B |
| `send` CLI | `src/flock/port/send.py:5` | identifier | Agent-facing command that constructs an envelope and writes its own egress. | Transmit-side NIC operation. | B |
| `run_port` | `src/flock/port/deliver.py:265` | identifier | Acquires per-agent serialization, delivers one ingress envelope, and exits. | Receive-side port service. | B |
| `deliver_one` | `src/flock/port/deliver.py:283` | identifier | Dispatches one destination ingress item by looking up handler in port registry. | Frame delivery entrypoint. | B |
| `deliver_tmux` | `src/flock/port/deliver.py:110` | identifier | Delivers queued ingress envelopes to a tmux window. | Tmux frame delivery. | B |
| `deliver_api` | `src/flock/port/deliver.py:58` | identifier | Moves one ingress envelope to an enrolled client's mailbox stream. | Delivery to a different port medium. | B |
| `deliver_unroutable` | `src/flock/port/deliver.py:88` | identifier | Pops and dead-letters an envelope whose port_type has no implementation. | Unsupported-port drop. | B |
| `get_delivery_handler` | `src/flock/port/registry.py:38` | identifier | Resolves delivery function or lazy module spec for a port_type. | Port registry lookup. | B |
| `register_port_type` | `src/flock/port/registry.py:24` | identifier | Registers a callable or lazy (module, attr) handler for a port_type. | Port registration. | B |
| `messages_opener` / `message_opener` | `src/flock/port/openers.py:82`, `src/flock/port/openers.py:119` | identifier | Terminal action selected for a `Message` (batched or single). | Protocol handler. | B |
| `command_opener` | `src/flock/port/openers.py:144` | identifier | Terminal action selected for a `Command`. | Protocol handler. | B |
| `add_ticket_opener` | `src/flock/port/openers.py:175` | identifier | Board action selected for an `AddTicket`. | Protocol handler. | B |
| `attachment_opener` | `src/flock/port/openers.py:284` | identifier | File write and inert notice action selected for an `Attachment`. | Protocol handler. | B |
| `opened` | `src/flock/bus/doors.py:143` | doc term | Terminal outcome meaning an opener completed, not proof a human/CLI consumed it. | Accepted by destination handler, not delivery acknowledgement. | A |
| `delivering` | `src/flock/port/deliver.py:277` | redis key | Tenant hash serving as a per-agent mutual-exclusion/busy tag. | Per-port transmit lock. | C |
| `paused` | `src/flock/port/deliver.py:120` | redis key | Marker that leaves ingress queued rather than opening it. | Administratively down port. | C |
| `pending.verify` | `src/flock/port/openers.py:50` | redis key | Stream of pasted deliveries awaiting out-of-band activity judgment. | Delivery telemetry awaiting observation. | C |
| `delivery.markers` | `src/flock/port/openers.py:51` | redis key | Bounded stream used to correlate later token usage heuristically with the delivery that prompted it. | Receive-side accounting join marker. | C |
| `VERIFY_AFTER_SECONDS` | `src/flock/watchdog/service.py:386` | env var | Minimum marker age before the watchdog judges delivery verification; defaults to 120 seconds. | Observation-window threshold. | C |
| `VERIFIABLE_CLIS` | `src/flock/port/openers.py:21` | identifier | Allowlist of CLI implementations whose session files can confirm input. | Observable port types. | B |
| `inbox` | `src/flock/port/deliver.py:67` | redis key | Resumable mailbox stream for a `port_type: api` participant. | Receive buffer on an application port. | C |
| `dead` | `src/flock/port/deliver.py:66` | redis key | Retained list of envelopes that could not be opened. | Dead-letter/drop queue. | C |
| `ingress` | `src/flock/port/deliver.py:65` | redis key | Recipient-side queue from which delivery pops. | Ingress queue. | C |
| `_CatchAllDict` | `src/flock/port/deliver.py:43` | identifier | Mapping facade that makes every kind openable for API mailboxes. | Promiscuous protocol handler. | B |

## `flock.control`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `control` | `src/flock/control/runner.py:1` | doc term | port_type that opens tenant lifecycle envelopes addressed to fixed participant `host`. | Control plane. | A |
| `port_type` | `src/flock/control/openers.py:9` | doc term | Selects the receiving implementation (`tmux`, `api`, or `control`); its intended expansion is not recoverable here. | Port/media type, but the acronym does not convey it. | A |
| `host` | `src/flock/control/openers.py:10` | identifier | Fixed roster participant/address for lifecycle operations, not tmuxhost. | Control-plane destination address. | B |
| `deliver_one` | `src/flock/control/runner.py:23` | identifier | Pops and opens one lifecycle envelope; same name as port's port_type dispatcher. | Control-plane receive operation. | B |
| `StartAgent` / `StopAgent` | `src/flock/control/runner.py:102` | wire | Envelope kinds that add/remove participant desired state and port_type-specific state. | Provision/deprovision a port. | D |
| `PauseAgent` / `ResumeAgent` | `src/flock/control/runner.py:104` | wire | Envelope kinds that stop/restart a tmux CLI while preserving membership and queues. | Administratively down/up a port. | D |
| `start_agent` / `stop_agent` | `src/flock/control/openers.py:109-240` | identifier | Desired-state mutations implementing lifecycle kinds. | Port provisioning operations. | B |
| `pause_agent` / `resume_agent` | `src/flock/control/openers.py:279-301` | identifier | Pause-marker and tmux-process operations implementing temporary suspension. | Port admin-state operations. | B |
| `replace_window` | `src/flock/control/openers.py:115` | identifier | Callback that kills stale actual state so tmuxhost recreates it. | Rebind a port attachment. | B |
| `*_accepted` | `src/flock/control/openers.py:53-56` | record | Every desired-state write committed; claims nothing about asynchronously reconciled actual state. | Accepted control-plane intent. | B |
| `*_incomplete` | `src/flock/control/openers.py:39-45` | record | A write outcome is unknown, only a subset was acknowledged, or an inline actual-state attempt failed; names facts separately from uncertainty. | Indeterminate or partial control outcome requiring operator action. | B |
| `_STARTABLE_VABS` | `src/flock/control/openers.py:17` | identifier | port_type values lifecycle control accepts for new participants. | Supported port/media types. | B |
| `_FIXED_PARTICIPANTS` | `src/flock/control/openers.py:18` | identifier | Built-in addresses that `StopAgent` cannot remove. | Reserved control-plane addresses. | B |
| `provider` | `src/flock/control/openers.py:172` | wire | `StartAgent` payload field selecting a named model service. | Model uplink selection, not participant provider. | D |
| `cli` | `src/flock/control/openers.py:157` | wire | `StartAgent` payload name for the desired agent program. | Attachment implementation. | D |
| `launch` | `src/flock/control/openers.py:208` | redis key | Stored name for the same desired agent program called `cli` on the wire. | Attachment implementation. | C |
| `agent` | `src/flock/control/openers.py:100` | wire | Lifecycle target participant name, even when the participant is an API client. | Address/port identity; “agent” is narrower than the set. | D |

## `container/`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `container` | `container/compose.yaml:10` | doc term | Deployment and security boundary containing exactly one tenant. | Network namespace / routing domain boundary. | A |
| `tenant` | `container/compose.yaml:10` | identifier | Compose service name and logical routing domain. | Routing domain. | B |
| `POD` | `container/compose.yaml:22` | env var | Namespace above tenant in every Redis key. | I could not tell what distinct network concept this means without asking. | C |
| `TENANT` | `container/compose.yaml:23` | env var | Tenant identity and default tmux session name. | Routing domain. | C |
| `AGENTS` | `container/compose.yaml:27` | env var | Boot roster seed encoded as comma-separated `name:port_type` pairs. | Static MAC/port table seed. | C |
| `AGENT_CLIS` | `container/compose.yaml:42` | env var | Comma-separated per-agent launch-program exceptions. | Port attachment map. | C |
| `AGENT_PROFILES` | `container/compose.yaml:43` | env var | Comma-separated per-agent account-config exceptions. | Port account map. | C |
| `AGENT_PROVIDERS` | `container/compose.yaml:52` | env var | Comma-separated per-agent model-service exceptions. | Port uplink map. | C |
| `API_TOKEN` | `container/compose.yaml:54` | env var | Shared bearer credential for both published doors. | Network access credential. | C |
| `API_HOST` / `SESSION_HOST` | `container/compose.yaml:73`, `container/compose.yaml:74` | env var | Host-side publish addresses, not application bind addresses. | Listen/publish address. | C |
| `API_PORT` / `SESSION_PORT` | `container/compose.yaml:58` | env var | Host-side published ports; container-side ports remain 8080/8081. | Port mapping. | C |
| `API_TLS_*` / `SESSION_TLS_*` | `container/compose.yaml:63` | env var | In-container certificate/key paths for each door. | TLS termination material. | C |
| `ALLOW_PLAINTEXT_PUBLISH` | `container/compose.yaml:75` | env var | Explicit operator acceptance of publishing a plaintext door beyond loopback. | Insecure-listener override. | C |
| `FLOCK_ALLOW_PLAINTEXT` | `container/entrypoint.sh:190` | env var | Entrypoint's internal assertion that exposure policy was already evaluated. | Policy handoff flag. | C |
| `REDIS_BIND` / `REDIS_PASSWORD` | `container/entrypoint.sh:195`, `container/entrypoint.sh:210` | env var | Redis listen address and credential required when widened beyond loopback. | Internal switch-store listener security. | C |
| `REDIS_URL` | `container/entrypoint.sh:218` | env var | Connection string handed only to framework processes that need Redis. | Control-plane store address. | C |
| `REDIS_READY_SECONDS` | `container/entrypoint.sh:235` | env var | Maximum boot wait for Redis readiness. | Dependency convergence timeout. | C |
| `FLOCK_CUSTODY_FILE` | `container/entrypoint.sh:16` | env var | Mounted append-only byte mirror of custody records written to container stdout, retained across tenant teardown. | Durable observation ledger. | C |
| `ROSTER_POLL_SECONDS` | `container/compose.yaml:31` | env var | Shared refresh interval for switch and tmuxhost. | Control-plane refresh interval. | C |
| `WATCHDOG_ENABLED` | `container/entrypoint.sh:417` | env var | Enables the separate human-alerting observer. | Network monitor enable flag. | C |
| `door` | `container/entrypoint.sh:165` | doc term | One externally published API or session process/port. | Network ingress door/listener. | A |
| `start` | `container/entrypoint.sh:127` | identifier | Shell helper that launches a named child and records its PID. | Process supervisor launch, though it is not a supervisor. | B |
| `rcli` | `container/entrypoint.sh:226` | identifier | Auth-aware wrapper around `redis-cli` used during boot seeding. | Control-plane configuration client. | B |
| `startAgent` | `src/flock/tmuxhost/host.py:104` | identifier | CLI launcher applying office-specific approval and model settings; not lifecycle `StartAgent`. | Port-attached process launcher. | B |

## Explicit findings

### One word, two meanings

- **`port`** names the outbound `send` CLI (`port/send.py`) and the inbound
  one-envelope receiver (`port/deliver.py`). They sit on opposite sides of the
  switch and have different lifecycles.
- **`host`** means the tmux reconciliation module and the fixed control-plane
  roster participant.
- **`socket`** in tmux code means a filesystem path to a tmux server, while the
  surrounding network design also uses socket in its ordinary network sense.
- **`provider`** means model-service selection here, while the architectural
  model naturally uses provider for an addressable participant or termination.
- **`startAgent`** is a local CLI-process launcher; `StartAgent` is a lifecycle
  envelope kind. Case is carrying the entire distinction.

### Two words, one meaning

- **`cli` and `launch`** are the same desired program before and after the wire
  boundary (`StartAgent.payload.cli` becomes the `launch` Redis resource).
- **`agent`, `participant`, and roster member** overlap. `agent` appears in wire
  fields even when the target is an API application, so the narrowest word is
  used for the broadest set.
- **`profile` and account** describe the same shared CLI configuration/login in
  code and prose respectively.

### Meaning not recoverable from this scope

- **`POD`: I could not tell what this means without asking.** Code proves it is
  a namespace above tenant, but the owned code and docs do not establish what
  real entity it represents or why both levels are required.
- **`port_type`: I could not determine its intended expansion from code.** I can infer
  its function—port implementation/receiving medium—from the values `tmux`,
  `api`, and `control`, but “virtual agent base” does not explain the latter two.

### Names that fight the network model

- `provider` denotes an upstream model service instead of a network participant.
- `port` merges transmit and receive edges rather than naming one port-side
  function.
- `agent` labels application clients and the lifecycle control participant,
  neither of which is an AI agent.
- `inbox` and `ingress` are usefully distinct but easy to misread: `ingress` is
  the consumed delivery queue for every participant; `inbox` is only the
  resumable mailbox stream for API participants.
