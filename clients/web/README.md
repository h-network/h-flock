# Browser office

A dependency-free browser client for one h-flock tenant. It shows the roster
and live presence, agent activity, mailbox replies, watchdog alerts and boards.

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

The browser persists the last cursor for mailbox, alert and per-agent activity
streams in `localStorage`. Browser SSE reconnects carry `Last-Event-ID` through
the proxy, and a reload starts each stream after its persisted cursor. A silent
mailbox remains open indefinitely and is not treated as an error.

The UI never connects to port 8081. Answers come from the participant mailbox;
terminal rendering is a different feature.

## Documentation gaps found

Built using only `docs/API.md` and the build brief. These details were missing or
internally incomplete:

- `GET /agents/{agent}` says presence has only `working`, `idle`, or `unknown`,
  while the client requirements call for `blocked`. The reference does not show
  whether `blocked` is a presence state or a separate response field, nor its
  shape. The UI defensively treats a truthy top-level `blocked` field as blocked.
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
