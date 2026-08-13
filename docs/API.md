# h-flock Public API Reference

Documentation for external developers building web interfaces, mobile clients, desktop applications, or bots against an **h-flock** tenant.

---

## 1. Overview & Core Concepts

An **h-flock** tenant is a message bus for terminal agents and external applications. Every participant in a tenant is an **agent**, identified by a unique **name**.

- **Addresses:** An agent's name (e.g. `backend`, `frontend`, `telegram`) is its sole address. All communication happens by addressing messages to names.
- **Applications as Participants:** External applications enrol as named participants on the bus with an `api` environment (`vab: api`). Once enrolled, terminal agents can address replies to your app by name (e.g. `office send -a telegram hello`).
- **Envelopes & Kinds:** Messages travel inside structured **envelopes**. The **kind** indicates what sort of message it is (e.g. `Message`, `AddTicket`, `StartAgent`).
- **Asynchronous Delivery:** `POST` operations return `202 Accepted` immediately. Agents process envelopes asynchronously over seconds to minutes. A reply, if generated, is delivered to your app's inbox stream.
- **Pull-Based Task Boards:** Task boards are pulled by participants; adding a ticket writes to a board without interrupting or notifying the agent.

> **A reply may never come — build for silence.**
>
> `202 Accepted` means the envelope was accepted for routing. It does not mean an
> agent received it, read it, or agreed to answer. An agent may be busy for
> minutes, may be stopped, or may simply decide no reply is warranted.
>
> This is the single most important thing to design around. Never block a user
> interaction on a reply arriving, never treat a missing reply as an error, and
> never retry a message because nothing came back — the first one was very likely
> delivered, and a retry produces two.
>
> A message you send is best thought of as a message to a colleague, not a
> function call.

---

## 2. Authentication & Transport

An h-flock tenant exposes two separate HTTP/WebSocket services on distinct ports:

| Service | Port | Protocol | Purpose |
|---|---|---|---|
| **REST API** | `:8080` | HTTP | Agent discovery, sending envelopes, mailbox polling/streaming, and task boards |
| **Session Service** | `:8081` | WebSocket | Live terminal window output streaming and raw keystroke input |

### Bearer Token Authentication

Every request to the REST API and Session Service requires a Bearer token in the `Authorization` header:

```http
Authorization: Bearer <API_TOKEN>
```

- **Shared Token Security:** The API token is shared per tenant. Declared application names (e.g. `as: "telegram"`) are validated against the enrolled roster.
- **Unauthorized Requests:** Omitting the token or providing an incorrect token returns `401 Unauthorized`:

```json
{
  "detail": "Unauthorized"
}
```

---

## 3. Quick Start (Three-Step Loop)

### Step 1: Enrol Your Application

Send a `StartAgent` envelope to `host` with `vab: "api"` to register your app on the roster without spawning a terminal window:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "StartAgent",
    "payload": {
      "agent": "telegram",
      "vab": "api"
    }
  }' \
  http://HOST:8080/agents/host/envelopes
```

**Response (`202 Accepted`):**
```json
{
  "stream_id": "2c58d49908cc42bfa48c3b8a5d503e9c",
  "correlation_id": "4765b9d9e97e482a9730aa8b09be920d"
}
```

### Step 2: Send a Message to an Agent

Send a message to an agent (e.g. `backend`), specifying your enrolled app name in the `"as"` parameter so replies route back to you:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "hello from telegram",
    "as": "telegram"
  }' \
  http://HOST:8080/agents/backend/envelopes
```

**Response (`202 Accepted`):**
```json
{
  "stream_id": "b2e227d8a2e2490691c5829df798ecba",
  "correlation_id": "52e29ac10d8f49f3bea2bdcbc72cc63a"
}
```

### Step 3: Retrieve Replies

Poll your application's inbox mailbox to retrieve incoming replies:

```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  http://HOST:8080/agents/telegram/messages
```

**Response (`200 OK`):**
```json
{
  "agent": "telegram",
  "messages": [
    {
      "v": 2,
      "kind": "Message",
      "stream_id": "edd534563cdd46209f0f63924c5e0497",
      "correlation_id": "4ba8e30ce8354109901d7b09c3a01bb4",
      "ts": "2026-08-08T23:31:26.623Z",
      "l2": {"source": "backend", "destination": "telegram"},
      "l3": {"source": "acme:hq:backend", "destination": "acme:hq:telegram"},
      "payload": {
        "text": "hello from backend"
      },
      "cursor": "1786231887036-0"
    }
  ],
  "next_cursor": "1786231887036-0"
}
```

