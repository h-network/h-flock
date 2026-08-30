# Interface Lane: Session Door and Bundled Clients Architecture

This document maps the real runtime structure, process lifecycles, and component boundaries of the **interface lane** (`src/flock/session`, `clients/telegram`, and `clients/web`) to support the design of the next-generation architecture.

---

## 1. Continuously-Running Daemons vs. Per-Request / Passive Mechanisms

The interface lane contains three distinct software subsystems, each mixing long-lived server/daemon loops with per-connection or per-request mechanics:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. flock.session (:8081)                                                    │
│    FastAPI/Uvicorn Daemon ──► ControlModeClient (tmux -C Subprocess)        │
│          ▲                              ▲                                   │
│          │ WebSocket                    │ stdio (%output / send-keys)       │
│          ▼                              ▼                                   │
│    Client Connections             Tenant Tmux Server                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. clients/web (server.py :8090)                                            │
│    ThreadingHTTPServer Daemon ──► Proxy & Auth Engine                       │
│          ▲                              ├──► REST API (:8080)               │
│          │ HTTP / WS / SSE              └──► Terminal Session (:8081)       │
│          ▼                                                                  │
│    Browser Operator / Mini App                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. clients/telegram (bot.py)                                                │
│    Long-Polling Bot Daemon ──► Background Pushers & Watchers                │
│          ▲                              ├──► Mailbox Poller (GET :8080)     │
│          │ getUpdates                   ├──► Alerts Stream (SSE :8080)      │
│          ▼                              ├──► Activity Stream (SSE :8080)    │
│    Telegram Cloud API                   └──► Terminal Watcher (WS :8081)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 `src/flock/session` (The Terminal WebSocket Door)

#### Continuously-Running Components
- **Process Entry Point & ASGI Server Loop (`src/flock/session/__main__.py:main()`):**
  Runs `uvicorn.run()` on `SESSION_BIND:SESSION_PORT` (default `127.0.0.1:8081`). Maintains the asynchronous network event loop, socket listening, TLS termination (`ssl_certfile`/`ssl_keyfile`), and HTTP upgrade handling.
- **FastAPI Lifespan Manager (`src/flock/session/app.py:lifespan()`):**
  Manages the lifecycle of the shared `ControlModeClient`. Calls `await controller.start()` at server boot and `await controller.stop()` on server shutdown.
- **Control-Mode Client Subprocess & Stream Reader Tasks (`src/flock/session/control.py:ControlModeClient`):**
  - `start()`: Spawns the long-lived OS subprocess `tmux -S <socket> -C attach-session -f ignore-size -t <session>`.
  - `_read_control_stream()`: An infinite `asyncio` task continuously reading lines from the `tmux -C` stdout pipe. Parses asynchronous `%output`, `%window-add`, `%window-close`, `%window-renamed`, `%begin`, `%end`, `%error`, and `%exit` notifications.
  - `_drain_stderr()`: An infinite `asyncio` task reading and discarding the subprocess stderr pipe to prevent OS buffer blocking.
  - `_refresh_after_notification()`: Background task scheduled automatically when window lifecycle notifications arrive from tmux.

#### Per-Connection / Per-Request Mechanisms
- **WebSocket Connection Endpoint (`src/flock/session/app.py:session_socket()`):**
  - `_authorized()`: Validates token on connect via `Authorization: Bearer` header or `?token=` query parameter (checked using constant-time `hmac.compare_digest`).
  - Connection Tasks: For each active client, creates a pair of coroutines:
    1. `forward_output()`: Drains `Subscriber.queue` and writes frames over the WebSocket (`websocket.send_json`).
    2. Message loop: Awaits `websocket.receive_text()`, parses incoming JSON, validates mode immutability, validates subscription arrays, and calls controller methods.
  - `_connection_log()`: Formats and emits a single structured audit record on socket termination to stdout and `flock.bus.mirror`.
