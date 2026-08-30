# Tmux daemon and passive-library boundary

This note describes the current implementation. It does not propose that every
callable in a daemon-owned file is itself a daemon, or that every passive
function is free of side effects. The useful distinction is whether code owns a
continuous control loop or runs only because a caller invoked it.

## The daemon

The continuously running component is the `flock.tmux_reconciler` process:

- `src/flock/tmux_reconciler/__main__.py` is its executable entry point. `main()` reads
  process configuration, constructs `TmuxReconciler`, and calls `run_forever()`.
- `TmuxReconciler.run_forever()` in `src/flock/tmux_reconciler/service.py` owns the loop. It
  connects to Redis, calls `reconcile_once()`, catches and records a failed
  pass, sleeps for `ROSTER_POLL_SECONDS`, and repeats.
- `TmuxReconciler.reconcile_once()` is the daemon's control policy. It reads desired
  participants, keeps only those whose port type is `tmux`, compares them with
  the windows in the managed tmux session, creates missing windows, and removes
  windows with no corresponding desired participant. A manually created window
  in that session is therefore stale and is removed. If it is the last window,
  reconciliation first creates `__init__` so the session survives, then removes
  it.

The following `TmuxReconciler` helpers exist to support that reconciliation policy and
have no independent loop:

- `get_agent_cli()`, `get_agent_profile()`, `get_agent_provider()`,
  `get_agent_resume()`, `get_agent_skip_permissions()`, and
  `get_agent_claude_tools()` resolve desired per-agent launch state.
- `get_lead()` resolves tenant-wide guide state.
- `consume_creation_correlation()` and `log_window_created()` join an asynchronously
  created window to the control envelope that requested it.
- `ensure_server_and_session()` implements the special first-window and
  `__init__` bootstrap required by reconciliation.
- `get_windows()`, `create_window()`, and `kill_window()` adapt the passive tmux
  operations to daemon configuration and custody logging.

These helpers are callable methods, but in the present design they are daemon
internals: the reconciliation loop is their owner and reason for existing.
`src/flock/tmux_reconciler/__init__.py` only exports `TmuxReconciler`; it adds no behavior.

## The passive mechanism library

Nothing under `src/flock/tmux/` runs continuously. Its functions execute only
when tmux_reconciler, ingress delivery, control, a test, or another caller invokes
them.

`src/flock/tmux/ops.py` contains the lowest-level mechanisms:

- `require_isolated_tmux()` and `run_tmux()` enforce socket isolation and run a
  single tmux command.
- `list_windows()`, `create_window()`, `kill_window()`, and `submit_text()` query
  or mutate terminal state on demand. `submit_text()` performs the buffer load,
  paste, delay, and Enter sequence; it is not a delivery loop.
- `window_env()` and `start_agent_command()` construct the environment and argv
  for a pane. The resulting command is normally `startAgent <cli>`, not an
  `h-agent` executable.
- `has_session_history()` selects fresh versus resumed CLI startup.
- `generate_agents_md()`, `_seed_profile_dirs()`, the three
  `ensure_*_project_trusted()` functions, and `write_agent_guide()` prepare a
  work directory and CLI configuration. They have filesystem and subprocess
  side effects, but no background lifecycle.
- `AmbientTmuxError` and `TmuxCommandError` describe mechanism failures.

`src/flock/tmux/handlers.py` is the passive terminal-delivery mechanism:

- `messages_opener()`, `message_opener()`, and `command_opener()` validate that
  the destination window exists and paste input into it.
- `attachment_opener()` validates and writes an attachment, then optionally
  pastes its notice.
- `mark_delivery_pending()` writes verification markers for supported CLIs.

`src/flock/tmux/deliver.py` is an event-driven adapter, not a daemon.
`deliver_tmux()` is called for a destination whose ingress was kicked. It drains
the current ingress snapshot, parses and batches envelopes, invokes an opener,
and returns. It neither polls nor remains resident after that call.

`src/flock/tmux/__init__.py` is a compatibility/export boundary. Its lazy
`__getattr__()` exposes older top-level imports without loading delivery code
until requested. It owns no runtime lifecycle.

## Things that do not fit cleanly

