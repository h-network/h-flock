# Naming inventory — tmux lane

Inventory only: this document proposes no rename and changes no interface.
Tier A is documentation, B internal code, C Redis/environment, and D wire.

## `flock.tmux`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `tmux` | `src/flock/tmux/ops.py:4` | doc term | Shared library for driving a tenant's terminal multiplexer, plus guide/trust setup. | Physical terminal fabric behind a port. | B |
| `run_tmux` | `src/flock/tmux/ops.py:56` | identifier | Checked entry point for one tmux subprocess invocation. | Device-driver operation. | B |
| `require_isolated_tmux` | `src/flock/tmux/ops.py:33` | identifier | Refuses ambient tmux unless an explicit socket namespace exists. | Refusing an unspecified network namespace. | B |
| `socket` | `src/flock/tmux/ops.py:33` | identifier | Optional explicit tmux server socket path, not a network socket. | None; collision with network sockets. | B |
| `TMUX_SOCKET` | `src/flock/tmux/ops.py:45` | env var | Explicit tmux socket path accepted as isolation authority. | None; local control endpoint. | C |
| `TMUX_TMPDIR` | `src/flock/tmux/ops.py:45` | env var | Directory that namespaces tmux's default socket. | Network namespace, approximately. | C |
| `AmbientTmuxError` | `src/flock/tmux/ops.py:19` | identifier | Attempt to drive whichever tmux server happens to be ambient. | Accidental use of the default routing domain. | B |
| `TmuxCommandError` | `src/flock/tmux/ops.py:23` | identifier | Non-zero tmux command result, distinct from empty success. | Link-operation failure. | B |
| `window` | `src/flock/tmux/ops.py:66` | doc term | One named terminal hosting one `vab: tmux` agent. | A switch port's attached terminal. | A |
| `create_window` / `kill_window` / `list_windows` | `src/flock/tmux/ops.py:321` | identifier | Idempotent named-window lifecycle operations. | Port provisioning and inventory. | B |
| `window_env` | `src/flock/tmux/ops.py:229` | identifier | Builds the command-scoped environment inherited by an agent pane. | Port attachment configuration. | B |
| `paste_text` | `src/flock/tmux/ops.py:371` | identifier | Performs the complete bracketed paste, delay, and Enter delivery sequence. | Frame transmission onto a terminal link. | B |
| `PASTE_ENTER_DELAY` | `src/flock/tmux/ops.py:15` | env var | Delay separating paste from Enter to prevent CLI input coalescing. | Inter-frame gap, loosely. | C |
| `agent guide` | `src/flock/tmux/ops.py:296` | doc term | Generated `AGENTS.md`/`CLAUDE.md` instructions placed in an agent workdir. | Port-local configuration. | A |
| `project trusted` | `src/flock/tmux/ops.py:112` | doc term | Pre-acceptance of a workdir in each supported CLI's own configuration. | None. | A |
| `profile` | `src/flock/tmux/ops.py:112` | identifier | Named CLI configuration/account directory, not an agent behavioral profile. | None; “profile” is underspecified. | B |
| `endpoint` | `src/flock/tmux/ops.py:235` | identifier | Model-service configuration selected for an agent. | Contradicts the network-model sense of endpoint. | B |