- **On-Demand Controller Operations (`src/flock/session/control.py`):**
  - `command(*args)`: Executes a synchronous tmux command through the control client under `_command_lock`, returning an `asyncio.Future` resolved by the stdout stream reader.
  - `refresh_panes()`: Queries `list-panes -s -t <session>` to update pane-to-agent and agent-to-pane index mappings.
  - `update_subscription(subscriber, agents, refresh=False)`: Generates visible screen snapshots using `capture-pane -p -e -t <pane>` and `display-message -p -t <pane> "#{cursor_y} #{cursor_x}"`, buffers live deltas, and delivers the initial frame.
  - `send_keys(agent, data)`: Encodes string data into hexadecimal bytes and executes `send-keys -t <pane> -H ...`.
  - `_unescape_control(data)`: Pure stateless regex function converting tmux octal escape sequences (`\033`, `\\`) back into raw binary bytes.

---

### 1.2 `clients/telegram` (The Unattended In-Tenant Telegram Client)

#### Continuously-Running Components
- **Bot Long-Polling Loop (`clients/telegram/bot.py:TelegramBot.run()`):**
  Repeatedly executes `getUpdates` against `https://api.telegram.org/bot<token>` with a 30-second long-polling timeout, dispatching incoming updates to handlers.
- **Mailbox Delivery Pusher (`clients/telegram/bot.py:ReplyPusher`):**
  A dedicated background daemon thread running an infinite polling loop:
  - Periodically polls `GET /agents/telegram/messages?after=<cursor>`.
  - For each new envelope, formats the reply (text, voice audio note via `edge-tts`, or attachment document) and delivers it to the target chat.
  - Atomically commits the updated mailbox cursor to disk via `CursorStore`.
- **Alert Stream Pusher (`clients/telegram/bot.py:AlertPusher`):**
  A dedicated background daemon thread consuming the Server-Sent Events (SSE) stream `GET /alerts/stream?after=<cursor>`. Pushes `blocked`, `stalled`, and `credential` alerts to the configured chat in real time.
- **Ephemeral Background Tasks:**
  - `watch_activity_stream()` (`ActivityWatcher`): Started on user prompt; tails `GET /agents/{agent}/activity/stream` via SSE and edits a rolling progress message (`editMessageText`) throttled to ~1/sec until completion.
  - `_watch_pane_loop()`: Started by `/watch <agent>`; maintains an active WebSocket connection to `:8081` session door, requesting periodic screen snapshots (`refresh: true`), cropping CLI chrome, and editing the live pane message.

#### Per-Request / Passive Mechanisms
- **One-Shot CLI Modes (`--prompt`, `--status`, `--menu`):**
  Execute a single HTTP request against the local API door and write formatted text to stdout without launching the poller or background pusher threads.
- **REST & Telegram API Clients (`FlockClient`, `TelegramClient`):**
  Stateless HTTP transport wrappers providing structured methods for tenant and Telegram endpoints.
- **Formatting and Validation Helpers:**
  `PaneWatchRender`, `ActivityRender`, `_strip_ansi()`, `_pane_tail_window()`, `_valid_attachment_filename()`, `_valid_attachment_mime_type()`.

---

### 1.3 `clients/web` (The Operator Web Console and Mini App Gateway)

#### Continuously-Running Components
- **HTTP Server (`clients/web/server.py:main()`):**
  Instantiates `HTTPServer` (or `ThreadingHTTPServer`) bound to `WEB_LISTEN:WEB_PORT` (default `127.0.0.1:8090`), managing thread-per-request concurrency for incoming browser connections.
- **WebSocket Reverse Proxy Tunnel (`clients/web/server.py:_do_proxy_websocket()`):**
  When a browser requests a WebSocket upgrade on `/session`:
  - Enforces operator authentication and concurrent session caps (`HFLOCK_MAX_SESSIONS`, default 16).
  - Opens an upstream TCP connection to `flock.session` (`session_host:session_port`).
  - Rewrites the HTTP upgrade handshake to inject `Authorization: Bearer <API_TOKEN>`.
  - Spawns two persistent threads (`forward(client, upstream)` and `forward(upstream, client)`) that bi-directionally stream raw WebSocket frames until disconnection.
- **SSE Stream Tunneling (`clients/web/server.py:_proxy()`):**
  Maintains open chunked HTTP connections streaming server-sent events (`/alerts/stream`, `/activity/stream`) from the tenant API to the browser.