---

## 4. Receiving Messages & Mailboxes

### Mailbox Architecture

Every enrolled `api` application has a dedicated inbox **mailbox**.

- **Retention Limit:** Mailboxes retain approximately the last 1000 messages.
- **Cursors:** Each message in the mailbox includes a unique string `cursor` (e.g. `"1786231887036-0"`). Cursors are monotonically increasing.
- **Resuming After Restart:** Store the `cursor` of the last processed message. When restarting or reconnecting, pass `after=<cursor>` to resume reading without missing or duplicating messages.

### Catch-Up Polling: `GET /agents/{client}/messages`

Retrieve messages from your inbox stream starting after a specified cursor.

- **Query Parameters:**
  - `after` (optional): Cursor ID to read after.
  - `limit` (optional): Maximum number of messages to return (default: `100`, max: `1000`).

**Example Request:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  "http://HOST:8080/agents/telegram/messages?after=1786231887036-0&limit=50"
```

**Example Response when no new messages exist (`200 OK`):**
```json
{
  "agent": "telegram",
  "messages": [],
  "next_cursor": "1786231887036-0"
}
```

### Live SSE Stream: `GET /agents/{client}/messages/stream`

Open a persistent Server-Sent Events (SSE) stream to receive messages in real time.

- **Query Parameters / Headers:**
  - `after` (optional query parameter): Cursor ID to resume from.
  - `Last-Event-ID` (optional HTTP header): the standard SSE resume header.

⚠ **`after` wins if both are given.** Browser `EventSource` cannot set headers,
so a browser client resumes with `?after=`; `Last-Event-ID` is sent automatically
by `EventSource` on its own reconnect, which is why both exist.

**Example Request:**
```bash
curl -N -H "Authorization: Bearer $API_TOKEN" \
  "http://HOST:8080/agents/telegram/messages/stream?after=1786231887036-0"
```

**Response Headers (`200 OK`):**
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE Event Output Stream:**
```text
id: 1786231898811-0
event: message
data: {"v": 2, "kind": "Message", "stream_id": "71d1dec5203c434c91df2af82e693637", "correlation_id": "da93ce7c8ce84ba6a26e9f338a989ee5", "ts": "2026-08-08T23:31:38.290Z", "l2": {"source": "frontend", "destination": "telegram"}, "l3": {"source": "acme:hq:frontend", "destination": "acme:hq:telegram"}, "payload": {"text": "hello from frontend"}, "cursor": "1786231898811-0"}

