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

### Running as its own container

`container/web.Dockerfile` packages this server as its own image, separate
from the tenant image (`container/Dockerfile`) — for running the console
(and the Mini App auth path it now hosts) as its own container on a tenant's
docker network, fronted by a reverse proxy, rather than a bare `python3
server.py` on an operator's own machine. `python:3.12-slim`, no pip install
(this file is stdlib-only). Binds `WEB_LISTEN=0.0.0.0` inside its own
container by design — the same rule `API_BIND`/`SESSION_BIND` already
document for the tenant's doors — which means `HFLOCK_SECRET` is **required**
for it to start at all (server.py refuses a non-loopback bind without one).
`WEB_PORT` is deliberately not set in the image, so server.py's own default
(`8090`) stays the only place that value lives. `HFLOCK_API`/`HFLOCK_SESSION`
must point at the tenant over whatever network connects the two containers —
`127.0.0.1` will not reach anything from inside this one. TLS is out of
scope here; a reverse proxy in front terminates it, same pattern the api and
session doors already use for their own published ports. See the tenant
provisioning tooling for how a compose service wires the two containers
together and publishes a host port.

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
| Telegram bot token, for Mini App login | `--telegram-bot-token` | `TELEGRAM_BOT_TOKEN` | unset — feature disabled |
| Telegram user id allowed to sign in via the Mini App | `--telegram-chat-id` | `TELEGRAM_CHAT_ID` | unset — feature disabled |

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

### Operator Action Log scope and API invariants

- **Console Operator Action Log Scope**: The console operator action log (`GET /api/audit` / `audit.jsonl`)
  records operator authentications, session state changes, lifecycle calls, console prompt dispatches, and terminal
  recordings performed **through the console proxy**. Operations performed directly against
  the tenant API using an `API_TOKEN` without passing through the console server bypass
  the console operator action log entirely. Direct API token traffic is tracked in tenant bus/adapter stdout logs and agent activity feeds (`GET /agents/{agent}/activity`).
- **Producer Identity (Invariant 2)**: Tenant API envelopes carry a `source` attribute.
  Possessing the tenant `API_TOKEN` authorizes producing messages to the tenant API, but
  the backend does not enforce sub-client source identity bindings. Any client with the
  tenant token may specify any source string in an envelope body.

## Telegram Mini App (read-only, v1)

`mini.html` + `mini-app.js` is a second, much smaller front end this same
server proxies: a `web_app` button in `clients/telegram/bot.py`'s sticky menu
(📊 Dashboard, shown only when `MINI_APP_URL` is configured for the bot)
opens it inside Telegram's own WebView. It reuses the console's existing
panel modules (`AgentsPanel`, `AlertsPanel`, `BoardsPanel` — same API client,
same freshness states) rather than a second implementation of any of them.

**Read-only, and not by convention.** This page carries no hire dialog, no
lifecycle buttons, no message composer and no terminal — there is nothing on
it that could send a write, not just nothing visible that does. The server
enforces the same boundary independently of what the page happens to render:
a session created via `/api/telegram-auth` gets every `POST /api/*` refused
with `403` and the `/session` terminal socket refused outright, regardless of
what any future page might try to send. Lifecycle actions and terminal
access were deliberately left for a later pass rather than guessing whether
the console's existing safety assumptions — built around a human typing an
operator secret — still hold for a session an initData POST created instead;
see the branch history for that reasoning in full.

**GET is scoped the same explicit way, not left to "whatever the page calls."**
`_telegram_read_allowed` (`server.py`) is an allowlist — exactly
`/agents`, `/agents/<name>` (bare presence, not a sub-resource), `/board`,
`/alerts` and `/alerts/stream`, the paths `mini-app.js`'s panels actually
call — checked on every `GET /api/*` for a Telegram-origin session before
any handler runs. `/api/recordings` (byte-for-byte terminal capture),
`/api/audit` (the operator action log) and `/agents/<name>/conversation`
(full message transcripts) are reads too, and meaningfully more sensitive
than the roster/alerts/board glance this page shows — reachable through the
same generic proxy path any authenticated session uses, so this needed the
same explicit treatment the write boundary already had, and initially
didn't get it: a review caught that GET was scoped only by what the page
happened to call, not by anything the server enforced, which was an
oversight relative to how carefully the write side was reasoned, not a
considered call. An allowlist rather than naming those three paths to
exclude also means a new api endpoint added later does not silently become
reachable from a Mini App session just by existing.