## `flock.tmuxhost`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `tmuxhost` / `TmuxHost` | `src/flock/tmuxhost/host.py:14` | identifier | Long-running reconciler that makes tmux windows match desired roster state. | Port manager/controller. | B |
| `host` | `src/flock/tmuxhost/host.py:14` | doc term | Here means the tmux reconciler, while roster name `host` means lifecycle control. | Collision between physical host and control-plane address. | A |
| `reconcile_once` | `src/flock/tmuxhost/host.py:165` | identifier | One desired-versus-actual window convergence pass. | Control-plane reconciliation. | B |
| `ensure_server_and_session` | `src/flock/tmuxhost/host.py:80` | identifier | Creates missing tmux server/session and applies global options. | Ensuring a switching fabric exists. | B |
| `session_name` | `src/flock/tmuxhost/host.py:21` | identifier | Tmux session target, normally identical to tenant name. | Routing-domain instance name. | B |
| `TMUX_SESSION` | `src/flock/tmuxhost/__main__.py:14` | env var | Override for tmux session name independently of tenant. | Routing-domain override. | C |
| `ROSTER_POLL_SECONDS` | `src/flock/tmuxhost/__main__.py:13` | env var | Delay between desired-state reconciliation passes. | Control-plane refresh interval. | C |
| `get_agent_cli` | `src/flock/tmuxhost/host.py:31` | identifier | Reads the agent's launch program from Redis. | Resolves port attachment implementation. | B |
| `launch` | `src/flock/tmuxhost/host.py:32` | redis key | CLI name tmuxhost must start for an agent. | Port attachment type. | C |
| `profile` | `src/flock/tmuxhost/host.py:39` | redis key | Agent's shared CLI configuration/account name. | None. | C |
| `endpoint` | `src/flock/tmuxhost/host.py:53` | redis key | Indirection name used to find model URL/token environment variables. | Misleading: a model uplink, not the participant endpoint. | C |
| `ENDPOINT_<NAME>_*` | `src/flock/tmuxhost/host.py:61` | env var | URL, token, and model settings for a named model service. | Upstream service configuration. | C |
| `lead` | `src/flock/tmuxhost/host.py:75` | redis key | Tenant-level agent whose generated guide receives leadership instructions. | None. | C |
| `__init__` | `src/flock/tmuxhost/host.py:83` | identifier | Non-agent placeholder window used to keep an empty session alive. | Null/management port, loosely. | B |

## `flock.adapter`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `adapter` | `src/flock/adapter/cli.py:10`, `src/flock/adapter/runner.py:149` | doc term | Names both outbound agent sending and inbound per-envelope delivery—opposite sides of the switch. | Two different NIC directions collapsed into one component name. | B |
| `send` CLI | `src/flock/adapter/cli.py:20` | identifier | Agent-facing command that constructs an envelope and writes its own egress. | Transmit-side NIC operation. | B |
| `run_adapter` | `src/flock/adapter/runner.py:149` | identifier | Acquires per-agent serialization, delivers one ingress envelope, and exits. | Receive-side port service. | B |
| `deliver_one` | `src/flock/adapter/runner.py:69` | identifier | Dispatches one recipient ingress item according to its VAB. | Frame delivery to a selected port type. | B |
| `deliver_api` | `src/flock/adapter/runner.py:26` | identifier | Moves one ingress envelope to an enrolled client's mailbox stream. | Delivery to a different port medium. | B |
| `deliver_unroutable` | `src/flock/adapter/runner.py:43` | identifier | Pops and dead-letters an envelope whose VAB has no implementation. | Unsupported-port drop. | B |
| `opener` | `src/flock/adapter/runner.py:141` | doc term | Kind-specific callable whose normal return means an envelope was opened. | Ethertype handler. | B |
| `message_opener` / `command_opener` / `add_ticket_opener` | `src/flock/adapter/openers.py:55` | identifier | Terminal or board actions selected by envelope kind. | Protocol handlers. | B |
| `opened` | `src/flock/adapter/runner.py:40` | doc term | Terminal outcome meaning an opener completed, not proof a human/CLI consumed it. | Accepted by destination handler, not delivery acknowledgement. | A |
| `delivering` | `src/flock/adapter/runner.py:161` | redis key | Tenant hash serving as a per-agent mutual-exclusion/busy tag. | Per-port transmit lock. | C |
| `paused` | `src/flock/adapter/runner.py:77` | redis key | Marker that leaves ingress queued rather than opening it. | Administratively down port. | C |
| `pending.verify` | `src/flock/adapter/openers.py:43` | redis key | Stream of pasted deliveries awaiting out-of-band activity judgment. | Delivery telemetry awaiting observation. | C |
| `VERIFIABLE_CLIS` | `src/flock/adapter/openers.py:15` | identifier | Allowlist of CLI implementations whose session files can confirm input. | Observable port types. | B |
| `inbox` | `src/flock/adapter/runner.py:33` | redis key | Resumable mailbox stream for a `vab: api` participant. | Receive buffer on an application port. | C |
| `dead` | `src/flock/adapter/runner.py:56` | redis key | Retained list of envelopes that could not be opened. | Dead-letter/drop queue. | C |
| `ingress` | `src/flock/adapter/runner.py:51` | redis key | Recipient-side queue from which delivery pops. | Ingress queue. | C |
| `_CatchAllDict` | `src/flock/adapter/runner.py:11` | identifier | Mapping facade that makes every kind openable for API mailboxes. | Promiscuous protocol handler. | B |