```

---

## 4a. Four things a client builder learns the hard way

Reported by the lanes that built the console against this document.

⚠ **An office overview takes three calls, not one.** `GET /agents` returns names
only. Presence, `blocked`, queue depths and `vab` come from `GET /agents/{agent}`,
one call per agent, and the boards from `GET /board`. There is no combined view,
deliberately — but budget for it rather than discovering it mid-render.

⚠ **`GET /agents/{agent}` does not include the agent's open ticket.** The
`office status` CLI shows one; the api does not. Read `GET /agents/{agent}/board`
and take the head of `doing`.

⚠ **Cursor expiry is unspecified.** Mailboxes and activity are Redis Streams
trimmed by `MAXLEN`, so a cursor older than the retained window will not error —
it resumes from what survives. A client that has been away longer than the
retention silently misses the difference. Treat a large gap as "I have been away",
not as an error.

⚠ **SSE heartbeats are not guaranteed.** Do not use silence to infer a dead
connection: an idle office is silent and a dead socket is silent. Track the
transport, not the message rate.

## 5. REST API Reference

### Liveness Check

#### `GET /health`
Returns `200 OK` if the tenant API service is running.

**Response (`200 OK`):**
```json
{
  "status": "ok"
}
```

---

### Roster & Agent Discovery

#### `GET /agents`
Returns the list of all currently enrolled agents in the tenant roster.

**Response (`200 OK`):**
```json
{
  "agents": [
    "backend",
    "api",
    "frontend",
    "systems",
    "host",
    "telegram"
  ]
}
```

#### `GET /agents/{agent}`
Returns queue depths and presence for a specific agent.

**`state` is one of four:**

| state | means | what to do |
|---|---|---|
| `working` | producing model activity right now | show a busy indicator |
| `idle` | ready, nothing in flight | send |
| `unknown` | **nothing can be said** — the agent runs no CLI we can read, or has not spoken yet | it may never reply; do not present it as ready |
| `blocked` | **a message was delivered and not consumed** | do not send more; tell the user |

⚠ **`unknown` is not `idle`.** Some agents write nothing we can read. Rendering
`unknown` as "ready" will have your users waiting on a reply that cannot come.

⚠ **`blocked` is the one to act on.** It means a delivery was judged unconsumed —
a login prompt, an unattended dialog, a stopped process. More messages will pile
up unread. It clears by itself when something is consumed again.

⚠ **A brand-new agent will never report `blocked`, however stuck it is.** A
delivery is judged only for an agent that has produced activity before; one that
has never spoken is `unknown` and its delivery is not judged at all. **Do not
wait for `blocked` to decide a new agent is unreachable** — it cannot arrive.

⚠ **There is no retry.** A delivery judged unconsumed is not resent. The
framework cannot tell text that never submitted from text sitting in a wedged
CLI, so it surfaces the state rather than risk running an instruction twice. If
you need a delivery guarantee, build it on your side.

**Response (`200 OK`):**
```json
{
  "agent": "sme-2",
  "vab": "api",
  "depths": {
    "ingress": 0,
    "egress": 0,
    "dead": 0
  },
  "presence": {
    "state": "working",
    "since": "2026-08-09T13:00:00.000Z",
    "last_activity": "2026-08-09T13:15:00.000Z"
  }
}
```

**Error Response (`404 Not Found` for unenrolled or invalid agent name):**
```json
{
  "detail": "unknown agent"
}
```
*Note on 404 vs 200:* An enrolled agent holding no tasks, mailbox messages, or presence feed returns `200 OK` with empty structures; `404 Not Found` indicates that no agent by that name is enrolled in the tenant roster (or the segment name is invalid).

---

### Sending Envelopes

#### `POST /agents/{agent}/envelopes`
Post an envelope to a specific agent, or to `"all"` for broadcast messages.

- **Request Body Fields:**
  - `text` (optional string): Text message shorthand (implies `kind: "Message"`).
  - `as` (optional string): Enrolled application client name to declare as `producer`. Must name an enrolled `vab: "api"` client.
  - `kind` (optional string): Envelope kind (e.g. `"Message"`, `"AddTicket"`, `"StartAgent"`, `"StopAgent"`).
  - `payload` (optional object): Payload dictionary associated with the envelope kind.

**Example Shorthand Message:**
```json
{
  "text": "hello backend",
  "as": "telegram"
}
```

**Example Full Envelope Body:**
```json
{
  "kind": "Message",
  "payload": {
    "text": "hello backend"
  },
  "as": "telegram"
}
```

**Response (`202 Accepted`):**
```json
{
  "stream_id": "b2e227d8a2e2490691c5829df798ecba",
  "correlation_id": "52e29ac10d8f49f3bea2bdcbc72cc63a"
}
```

**Error Response (`422 Unprocessable Content` if `as` client is invalid or not enrolled as `vab: api`):**
```json
{
  "detail": "invalid 'as' client: must be an enrolled client with vab 'api'"
}
```

---

### Agent & Application Lifecycle

Lifecycle commands are sent as envelopes addressed to the `host` agent: `POST /agents/host/envelopes`.

Lifecycle payloads have a fixed vocabulary. `StartAgent` accepts `agent`,
`vab`, `cli`, `profile`, and `endpoint`; `StopAgent`, `PauseAgent`, and
`ResumeAgent` accept only `agent`. An omitted optional key keeps its documented
default, but any unknown key is refused with HTTP 422 and named in the error.
This makes misspellings loud instead of silently selecting a default.

#### Enrol Application Client (`StartAgent` with `vab: api`)

⚠ **Enrolling a name that already exists is safe.** It re-registers and changes
nothing else — no mailbox is cleared, no messages are lost. Clients are expected
to enrol on every start rather than track whether they have before.

Registers an external application client without creating a terminal window or starting a CLI process:

```json
{
  "kind": "StartAgent",
  "payload": {
    "agent": "telegram",
    "vab": "api"
  }
}
```

#### Enrol Terminal Agent (`StartAgent` with `vab: tmux`)

Enrols a new terminal agent, creating its workspace window and starting its CLI:

```json
{
  "kind": "StartAgent",
  "payload": {
    "agent": "networking",
    "cli": "claude",
    "vab": "tmux"
  }
}
```

#### Retire Application or Agent (`StopAgent`)

Removes an application or agent from the roster, cleaning up its mailbox and state:

```json
{
  "kind": "StopAgent",
  "payload": {
    "agent": "telegram"
  }
}
```

---

### Task Boards

Task boards consist of four columns: `todo`, `doing`, `hold`, and `done`.

#### `GET /agents/{agent}/board`

⚠ **A board entry is usually an object, and may be a bare string.** Older tenants
hold entries written before tickets had a shape. Handle both: if it is not an
object, treat it as a title with no other fields. Entries the server cannot parse
are skipped rather than failing the response, so a board may be shorter than the
agent believes.
Returns the task board for a specific agent.

**Response (`200 OK`):**
```json
{
  "agent": "backend",
  "todo": [
    {
      "v": 1,
      "id": "a1b2c3d4",
      "title": "Review authentication pipeline",
      "description": "Verify Bearer token middleware on all routes",
      "created_by": "backend",
      "status": "todo",
      "created_ts": "2026-08-08T22:00:00Z",
      "priority": "high"
    }
  ],
  "doing": [],
  "hold": [],
  "done": []
}
```

#### `GET /board`
Returns task boards for all enrolled agents across the tenant in a single round-trip.

**Response (`200 OK`):**
```json
{
  "agents": [
    {
      "agent": "backend",
      "todo": [],
      "doing": [],
      "hold": [],
      "done": []
    },
    {
      "agent": "frontend",
      "todo": [],
      "doing": [],
      "hold": [],
      "done": []
    }
  ]
}
```

#### Add a Task (`POST /agents/{agent}/envelopes` with `AddTicket`)

Adds a ticket to an agent's board without interrupting or notifying the agent:

```json
{
  "kind": "AddTicket",
  "payload": {
    "title": "Implement caching header",
    "description": "Add Cache-Control headers to static endpoints",
    "priority": "normal"
  }
}
```

---

### Agent Activity Feed

The activity feed streams real-time execution facts about what an agent is doing (e.g., executing commands, reading files, generating responses). It is available for any agent in the tenant roster (not only `vab: "api"` clients).

- **Kinds Vocabulary (`kind`):**
  - `input`: User or incoming prompt input received.
  - `output`: Agent output generated.
  - `tool`: CLI tool invoked (includes `tool` field, e.g. `"tool": "Bash"`).
- **Privacy & Safety Non-Leakage Invariants:** Tool arguments, file paths, shell command lines, and message content are **deliberately absent** from the activity feed.
- **Absence of Activity:** Absence of activity is not an error. Agents with no activity entries or `agy` CLI agents (which keep no session append log) return `200 OK` with an empty activity list `{"agent": agent, "activity": [], "next_cursor": after}`.

**`kind` is one of exactly three**, and the set will not grow without notice:

| kind | means | `tool` field |
|---|---|---|
| `input` | the agent received something and began a turn | absent |
| `output` | the agent produced a response | absent |
| `tool` | the agent called a tool | **present** — the tool's name |

⚠ **`tool` appears only on `kind: "tool"`.** Do not read it on the others.

⚠ **Tool *names* only — never arguments, paths or content.** There is no field
they could occupy. If you need to show a user what an agent is doing, the name is
what you have: `Bash`, `Read`, `Edit`.

#### Catch-Up Polling: `GET /agents/{agent}/activity`

Retrieve activity feed events for an agent starting after a specified cursor.

- **Query Parameters:**
  - `after` (optional): Cursor ID to read after.
  - `limit` (optional): Maximum number of entries to return (default: `100`, max: `1000`).

**Example Request:**
```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  "http://HOST:8080/agents/sme-2/activity?limit=50"
```

**Example Response (`200 OK`):**
```json
{
  "agent": "sme-2",
  "activity": [
    {
      "v": 1,
      "agent": "sme-2",
      "ts": "2026-08-09T12:00:00.000Z",
      "kind": "tool",
      "tool": "Bash",
      "cursor": "1786231900000-0"
    }
  ],
  "next_cursor": "1786231900000-0"
}
```

#### Live SSE Stream: `GET /agents/{agent}/activity/stream`

Opens a real-time Server-Sent Events stream of activity events for an agent.

- **Query Parameter:** `after` (optional)
- **Header:** `Last-Event-ID` (optional)

**Example SSE Event Stream Output:**
```text
id: 1786231900000-0
event: activity
data: {"v": 1, "agent": "sme-2", "ts": "2026-08-09T12:00:00.000Z", "kind": "tool", "tool": "Bash", "cursor": "1786231900000-0"}

