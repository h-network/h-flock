# Browser office

A dependency-free browser client for one h-flock tenant. It shows the roster
and live presence, agent activity, mailbox replies, watchdog alerts, boards and
a human-operated terminal.

The small Python server is required even though the page is static. h-flock
sends no CORS headers, so a page served from another origin cannot call it.
Native browser `EventSource` also cannot attach the required Bearer header. This
server serves the page and proxies authenticated API and SSE requests on the
same origin; the token is never placed in browser storage or JavaScript.

## Run

Python 3 is the only dependency.

```bash
cd clients/web
API_TOKEN=<tenant-token> python3 server.py --api http://HOST:8080
```

Open <http://127.0.0.1:8090>. The server enrols an idempotent `web` API
participant on startup. Use `--client NAME`, `--listen ADDRESS`, or `--port N`
to change those defaults. It binds to loopback unless explicitly told
otherwise.

For fixtures, including every panel state in `SPEC.md` §4:

```bash
python3 server.py --demo
```

Demo mode needs no tenant or token and exposes a state toolbar. It is for visual
exercise, not evidence that a tenant works.

The browser persists the last cursor for mailbox, alert and per-agent activity
streams in `localStorage`. Browser SSE reconnects carry `Last-Event-ID` through
the proxy, and a reload starts each stream after its persisted cursor. A silent
mailbox remains open indefinitely and is not treated as an error.

The browser connects only to this server. HTTP and SSE use `/api`; the terminal
uses the same-origin `/session` WebSocket. The server attaches the token to both
upstreams, so it never enters page source, JavaScript or browser storage.

## Panel architecture

`app.js` is wiring only. Each independent panel lives under `ui/` and owns its
loading, empty, error, stale and disconnected presentation. Presence and boards
poll because they have no stream. Alerts, activity and messages catch up from a
persisted cursor and then use SSE with capped exponential reconnect backoff.
One failed panel keeps its last honest data and cannot take down another.

The alert DOM is capped at the newest 300 entries and updated one row at a time;
that bounds layout work under alert load. Activity and each message history are
capped at 100. Boards render every ticket inside independently scrolling,
collapsible agent rows, so a 200-ticket board remains navigable without hiding
work.

Every timestamp is relative in the layout and absolute on hover. `blocked` has
an icon, text and a heavy border rather than relying on red; `unknown` is
labelled and dashed rather than presented as ready. The terminal is read-only
until its explicit mode control is switched, and terminal bytes populate no
other panel.

## Documentation gaps found

Built using only `docs/API.md` and the build brief. These details were missing or
internally incomplete:

- `GET /agents` returns names, not the overview data. The console fans out to
  `GET /agents/{agent}` for VAB and presence, and joins `/board` for open work.
  At 40 agents this is 41 HTTP reads per presence refresh; it works with the
  frozen backend but is the largest avoidable client cost.
- `GET /agents/{agent}` has no open-ticket field even though the console needs
  one beside presence. The all-agent board supplies it without a new endpoint.
- The alerts section shows only the `stalled` record shape even though it names
  delivery and credential alerts too. Their fields are not documented, so the
  alert list renders only common fields and the optional stall age.
- The reference does not state that repeating `StartAgent` for an already
  enrolled API participant is idempotent. The build brief does, and the server
  relies on that property to make restarts safe.
- Every REST request requires an Authorization header, but the reference does
  not discuss browser SSE: `EventSource` has no API for setting that header.
  A same-origin authenticated proxy is therefore necessary for live browser
  feeds even apart from CORS.
- Cursor retention is described, but the reference does not state what happens
  when a saved cursor has aged out of the approximately 1000 retained entries.
  The client cannot distinguish that condition from an ordinary reconnect.
- SSE event examples are given, but heartbeat behavior and server disconnect
  behavior are unspecified. The client relies on standard `EventSource`
  reconnection and displays its connection state without declaring silence an
  error.