#### Per-Request / Passive Mechanisms
- **Operator Authentication & Security Boundary:**
  - `_handle_login()`: Constant-time operator secret verification, IP rate limiting (5 attempts / 60s -> HTTP 429), session cookie generation (`hflock_session`).
  - `_handle_telegram_auth()`: Cryptographic HMAC-SHA256 verification of Telegram WebApp `initData`, `auth_date` replay protection, user ID validation against `TELEGRAM_CHAT_ID`.
  - `_telegram_read_allowed()`: Strict endpoint allowlist for read-only Telegram Mini App sessions.
- **API Proxy & Audit Logger:**
  - `_proxy()`: Forwards HTTP requests to `HFLOCK_API`, attaching `API_TOKEN` server-side so credentials never enter the client environment.
  - `_audit_log()`: Appends structured JSON records to `audit.jsonl` / `GET /api/audit` recording operator actions (logins, logouts, lifecycle actions, message dispatches).
- **Static Asset Serving:**
  Serves zero-build vanilla ES modules (`index.html`, `mini.html`, `style.css`, `ui/*.js`, `vendor/*.js`).
- **Browser-Side Modules (`clients/web/ui/*.js`):**
  Client-side UI controllers executing entirely within the operator's browser (`router.js`, `terminal.js`, `messages.js`, `activity.js`, `agents.js`, `alerts.js`, `boards.js`, `lifecycle.js`, `recordings.js`, `audit.js`, `preferences.js`, `palette.js`).

---

## 2. Structural Map of the Interface Lane

### 2.1 File and Module Map

```
src/flock/session/
├── __init__.py           # Exports SessionSettings and create_app
├── __main__.py           # Uvicorn server entry point (main())
├── app.py                # FastAPI app, /session WebSocket route, auth, connection logging
└── control.py            # ControlModeClient, tmux -C subprocess management, Subscriber queues

clients/telegram/
├── __init__.py           # Package marker
├── bot.py                # All-in-one Telegram client daemon, pushers, formatters, and CLI handlers
└── README.md             # Comprehensive operational and specification guide

clients/web/
├── server.py             # Multi-threaded Python server, auth boundary, REST & WebSocket proxy
├── index.html            # Primary operator console SPA entry point
├── mini.html             # Telegram Mini App dashboard entry point
├── app.js                # Full console application bootstrap and UI router initialization
├── mini-app.js           # Mini App lightweight bootstrap (read-only panels)
├── style.css             # Unified CSS custom properties, design tokens, and components
├── terminal.css          # Terminal-specific styling and layout rules
├── ui/                   # Browser ES modules (one responsibility per file)
│   ├── activity.js       # Inline activity stream renderer
│   ├── agents.js         # Roster panel and agent detail views
│   ├── alerts.js         # Alerts feed, grouping, and banner notifications
│   ├── audit.js          # Operator action audit log explorer
│   ├── boards.js         # Kanban task board renderer (todo/doing/done/hold)
│   ├── lifecycle.js      # Hire, Pause, Resume, and Retire dialogs
│   ├── messages.js       # Conversation history and multi-line composer
│   ├── palette.js        # Command palette (Ctrl/Cmd-K)
│   ├── preferences.js    # LocalStorage settings (density, theme, sizes)
│   ├── recordings.js     # Terminal session recording and playback
│   ├── router.js         # Hash-based application shell and section router
│   ├── shared.js         # Shared formatters, relative timestamps, SVG icons
│   └── terminal.js       # xterm.js wrapper, multi-pane grids, recording hook
├── vendor/               # Zero-build vendored dependencies (xterm.js, search addon)
├── tests/                # Automated security, routing, and attack surface tests
├── SPEC.md               # Product specification and UI design contract
└── README.md             # Architecture, operational instructions, and security model
```

---

## 3. Components That Do Not Fit Cleanly into Daemon vs. Passive-Library

Several components in the interface lane bridge daemon and library behaviors in ways that make simple classification incomplete:

### 3.1 `ControlModeClient` (`src/flock/session/control.py`)
- **Hybrid Nature:** It is not an independent OS daemon process, yet it is far from a stateless passive library.
- **Why it does not fit cleanly:**
  - It maintains a persistent stateful OS child process (`tmux -C attach`).
  - It runs multiple background asyncio tasks (`_read_control_stream`, `_drain_stderr`, `_refresh_after_notification`).
  - It maintains complex in-memory state: pane-to-agent bidirectional indexes, pending command futures (`_pending`), command serialization locks (`_command_lock`), and subscriber fan-out registries (`_subscribers`).
  - It acts as an **in-process multiplexing controller** embedded within the FastAPI server.

### 3.2 Web Console Server (`clients/web/server.py`)
- **Hybrid Nature:** Combines a local application server, static file host, reverse proxy gateway, and security firewall into a single procedural class (`ConsoleHandler(SimpleHTTPRequestHandler)`).
- **Why it does not fit cleanly:**
  - It proxies HTTP, SSE streams, and raw WebSocket TCP sockets while simultaneously enforcing session authentication and IP rate limits.
  - It holds server-wide in-memory state (`valid_sessions`, `login_attempts`, `active_sockets_set`, `active_sessions`) protected by threading locks on the `HTTPServer` instance.
  - It acts as a **protocol translator and security barrier**, not merely a web server.

### 3.3 Telegram Client (`clients/telegram/bot.py`)
- **Hybrid Nature:** A monolithic 2,866-line file that serves simultaneously as an interactive CLI tool, an autonomous background daemon, an SSE stream subscriber, a WebSocket terminal consumer, and a media pipeline (Edge-TTS and attachment processing).
- **Why it does not fit cleanly:**
  - It mixes one-shot command execution (`--prompt`, `--status`) with multi-threaded daemon architectures (`ReplyPusher`, `AlertPusher`, `ActivityWatcher`, `PaneWatcher`).
  - It embeds direct disk cursor persistence (`CursorStore`) alongside HTTP client drivers.

### 3.4 WebSocket Connection Lifecycle vs. HTTP Request Lifecycle
- In standard REST APIs (like `flock.api`), requests are short-lived, stateless transactions.
- In `flock.session.app`, a WebSocket connection is a **long-lived stateful entity** with its own task lifecycle, output queue, subscription list, and immutable mode state (`read-only` vs `read-write`).

---

## 4. Proposed Redesign, Modular Split, and Vocabulary

If given full freedom to reorganize and rename this lane for the next-generation architecture (e.g. `h-mesh`), I would resolve naming ambiguities, separate concerns into distinct modules, and adopt a cleaner domain vocabulary.

### 4.1 Resolving the "Session" Naming Overload

