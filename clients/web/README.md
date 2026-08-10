# h-flock Console

The h-flock Console is the browser control surface for one AI office. It gives
an operator one place to answer three questions: who is working, what needs
attention, and what work is moving.

From one page an operator can:

- see every agent's presence and current ticket;
- put blocked and unknown agents ahead of healthy agents;
- inspect live tool activity, messages, alerts and task boards;
- hire, pause, resume and retire agents;
- watch an agent's terminal, then deliberately enable typing when intervention
  is necessary.

The console is intentionally honest about uncertainty. Each panel reports its
own loading, empty, stale, disconnected and error state. A silent office is not
called broken, an unknown agent is not called idle, and a message never implies
that a reply is guaranteed.

## Start the console

The console has no build step and no package installation. Python 3 serves the
vendored browser assets and proxies one tenant's HTTP, event-stream and terminal
connections through the same origin.

For local access on the machine running h-flock:

```bash
cd clients/web
API_TOKEN=<tenant-token> python3 server.py
```

Open <http://127.0.0.1:8090>. The server enrols an idempotent API participant
named `web`, keeps the tenant token server-side, and connects to the API at
`http://127.0.0.1:8080` and session door at `http://127.0.0.1:8081` by default.

To serve other operators, configure the shared operator secret and bind the
intended interface:

```bash
API_TOKEN=<tenant-token> \
HFLOCK_SECRET=<long-random-operator-secret> \
python3 server.py --listen 0.0.0.0
```

The process refuses any non-loopback bind without an operator secret. Operators
receive a login page; the console API and terminal socket reject requests
without a valid session cookie.

Use TLS at the network edge whenever the console crosses a trusted host. The
shared secret, session cookie, messages and terminal traffic are sensitive even
though the tenant API token never enters the browser.

## Configuration

Command-line options override the corresponding environment defaults.

| Purpose | Option | Environment | Default |
|---|---|---|---|
| listen address | `--listen` | `WEB_LISTEN` | `127.0.0.1` |
| console port | `--port` | `WEB_PORT` | `8090` |
| tenant API | `--api` | `HFLOCK_API` | `http://127.0.0.1:8080` |
| terminal session door | `--session` | `HFLOCK_SESSION` | `http://127.0.0.1:8081` |
| tenant bearer token | `--token` | `API_TOKEN` | required |
| console participant name | `--client` | `HFLOCK_CLIENT` | `web` |
| shared operator secret | `--secret` | `HFLOCK_SECRET` | none on loopback |
| simultaneous terminal sockets | — | `HFLOCK_MAX_SESSIONS` | `16` |
| operator session lifetime, seconds | — | `HFLOCK_SESSION_TTL` | `86400` (24 hours) |
| failed logins allowed per window/IP | — | `HFLOCK_MAX_LOGIN_ATTEMPTS` | `5` |
| login rate-limit window, seconds | — | `HFLOCK_RATE_LIMIT_WINDOW` | `60` |

Run `python3 server.py --help` for the command-line surface.

## What operators see

The page summary reports working agents, blocked agents and active alerts at a
glance. The roster groups agents in action order—blocked, unknown, pending,
working, then idle—so a problem cannot hide below healthy rows. A new office
with infrastructure participants but no tmux agents shows a single clear next
step: hire the first agent.

Panels fail independently. Presence and boards poll because the API exposes
them as snapshots. Alerts, activity and messages resume event streams from
browser-persisted cursors with visible reconnect attempts and capped backoff.
Prior data remains visible but is marked stale after a failed refresh. A server
error in one panel does not make the rest of the office look offline.

The console remains bounded under normal office load:

- the roster is grouped and keyboard navigable at 40 agents;
- the alert history is capped at the newest 300 entries, folds repeated
  condition/subject pairs into severity-coded rows with multipliers, and
  batches catch-up rendering;
- activity and message histories retain 100 entries each;
- boards keep all tickets available inside collapsible, independently scrolling
  agent rows.

Every timestamp is relative at rest and absolute on hover. Blocked and unknown
states use words, shapes and borders rather than relying on colour. The console
supports keyboard navigation, visible focus, screen-reader regions, responsive
layout, and system light/dark preference.

## Operator workflow and preferences

One global search filters agent identity and presence, alert facts, and every
board ticket at the same time, with a result count for each panel. `Ctrl/⌘-K`
opens a command palette for agents, lifecycle actions, boards, alerts and
display settings. Press `?` for the complete shortcut reference; shortcuts not
listed there are not part of the interface.

Comfortable and compact density, system/light/dark theme, the last selected
agent and the office/detail column balance persist in one namespaced
`localStorage` preference record. It contains display choices only—never the
operator secret, tenant token, messages, terminal content or commands.