```

---

### Watchdog Alerts Feed

Tenant-level alerts produced by `flock.watchdog`: an agent that took work and has since produced neither model activity nor terminal output, a delivery that was not consumed, or a credential nearing expiry.

**Alerts state facts and do not diagnose.** There is no "wedged" or "stuck" — an alert reports what was observed and what could not be checked, and leaves the conclusion to you.

#### `GET /alerts`

Returns stored watchdog alert events across the tenant (`?after=<cursor>&limit=100`).

**Response (`200 OK`):**
```json
{
  "alerts": [
    {
      "cursor": "1723150000000-0",
      "v": 1,
      "ts": "2026-08-09T15:00:00.000Z",
      "kind": "stalled",
      "agent": "sme-2",
      "ticket": "review the auth change",
      "doing_age_s": 840,
      "no_activity_s": 540,
      "no_output_s": 420,
      "unchecked": []
    }
  ],
  "next_cursor": "1723150000000-0"
}
```

#### `GET /alerts/stream`

Live Server-Sent Events (SSE) stream of watchdog alert events across the tenant (`?after=<cursor>`).

**Example SSE Event Stream Output:**
```text
id: 1723150000000-0
event: alert
data: {"v": 1, "ts": "2026-08-09T15:00:00.000Z", "kind": "stalled", "agent": "sme-2", "ticket": "review the auth change", "doing_age_s": 840, "no_activity_s": 540, "no_output_s": 420, "unchecked": [], "cursor": "1723150000000-0"}