**Auth is Telegram's own scheme, reused rather than duplicated.** The Mini
App SDK hands the page `Telegram.WebApp.initData`, which Telegram itself
signs with `HMAC-SHA256("WebAppData", bot_token)` — the same
HMAC-over-canonical-payload shape `docs/API.md`'s per-client `kid`/`sig`
signatures already use elsewhere in this project, so this reuses the
primitive rather than inventing a second one. The login page
(`_serve_login_page` in `server.py`) detects a Telegram WebView and POSTs
`initData` to `POST /api/telegram-auth` instead of showing the operator-secret
form; the server validates the signature, checks `auth_date` is within a
short window (Telegram doesn't expire `initData` itself — a captured string
would otherwise be a permanent login token), and then checks the signed
user id against `TELEGRAM_CHAT_ID` — the same single-operator allowlist
`clients/telegram/bot.py`'s `_chat_allowed` already enforces for the bot
itself. A cryptographically valid initData for a *different* Telegram user is
still refused: the signature proves it came from Telegram for this bot, not
that the signer is authorized. On success it sets the exact same
`HttpOnly`/`SameSite=Strict` session cookie a secret login sets — this is a
second way to *reach* a session, not a second authorization model — and
redirects to `/mini.html` rather than `/` (the full, write-capable console).

**Both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are required together**;
either absent disables the feature (`/api/telegram-auth` answers `404`) and
`/login`'s operator-secret flow is entirely unaffected — same variable names
`clients/telegram/bot.py` already uses for the same bot and the same single
operator, deliberately, since a Mini App login is "prove you're the person
the bot already only talks to," not a second identity to configure.

**Testing it needs a real public HTTPS origin** — Telegram's own requirement
for a `web_app` button to open on a device, not something this codebase can
route around. For development, run this server normally and put a temporary
tunnel (e.g. `cloudflared tunnel --url http://127.0.0.1:8090`) in front of it
just long enough to open the Dashboard button from a phone; tear the tunnel
down afterward. That URL is never committed anywhere — set `MINI_APP_URL`
for the bot and `--listen`/TLS termination for this server the same way any
other exposure decision is made (`SPEC-bundled-clients-and-exposure.md`),
per-environment, not baked into the code.

For a normal tenant deployment, `setup.sh` can provision this server as the
separate `mini-app` Compose service. It generates the operator secret, connects
the service to the tenant's private network, and publishes container port 8090
on the selected `MINI_APP_HOST` / `MINI_APP_PORT`. The public
`MINI_APP_URL` still belongs to an operator-managed reverse proxy, which must
terminate TLS. A proxy in another container cannot reach the Docker host's
`127.0.0.1`; choose a host-reachable bind address or connect that proxy to the
tenant's Compose network.

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

## ⚠ TLS

This server is a proxy — the browser never talks to the doors directly, so a
certificate is never presented to it. Its own client is plaintext-only: the
WebSocket proxy opens a bare socket and the REST proxy verifies with the default
context. **Against TLS doors, terminals fail even with a valid certificate.**
Run the doors published on loopback with TLS terminated in front, or see
`docs/TODO.md`.

## Checking it

Two checkers, both needing a real tenant and a browser:

```bash
python3 clients/web/visual-check.py --url http://127.0.0.1:8099
python3 clients/web/flow-check.py --console http://HOST:8098 --secret S \
    --container h-flock-<tenant>-tenant-1 --tenant <name> [--ssh user@host]
```

`visual-check` measures layout: overflow, layout shift, console errors, failed
requests. `flow-check` drives the console as an operator — hire an agent and
watch the terminals view, close a tab and confirm it stays closed, retire an
agent, send a message and reload the page.

⚠ **Every flow in `flow-check` is a defect someone hit in use.** The tests in
`tests/` are static: they assert files exist and that no token reaches browser
assets, and they passed while the terminals view ignored a hire and the chat
lost everything on refresh. **A reported bug becomes a failing flow first, and a
fix second** — so a red result on the day of a report is correct.

⚠ Neither proves it *looks* right. That still needs a person.