The message composer is multi-line. `Ctrl/⌘-Enter` sends, Up recalls the most
recent sent text when the caret is at the start, and the interface says plainly
that a reply may never arrive. Sent-text recall is bounded to the current page
session and is not persisted.

Desktop notification permission and mute/deduplication machinery are present,
but alert delivery is deliberately not enabled. The alert API is historical
and has no resolved event, so the browser could create a notification but could
not honestly retire it when the condition clears. Delivery remains gated until
the framework exposes an observable alert lifecycle.

## Lifecycle semantics

Hiring creates a tmux agent through the same control-envelope path used by other
clients. The roster row appears before the window and CLI finish reconciling, so
the console shows the hire as pending rather than failed.

Pause and retire are different operations:

- **Pause** stops the CLI but preserves identity, queues, boards and window.
  Envelopes queue and drain after resume.
- **Retire** removes roster membership and identity state. It preserves queues
  and boards for a later re-hire, and requires typing the agent name to confirm.

The console does not expose a `Command` action. Terminal typing is read-only in
the UI until an operator explicitly changes its visible mode.

## Security model

The Python server is a security boundary, not just a static-file server. It
keeps the bearer token out of HTML, JavaScript, browser storage and query
strings; attaches it only on upstream requests; authenticates HTTP, SSE and
WebSocket access; limits request bodies and simultaneous terminal sockets; and
times out slow clients.

Operator authentication uses one shared secret and an opaque `HttpOnly`,
`SameSite=Strict` session cookie. Secret and session-token comparisons are
constant-time. By default, five failed logins from one IP within 60 seconds
trigger HTTP 429 with a `Retry-After` response. Sessions expire after 24 hours
by default and also end at explicit logout or server restart. The attempt limit,
window and session lifetime are configurable with the environment variables
listed above. See the limitations below before exposing the console beyond a
trusted operator network.

## Deliberate limitations

The console does **not** currently provide:

- individual operator identities, roles or RBAC;
- attribution of a lifecycle action or terminal keystroke to a named person;
- a durable, multi-operator alert acknowledgement model—alerts are active facts,
  not browser-local checkboxes;
- tenant selection or a combined view across several offices;
- a general command-execution button;
- a guarantee that an agent will reply to a message;
- indefinite browser history—each high-volume view has the stated cap;
- server persistence for operator sessions—restart invalidates every session.

The shared secret answers “may this operator enter?”, not “which operator did
this?”. Real acknowledgement would likewise require a backend identity, actor
and timestamp. Inventing either feature in browser-local state would make two
operators see different truths.

## Failure and recovery behavior

- An HTTP 500 is not treated as a network drop. It remains a panel-local server
  failure, with prior data preserved where available.
- A polling panel keeps its last data and marks it stale when a refresh returns
  an HTTP error. A first-load failure shows an error and Retry action.
- EventSource does not expose an SSE response status. A stream-side
  error is therefore shown as disconnected with attempt count and backoff,
  rather than being mislabelled as a particular HTTP failure.
- Mailbox silence is valid and is not treated as a dead socket.
- Saved cursors resume alert, activity and message streams after reload. If a
  cursor has aged out of server retention, the API does not currently expose a
  distinct expiry error.

## Demo and verification

Run the built-in fixtures without a tenant or token:

```bash
python3 clients/web/server.py --demo
```

Demo mode supplies working, idle, blocked and unknown agents, mixed board entry
shapes, 300 alerts, held event streams and terminal fixtures. Its toolbar can
force each panel's loading, empty, error, stale and disconnected presentation.
It is useful for review and accessibility work; it is not evidence that a real
tenant is healthy.

The browser assets are source files under `clients/web/`: ES modules under
`ui/`, vendored xterm assets under `vendor/`, and no npm, framework, bundler or
generated distribution. This keeps the console inspectable, offline-capable and
deployable in an air-gapped tenant.

Automated checks live under `clients/web/tests/`. Product verification should
also use a real tenant, exercise a terminal handshake, interrupt a live stream,
and confirm that each affected panel reconnects without taking down the page.

The Part II visual harness was run in Chromium in light and dark at 1600×900,
1280×720 and 1024×768. All six renders had no horizontal overflow, console
errors or failed requests. After fixed header tracks removed asynchronous
wrapping, cumulative layout shift measured 0.018–0.025 and remained stable on
independent reruns. Screenshots were inspected: the idle office overview,
retained last-activity column and severity-grouped alert history rendered as
specified. Rendering is verified; a screenshot alone does not establish frame
rate, so performance claims remain limited to the explicit data and DOM caps.