```

---

### Browser clients need a small server of their own

⚠ **A page cannot talk to a tenant directly, for two reasons**, and both bite
immediately:

1. **No CORS headers.** A browser refuses a cross-origin request to the api, so a
   page served from anywhere else is blocked before it starts.
2. **`EventSource` cannot set headers.** The SSE endpoints require
   `Authorization: Bearer …`, and the browser's SSE client has no way to send
   one. There is no workaround in the browser.

**So serve your page and proxy the api from the same origin.** A few dozen lines
is enough — no framework — and it has a second benefit worth having anyway: the
**token stays server-side** instead of shipping to every browser that loads the
page.

`clients/web/` in the h-flock repository is a working example of exactly this
shape, in the standard library.

## 6. Terminal Session WebSocket Door (`:8081`)

**The two doors split by who consumes them.** The REST API is for your code:
deterministic, structured, data-driven. The session socket is for the **person
using your app**: a live terminal to read and type into. Anything your program
needs to *act on* comes from the REST API; the session socket is what you render
to a human.

Two things it is genuinely for: showing someone an agent working, and letting
them complete an interactive login when an agent's credential expires — a
device-code flow is terminal output one way and keystrokes the other, so it works
end to end through this socket with no shell access to the host.

⚠ **Never derive data from it.** Do not parse the stream for an agent's answer,
its status, or whether it finished. Terminal output is a rendering, it changes
between CLI versions without notice, and there is no contract on its shape.

Port `:8081` provides WebSocket terminal access for rendering live terminal windows in a user interface.

- **URL:** `ws://HOST:8081/session` or `ws://HOST:8081/session?token=<API_TOKEN>`
- **Authentication:**
  - **Browser JavaScript Clients:** browsers cannot set an `Authorization`
    header on a `WebSocket`, so query parameter authentication
    `ws://HOST:8081/session?token=<API_TOKEN>` is supported. ⚠ **Read the
    security cost below before using it.**
  - **Non-Browser / Standalone Clients:** may pass either an
    `Authorization: Bearer <API_TOKEN>` header or `?token=<API_TOKEN>`.
- **⚠ The cost of a token in a URL:**
  - query parameters land in browser history, `Referer` headers, network
    intermediaries and web server logs — and this token grants execution in any
    agent's window through the `Command` kind
  - ⚠ **the token DOES currently reach the tenant's stdout.** The door runs
    `access_log=False`, which silences uvicorn's *access* logger — but the
    WebSocket handshake line is emitted by a different one
    (`websockets_impl.py`: `'%s - "WebSocket %s" [accepted]'` with the query
    string included), and it was measured on a running tenant. **Treat any
    tenant log as containing the token if a browser has connected this way.**
    Being fixed by minting a short-lived ticket instead — see `docs/TODO.md`
  - **recommended instead:** a server-side proxy, as `clients/web/server.py`
    does. The token stays on the server and never reaches a URL
