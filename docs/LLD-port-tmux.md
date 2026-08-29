# LLD — The Tmux Port

> **Status: built and running.**
>
> Depends on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for envelope formats and
> [`LLD-port-delivery.md`](LLD-port-delivery.md) for the generic delivery framework,
> busy-tag locking, and registry-based dispatch.
> This document specifies `deliver_tmux` and the tmux openers in `src/flock/port/openers.py`.
> Bringing tmux up — the server, the windows, sizing — is owned by [`LLD-tmux-host.md`](LLD-tmux-host.md).

## 1. Purpose

An agent in a tmux window is a program at an interactive terminal. It cannot pop a queue,
and nothing can hand it an in-memory object — it reads text pasted onto its screen and
submits commands.

The tmux port (`deliver_tmux`) implements delivery for agents hosted in tmux panes (`port_type: tmux`).
It opens envelopes, renders text or saves files, writes delivery verification markers,
and pastes into the agent's window using bracketed paste mode.

```
  ┌───────────────────────────────── deliver_tmux ──────────────────────────────────┐
  │                                                                                 │
  │  1. Parse snapshot-drained envelopes & emit 'received'                          │
  │  2. Batch consecutive Messages into a combined bracketed paste                  │
  │  3. For API sources: append [reply to <client>] trailer                         │
  │  4. For verifiable CLIs: record pending.verify & delivery.markers before paste │
  │  5. Paste into window (or mutate board for AddTicket, write file for Attachment)│
  │  6. Emit 'opened' (or 'dead_lettered' on failure)                               │
  │                                                                                 │
  └─────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Delivery & Burst Batching (`deliver_tmux`)

When invoked by the delivery framework, `deliver_tmux` receives a drained snapshot of
envelopes for the destination agent:

- **Opportunistic burst batching**: Consecutive `Message`-kind envelopes are concatenated
  into ONE combined bracketed paste (`[message from X] text\n` per block, in arrival order),
  requiring only a single lock-acquire/paste/lock-release cycle.
- **Client-sourced reply trailers**: When a message originates from an API port (`port_type == "api"`,
  e.g. `telegram`), the opener appends an actionable `[reply to <client>]` trailer immediately
  after that individual message block:
  ```
  [message from backend] can you review the auth change?
  [message from telegram] can you check the auth status?
  [reply to telegram]
  ```
  The agent reads the name and replies via `office send -a <name> <message>`.
- **Commands, Tickets, and Attachments**: Executable `Command` envelopes, `AddTicket` mutations,
  and `Attachment` deliveries are never batched into message blocks; they are executed
  individually in strict arrival order.
- **Per-envelope custody**: Batching is purely a terminal-layer optimization and is invisible
  to the custody chain. Every drained envelope emits its own `received` record, writes its
  own verification markers (if verifiable), and emits its own `opened` record upon success.

## 3. Opener Implementations

### `Message` — formatted communication
Renders `[message from <source>] <text>\n` (with `[reply to <client>]\n` for API sources).
Pasted into the window using bracketed paste mode with a trailing Enter.

### `Command` — bare remote execution
`{"text": "git status"}`. Pasted bare into the window with **no `[message from …]` prefix**,
so the shell or CLI in that window executes it immediately.

⚠ **`Command` is arbitrary execution in an agent's window.** Handing out access to send `Command`
is equivalent to handing out access to the shell. This capability is deliberate and protected
by bus/API authentication policies.

### `AddTicket` — board mutation, pastes nothing
`{"title": "…", "description": "…", "priority": "…"}`. The `AddTicket` opener creates a v1
ticket entry in the destination agent's `tasks.todo` Redis list, records the `add` event via
`flock.bus.record_task_event`, and **pastes nothing into the window**.

- **No window check**: Writes to `tasks.todo` succeed even if the agent's window is not currently open.
- **Synchronous mutation confirmation**: Returns list depth to confirm write. Success emits `board_write_confirmed`.
  Exceptions or invalid lengths raise `DeadLetter` and emit `dead_lettered`.

### `Attachment` — workspace file write + inert notice
`{"filename": "…", "mime_type": "…", "content_base64": "…", "caption": "…"}`.
- Revalidates schema, filename basename, ASCII MIME type format, and base64 encoding bounds (`ATTACHMENT_MAX_BYTES = 10_485_760`).
- Creates directory `/workdir/<recipient>/attachments/<stream_id>/`.
- Writes decoded bytes to a temporary file and atomically renames (`os.replace`) to target `filename`.
- Writes `pending.verify` and `delivery.markers` markers (deferred custody).
- Pastes an inert notice naming the saved path:
  ```
  [attachment from <source>] saved to /workdir/<agent>/attachments/<stream_id>/<filename> (<mime_type>, <bytes> bytes)
  [attachment caption] <caption>
  ```

## 4. Verification and Usage-Correlation Markers

Before pasting a `Message`, `Command`, or `Attachment` into a `port_type: tmux` window, the
port writes the marker to two bounded Redis Streams:

- `<prefix>:agent:<name>:pending.verify` via `XADD MAXLEN ~ 100`, for the watchdog's
  delivery-verification pass.
- `<prefix>:agent:<name>:delivery.markers` via `XADD MAXLEN ~ 500`, for the activity tailer's
  heuristic join from a later token usage record to the delivery that prompted it.

Entry schema:
```json
{ "stream_id": "<stream_id>", "ts": "<ts>", "correlation_id": "<opt>" }
```

- **Ordering**: Markers are written *before* pasting into the window to eliminate races with fast agent responses.
- **Allowlist `{claude, codex, agy}`**: Recorded only for CLIs whose activity logs are tailed (`VERIFIABLE_CLIS`).
- **Skipped for `bash` and `AddTicket`**: Non-interactive or untailed CLIs skip marker recording.
- **`blocked` watchdog state**: If an agent has produced prior activity and a delivery remains unverified after `VERIFY_AFTER_SECONDS` (default 120s), the watchdog marks the agent `blocked`.

## 5. Getting Text into a Window

- **Paste, do not type**: `load-buffer` followed by `paste-buffer -p`. Bracketed paste prevents the TUI from mistaking paste characters for user keystrokes.
- **Enter is a separate call**: Combined text and Enter can be swallowed as shift+enter by interactive prompts.
- **Delay before Enter (`PASTE_ENTER_DELAY`)**: A delay of **0.5s** (`PASTE_ENTER_DELAY`, read into `ENTER_DELAY` in `src/flock/tmux/ops.py`) is enforced between paste and Enter to prevent CLI input handler coalescing.
- **Subprocess per command**: `tmux load-buffer`, `tmux paste-buffer`, `tmux send-keys` are each executed as independent subprocess calls.

## 6. Safety & Window State

- **Window existence**: The port verifies the window exists via `list_windows`. If missing, the envelope dead-letters.
- **Input box queues**: Text pasted while an agent is generating output is buffered in the CLI's input queue and processed when the turn completes.
- **Modals swallow**: A modal or interactive picker swallows input. The watchdog's `blocked` detection identifies agents stuck in unprompted modals.