The term **`session`** is heavily overloaded in this codebase:
1. **Tmux session** (`TMUX_SESSION="hq"` — the multiplexer session).
2. **CLI conversation session** (the agent CLI's disk JSONL transcripts).
3. **Operator web session** (`hflock_session` cookie — the web login token).
4. **Session door** (`:8081` / `flock.session` — the terminal streaming door).

#### Proposed Rename: `flock.terminal` (or `flock.terminal_door`)
Renaming `flock.session` to `flock.terminal` immediately clarifies that its sole responsibility is moving raw terminal bytes and keystrokes.

---

### 4.2 Proposed Modular Decomposition

#### 1. `flock.terminal` (Replacing `src/flock/session`)
Split the monolithic `control.py` and `app.py` into focused single-responsibility modules:

```
src/flock/terminal/
├── __init__.py               # Public API exports
├── __main__.py               # Server entry point and CLI runner
├── config.py                 # TerminalSettings, TLS validation, bind rules
├── server.py                 # FastAPI/ASGI application factory, lifespan, health routes
├── websocket.py              # WebSocket endpoint (/terminal), auth check, frame router
├── protocol.py               # In-band message schemas (subscribe, keystroke, error frames)
├── control/
│   ├── __init__.py
│   ├── client.py             # TmuxControlClient: subprocess lifecycle, stdout reader
│   ├── command.py            # Async command execution and request/response resolution
│   ├── escaping.py           # Tmux octal unescaping and hex-byte key encoding
│   └── panes.py              # Pane-to-agent mapping and window lifecycle updates
└── subscription/
    ├── __init__.py
    ├── subscriber.py         # Subscriber model, bounded queue (1000), drop policy
    ├── registry.py           # Fan-out registry mapping agents to subscribers
    └── snapshot.py           # capture-pane execution, cursor query, and snapshot framing
```

#### 2. `clients.telegram` (Decomposing `clients/telegram/bot.py`)
Decompose the 2,866-line monolith into structured packages:

```
clients/telegram/
├── __main__.py               # CLI entry point (handles flags, dry-run, one-shots)
├── bot.py                    # Main TelegramBot orchestrator and polling loop
├── config.py                 # Environment variables and CLI argument parsing
├── client/
│   ├── flock.py              # FlockApiClient: REST API wrapper with backoff
│   └── telegram.py           # TelegramApiClient: Bot API wrapper
├── pushers/
│   ├── mailbox.py            # ReplyPusher: polls mailbox and delivers replies
│   ├── alerts.py             # AlertPusher: SSE stream listener for alerts
│   └── activity.py           # ActivityWatcher: SSE stream listener for tool runs
├── watch/
│   ├── pane.py               # PaneWatcher: WebSocket client to terminal door
│   ├── chrome.py             # Bottom chrome cropping and CLI-specific heuristics
│   └── render.py             # Throttled editMessageText pane renderer
├── media/
│   ├── voice.py              # Edge-TTS synthesizer and audio formatting
│   └── attachments.py        # Photos & documents download, validation, and Base64
├── ui/
│   ├── keyboard.py           # Sticky ReplyKeyboardMarkup and ReplyKeyboardRemove
│   ├── inline.py             # Inline keyboards (agent grid pickers, priority)
│   └── flows.py              # Multi-step state machines (AddTicket, Hire, Retire)
└── storage/
    └── cursor.py             # CursorStore: thread-safe JSON cursor persistence
```

#### 3. `clients.web` (Decomposing `clients/web/server.py`)
Separate proxying, authentication, and API handling:

```
clients/web/
├── server/
│   ├── __main__.py           # Console server entry point
│   ├── app.py                # HTTP request routing and dispatch
│   ├── config.py             # Server configuration, ports, secrets
│   ├── auth/
│   │   ├── secret.py         # Operator shared secret validation and cookie issue
│   │   ├── rate_limit.py     # IP-based rate limiting (429 Retry-After)
│   │   └── telegram.py       # Telegram Mini App initData HMAC verification
│   ├── proxy/
│   │   ├── rest.py           # HTTP REST proxy with API_TOKEN injection
│   │   ├── sse.py            # Server-Sent Events streaming proxy
│   │   └── websocket.py      # Upstream terminal WebSocket proxy (with full TLS support)
│   └── api/
│       ├── audit.py          # Operator action logging (/api/audit)
│       └── recordings.py     # Session recording storage and playback (/api/recordings)
└── ui/                       # Frontend assets (retained as vanilla ES modules)
```

---

### 4.3 Proposed Vocabulary and Method Renamings

| Current Name | Proposed Name | Rationale |
|---|---|---|
| `flock.session` | `flock.terminal` | Eliminates overload with tmux sessions, CLI transcripts, and web login cookies. |
| `ControlModeClient` | `TmuxControlDriver` | Clarifies that it is an active driver managing a tmux control-mode subprocess. |
| `ControlModeClient.command()` | `execute_tmux_command()` | Disambiguates raw tmux multiplexer commands from fabric `Command` envelopes. |
| `update_subscription()` | `set_subscribed_agents()` | Accurately describes setting the target agent set for a subscriber. |
| `send_keys()` | `submit_keystrokes()` | Clarifies that input is keystroke text delivered to a terminal window. |
| `_unescape_control()` | `unescape_tmux_octal()` | Explicitly names what is being transformed (octal sequences from tmux `%output`). |
| `_connection_log()` | `log_terminal_connection_closed()` | Distinguishes terminal connection closure from operator login session logs. |
| `ReplyPusher` | `MailboxReplyForwarder` | More accurately describes its role bridging the agent's mailbox to Telegram. |
| `AlertPusher` | `AlertStreamForwarder` | Accurately describes forwarding real-time alerts from SSE stream to Telegram. |
| `PaneWatchRender` | `TerminalWatchRenderer` | Standardizes terminology around watching live terminals. |