- **Wire Format & Encoding:**
  - **Output Events (`server -> client`):** `{"agent": "<name>", "data": "<text>"}` where `data` is UTF-8 string content containing ANSI control sequences (e.g. `\x1b[2J\x1b[H` screen repaint snapshots or live stdout).
  - **Keystroke Events (`client -> server`):** `{"agent": "<name>", "data": "<keystrokes>"}` where `data` is raw UTF-8 string keystroke input. The server encodes this string to UTF-8 bytes and forwards it to tmux via `send-keys -H`.
- **WebSocket Close Codes:**
  - `1000 Normal Closure`: Socket closed normally.
  - `4401 Unauthorized`: Token missing or invalid.
  - `1011 Internal Error`: Control stream or internal session failure.
- **Important Note for Application Developers:** Terminal streaming is strictly for rendering terminal UI panes. Applications **must not scrape terminal text** to extract answers or data. All structured application communication must use the REST API (`:8080`) and inbox mailboxes.

---

## 7. Error Codes & Retries

| Status Code | Meaning | Cause | Action |
|---|---|---|---|
| `200 OK` | Success | Request succeeded | Process body |
| `202 Accepted` | Accepted | Envelope accepted for asynchronous routing | Poll/stream mailbox for reply |
| `401 Unauthorized` | Unauthorized | Missing or invalid Bearer token | Check `Authorization: Bearer <TOKEN>` header |
| `404 Not Found` | Not Found | Unknown route, invalid agent segment name, or reading `/messages` for a non-`api` agent | Verify agent name and roster enrolment |
| `422 Unprocessable Content` | Validation Error | Invalid `"as"` client name (not enrolled or `vab != "api"`), payload exceeding 1MB limit, or malformed request payload | Correct request payload; do not retry identical request |
| `5xx` | Server Error | Redis database or internal backend failure — not a fault in your request payload | **Retry with backoff.** The same request will succeed once the server/database recovers |

**Request & Payload Size Limits:**
- **Maximum Envelope Payload:** Envelopes posted to `POST /agents/{agent}/envelopes` are limited to **1 MB (1,048,576 bytes)**. Requests exceeding this limit return `422 Unprocessable Content`.
- **Stream Query Bounds:** Pagination `limit` parameters on stream endpoints (`/messages`, `/activity`, `/alerts`) are bounded between `1` and `1000` entries (default `100`).

**Streaming & Socket Error Handling:**
- **SSE Streams (Mid-Flight):** Because HTTP headers (`200 OK`) are sent when an SSE connection opens, a mid-flight infrastructure error cannot alter the HTTP status code. Mid-flight failures emit an SSE `event: error` frame containing `{"error": "<reason>"}` before closing the stream.
- **WebSocket Door:** Malformed JSON input or invalid client frames emit a JSON error frame `{"error": "<reason>"}` back over the socket. The WebSocket connection remains active for subsequent valid messages.

**No reply is not an error.** There is no status code for it, because nothing
failed. If you have sent a message and your mailbox stays empty, the envelope was
still accepted and very probably delivered — the agent has not answered *yet*, or
will not. Surface it in your interface as waiting, not as a failure, and do not
resend.

**What is worth retrying:** `5xx` and connection failures, with backoff. `401`,
`404` and `422` are all deterministic — the same request will fail identically,
so fix it rather than repeat it.

---

## 8. Complete Worked Examples

### Python Walkthrough (`urllib.request`)

```python
import json
import time
import urllib.request

HOST = "http://localhost:8080"
TOKEN = "<YOUR_API_TOKEN>"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

def request(method, path, data=None):
    url = f"{HOST}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode())

# 1. Enrol application client
status, body = request("POST", "/agents/host/envelopes", {
    "kind": "StartAgent",
    "payload": {"agent": "mybot", "vab": "api"}
})
print("Enrolled mybot:", status, body)

# 2. Send message to backend as mybot
status, body = request("POST", "/agents/backend/envelopes", {
    "text": "Hello Backend, please check the status",
    "as": "mybot"
})
print("Sent message:", status, body)

# 3. Poll mailbox for replies
cursor = None
for _ in range(5):
    path = f"/agents/mybot/messages?after={cursor}" if cursor else "/agents/mybot/messages"
    status, body = request("GET", path)
    messages = body.get("messages", [])
    if messages:
        for msg in messages:
            print("Received reply from", msg["l2"]["source"], ":", msg["payload"])
            cursor = msg["cursor"]
        break
    time.sleep(1)

# 4. Clean up / retire application
status, body = request("POST", "/agents/host/envelopes", {
    "kind": "StopAgent",
    "payload": {"agent": "mybot"}
})
print("Retired mybot:", status, body)
```