## `flock.control`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `control` | `src/flock/control/runner.py:1` | doc term | VAB that opens tenant lifecycle envelopes addressed to fixed participant `host`. | Control plane. | A |
| `VAB` | `src/flock/control/openers.py:7` | doc term | Selects the receiving implementation (`tmux`, `api`, or `control`); its intended expansion is not recoverable here. | Port/media type, but the acronym does not convey it. | A |
| `host` | `src/flock/control/openers.py:8` | identifier | Fixed roster participant/address for lifecycle operations, not tmuxhost. | Control-plane destination address. | B |
| `deliver_one` | `src/flock/control/runner.py:23` | identifier | Pops and opens one lifecycle envelope; same name as adapter's VAB dispatcher. | Control-plane receive operation. | B |
| `StartAgent` / `StopAgent` | `src/flock/control/runner.py:102` | wire | Envelope kinds that add/remove participant desired state and VAB-specific state. | Provision/deprovision a port. | D |
| `PauseAgent` / `ResumeAgent` | `src/flock/control/runner.py:104` | wire | Envelope kinds that stop/restart a tmux CLI while preserving membership and queues. | Administratively down/up a port. | D |
| `start_agent` / `stop_agent` | `src/flock/control/openers.py:21` | identifier | Desired-state mutations implementing lifecycle kinds. | Port provisioning operations. | B |
| `pause_agent` / `resume_agent` | `src/flock/control/openers.py:111` | identifier | Pause-marker and tmux-process operations implementing temporary suspension. | Port admin-state operations. | B |
| `replace_window` | `src/flock/control/openers.py:27` | identifier | Callback that kills stale actual state so tmuxhost recreates it. | Rebind a port attachment. | B |
| `_STARTABLE_VABS` | `src/flock/control/openers.py:7` | identifier | VAB values lifecycle control accepts for new participants. | Supported port/media types. | B |
| `_FIXED_PARTICIPANTS` | `src/flock/control/openers.py:8` | identifier | Built-in addresses that `StopAgent` cannot remove. | Reserved control-plane addresses. | B |
| `endpoint` | `src/flock/control/openers.py:50` | wire | `StartAgent` payload field selecting a named model service. | Model uplink selection, not participant endpoint. | D |
| `cli` | `src/flock/control/openers.py:40` | wire | `StartAgent` payload name for the desired agent program. | Attachment implementation. | D |
| `launch` | `src/flock/control/openers.py:80` | redis key | Stored name for the same desired agent program called `cli` on the wire. | Attachment implementation. | C |
| `agent` | `src/flock/control/openers.py:13` | wire | Lifecycle target participant name, even when the participant is an API client. | Address/port identity; “agent” is narrower than the set. | D |