`TmuxReconciler` currently mixes policy and mechanism. `reconcile_once()` and
`run_forever()` are plainly daemon code, while its `get_windows()`,
`create_window()`, and `kill_window()` methods are thin callable wrappers around
`flock.tmux.ops`. They belong to the daemon today because they add configured
session/socket selection and custody records, not because window manipulation
requires a loop.

`ensure_server_and_session()` is both bootstrap mechanism and reconciliation
policy. It issues ordinary tmux commands, but it also chooses the first desired
agent, creates the `__init__` placeholder, prepares the agent guide, selects
resume behavior, and emits `window_created`. Moving it unchanged into a generic
tmux library would leak daemon policy into that library.

The work-directory helpers in `ops.py` are passive, but they are not tmux
operations. Trust seeding, profile seeding, guide generation, and filesystem
writes prepare an agent process before tmux starts it. Their present location
reflects the creation call path rather than a terminal-multiplexer abstraction.

`deliver_tmux()` and the openers are active work but not a daemon: one kick can
cause multiple Redis operations, file writes, and terminal writes, yet the code
has no self-owned loop. “Passive” here means caller-driven, not pure or
read-only.

Control lifecycle handlers are outside both categories. `control/openers.py`
publishes desired participant state; it does not create a tmux window or track
opened sessions. `TmuxReconciler` independently reconciles the `tmux` subset of that
state. Describing control as a module-agnostic opened-session tracker would
therefore be inaccurate.

## Implemented boundary and deferred splits

The minimal structural split makes the daemon identity explicit while keeping
terminal mechanisms independent of desired-state policy:

- `flock.tmux_reconciler.__main__` owns process configuration and the executable
  entry point; the former `tmuxhost` name incorrectly described the daemon as
  the terminal host itself.
- `flock.tmux_reconciler.service.TmuxReconciler` owns `run_forever()` and
  `reconcile_once()`. Its name now states that it is a desired-versus-actual
  controller.
- `flock.tmux.handlers` is the passive delivery-handler module formerly named
  `openers`; its functions can paste terminal input, write files, and record
  verification state rather than merely “open.”
- `submit_text()` replaces `paste_text()` because the operation pastes and then
  submits with Enter.
- `consume_creation_correlation()` replaces `take_window_cause()` because it is
  a destructive one-shot read of a correlation id.

The following larger splits remain deliberately deferred:

- `flock.tmux_reconciler.desired`: typed loading of launch, profile, provider,
  resume, permissions, tools, lead, and creation cause from Redis. The current
  family of `get_agent_*` methods would become `load_agent_spec()` returning one
  `AgentWindowSpec`, avoiding partially assembled configuration.
- `flock.tmux_reconciler.policy`: set comparison and decisions such as
  `missing`, `stale`, and placeholder necessity. This makes the current policy
  that kills unregistered human windows visible and independently testable.
- `flock.tmux.client.TmuxClient`: isolated `run`, `list_windows`,
  `create_window`, `kill_window`, and `submit_text` methods bound to one
  session/socket. This replaces repeated free-function parameters without
  importing roster or Redis concepts.
- `flock.agent_bootstrap`: `window_env`, `start_agent_command`, session-history
  detection, guide creation, profile seeding, and trust seeding. These prepare
  an agent process; they are not intrinsically tmux operations.
- `flock.tmux.delivery`: `deliver_tmux` plus terminal envelope handlers. I would
  keep this separate from the low-level tmux client if those mechanisms are
  later extracted.

Two policy-rich operation renames also remain deferred:

- `ensure_server_and_session()` to daemon-owned `ensure_managed_session()`;
  “server and session” describes implementation, while “managed” signals that
  reconciliation policy applies to every window inside it.
- `create_window()` on the reconciler to `materialize_agent_window()` and the
  low-level client operation to `create_window()`. The distinct names prevent a
  caller from confusing policy-rich agent creation with a raw tmux command.

The central boundary would then be: control publishes desired participants;
`TmuxReconciler` continuously converts desired tmux participants into actual
windows; `TmuxClient`, agent bootstrap, and delivery handlers remain callable
mechanisms with no loop of their own.