## `container/`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `container` | `container/compose.yaml:10` | doc term | Deployment and security boundary containing exactly one tenant. | Network namespace / routing domain boundary. | A |
| `tenant` | `container/compose.yaml:10` | identifier | Compose service name and logical routing domain. | Routing domain. | B |
| `POD` | `container/compose.yaml:22` | env var | Namespace above tenant in every Redis key. | I could not tell what distinct network concept this means without asking. | C |
| `TENANT` | `container/compose.yaml:23` | env var | Tenant identity and default tmux session name. | Routing domain. | C |
| `AGENTS` | `container/compose.yaml:27` | env var | Boot roster seed encoded as comma-separated `name:vab` pairs. | Static MAC/port table seed. | C |
| `AGENT_CLIS` / `AGENT_PROFILES` / `AGENT_ENDPOINTS` | `container/compose.yaml:35` | env var | Comma-separated per-agent exceptions for launch, account config, and model service. | Port configuration maps. | C |
| `API_TOKEN` | `container/compose.yaml:47` | env var | Shared bearer credential for both published doors. | Network access credential. | C |
| `API_HOST` / `SESSION_HOST` | `container/compose.yaml:60` | env var | Host-side publish addresses, not application bind addresses. | Listen/publish address. | C |
| `API_PORT` / `SESSION_PORT` | `container/compose.yaml:58` | env var | Host-side published ports; container-side ports remain 8080/8081. | Port mapping. | C |
| `API_TLS_*` / `SESSION_TLS_*` | `container/compose.yaml:63` | env var | In-container certificate/key paths for each door. | TLS termination material. | C |
| `ALLOW_PLAINTEXT_PUBLISH` | `container/compose.yaml:62` | env var | Explicit operator acceptance of publishing a plaintext door beyond loopback. | Insecure-listener override. | C |
| `FLOCK_ALLOW_PLAINTEXT` | `container/entrypoint.sh:84` | env var | Entrypoint's internal assertion that exposure policy was already evaluated. | Policy handoff flag. | C |
| `REDIS_BIND` / `REDIS_PASSWORD` | `container/entrypoint.sh:89` | env var | Redis listen address and credential required when widened beyond loopback. | Internal switch-store listener security. | C |
| `REDIS_URL` | `container/entrypoint.sh:112` | env var | Connection string handed only to framework processes that need Redis. | Control-plane store address. | C |
| `REDIS_READY_SECONDS` | `container/entrypoint.sh:128` | env var | Maximum boot wait for Redis readiness. | Dependency convergence timeout. | C |
| `ROSTER_POLL_SECONDS` | `container/compose.yaml:28` | env var | Shared refresh interval for router and tmuxhost. | Control-plane refresh interval. | C |
| `WATCHDOG_ENABLED` | `container/entrypoint.sh:272` | env var | Enables the separate human-alerting observer. | Network monitor enable flag. | C |
| `door` | `container/entrypoint.sh:61` | doc term | One externally published API or session process/port. | Network ingress door/listener. | A |
| `start` | `container/entrypoint.sh:9` | identifier | Shell helper that launches a named child and records its PID. | Process supervisor launch, though it is not a supervisor. | B |
| `rcli` | `container/entrypoint.sh:119` | identifier | Auth-aware wrapper around `redis-cli` used during boot seeding. | Control-plane configuration client. | B |
| `startAgent` | `src/flock/tmuxhost/host.py:104` | identifier | CLI launcher applying office-specific approval and model settings; not lifecycle `StartAgent`. | Port-attached process launcher. | B |

## Explicit findings

### One word, two meanings

- **`adapter`** names the outbound `send` CLI (`adapter/cli.py`) and the inbound
  one-envelope receiver (`adapter/runner.py`). They sit on opposite sides of the
  switch and have different lifecycles.
- **`host`** means the tmux reconciliation module and the fixed control-plane
  roster participant.
- **`socket`** in tmux code means a filesystem path to a tmux server, while the
  surrounding network design also uses socket in its ordinary network sense.
- **`endpoint`** means model-service selection here, while the architectural
  model naturally uses endpoint for an addressable participant or termination.
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
- **`VAB`: I could not determine its intended expansion from code.** I can infer
  its function—port implementation/receiving medium—from the values `tmux`,
  `api`, and `control`, but “virtual agent base” does not explain the latter two.

### Names that fight the network model

- `endpoint` denotes an upstream model service instead of a network participant.
- `adapter` merges transmit and receive edges rather than naming one port-side
  function.
- `agent` labels application clients and the lifecycle control participant,
  neither of which is an AI agent.
- `inbox` and `ingress` are usefully distinct but easy to misread: `ingress` is
  the consumed delivery queue for every participant; `inbox` is only the
  resumable mailbox stream for API participants.
