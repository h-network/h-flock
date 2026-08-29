# h-flock Public API Reference

Documentation for external developers building web interfaces, mobile clients, desktop applications, or bots against an **h-flock** tenant.

---

## 1. Overview & Core Concepts

An **h-flock** tenant is a message bus for terminal agents and external applications. Every participant in a tenant is an **agent**, identified by a unique **name**.

- **Addresses:** An agent's name (e.g. `backend`, `frontend`, `telegram`) is its sole address. All communication happens by addressing messages to names. Local names can be addressed directly (e.g. `backend`), or qualified with tenant and pod (`acme:hq:backend`).
- **Applications as Participants:** External applications enrol as named participants on the bus with an `api` environment (`port_type: api`). Once enrolled, terminal agents can address replies to your app by name (e.g. `office send -a telegram "hello"`).
- **Layered Wire Frames (v4):** Messages travel across the bus as version 4 layered wire frames (`v: 4`). A frame encapsulates Layer 2 local forwarding addresses (`l2`), Layer 3 qualified fabric addresses (`l3`), lifecycle correlation headers (`stream_id`, `correlation_id`), a `ttl`/`hops` pair, and an application `payload`.
- ⚠ **v4 added two keys you will receive: `ttl` and `hops`.** A client that validates against a closed set of the eight v3 keys **will reject a v4 envelope**. `ttl` counts down from 16 and `hops` counts up, both set by the fabric; treat them as read-only and ignore them unless you are tracing a loop.
- **The wire encoding is not your concern.** v4 is a fixed **256-byte** ASCII header followed by an opaque JSON body, so the switch forwards without parsing the payload. API clients never see the wire form — you send and receive JSON.
- **Envelopes & Kinds:** The **kind** indicates what sort of message it is (e.g. `Message`, `AddTicket`, `StartAgent`).
- **Tag-Based Policy & Access Control:** Senders and recipients can declare `export` and `import` policy tags. Senders are filtered at the port before enqueuing; an unshared tag set results in an immediate, synchronous `422 Unprocessable Content` refusal.
- **Asynchronous Delivery:** `POST` operations return `202 Accepted` immediately upon successful queueing. Agents process envelopes asynchronously over seconds to minutes. A reply, if generated, is delivered to your app's inbox stream.
- **Pull-Based Task Boards:** Task boards are pulled by participants; adding a ticket writes to a board without interrupting or notifying the agent.

### The v4 Wire Frame Specification

Every envelope moving across the bus or read from `/messages` conforms to the version 4 frame schema:

```json
{
  "v": 4,
  "kind": "Message",
  "stream_id": "d03d60148843438cbafac93615646951",
  "correlation_id": "d3cec61c5c7049519920f433b325bf10",
  "ts": "2026-08-14T15:55:54.243Z",
  "l2": {
    "source": "telegram",
    "destination": "backend"
  },
  "ttl": 16,
  "hops": 0,
  "l3": {
    "source": "acme:hq:telegram",
    "destination": "acme:hq:backend"
  },
  "payload": {
    "text": "hello"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `v` | integer | Wire schema version. Always `4`. Anything else is rejected at the door — the fabric does not accept older frames. |
| `kind` | string | Message kind discriminator (e.g. `"Message"`, `"AddTicket"`, `"StartAgent"`, `"StopAgent"`). |
| `stream_id` | string | Unique 32-character lowercase hex identifier for this envelope across its entire lifecycle. |
| `correlation_id` | string | Unique 32-character lowercase hex identifier minted by the fabric for multi-turn conversation tracing. |
| `ts` | string | RFC 3339 / ISO 8601 UTC timestamp with millisecond precision and `Z` suffix (`%Y-%m-%dT%H:%M:%S.%fZ`). |
| `l2` | object | **Layer 2 Local Forwarding:** contains `source` (local agent name) and `destination` (local agent name or `"all"`). Used by the local switch. |
| `ttl` | integer *(v4)* | Forwards remaining. Starts at `16`, decremented by the switch at each forward; at `0` the envelope is dead-lettered instead of forwarded. Read-only. |
| `hops` | integer *(v4)* | Forwards taken, counting up from `0`. Read-only. |
| `l3` | object | **Layer 3 Qualified Addressing:** contains `source` (`pod:tenant:agent`) and `destination` (`pod:tenant:agent` or `pod:tenant:all`). |
| `payload` | object | Arbitrary JSON object holding the message content for the specified `kind`. |
| `cursor` | string *(mailbox stream only)* | Monotonically increasing Redis stream entry ID (e.g. `"1786231887036-0"`) used for pagination and catch-up resuming. |

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
- **Published Door:** once the door is reachable outside the container (`API_PUBLISH=1` at setup), a declared `as` additionally requires a per-client HMAC signature — see [Per-Client Signatures](#per-client-signatures-published-door-only). Loopback-only, nothing here changes.
- **Unauthorized Requests:** Omitting the token or providing an incorrect token returns `401 Unauthorized`:

```json
{
  "detail": "Unauthorized"
}
```

---

## 3. Quick Start (Three-Step Loop)

### Step 1: Enrol Your Application

Send a `StartAgent` envelope to `host` with `port_type: "api"` to register your app on the roster without spawning a terminal window:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "StartAgent",
    "payload": {
      "agent": "telegram",
      "port_type": "api"
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
      "v": 4,
      "kind": "Message",
      "stream_id": "edd534563cdd46209f0f63924c5e0497",
      "correlation_id": "4ba8e30ce8354109901d7b09c3a01bb4",
      "ts": "2026-08-08T23:31:26.623Z",
      "l2": {"source": "backend", "destination": "telegram"},
      "ttl": 16,
      "hops": 0,
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
data: {"v": 4, "kind": "Message", "stream_id": "71d1dec5203c434c91df2af82e693637", "correlation_id": "da93ce7c8ce84ba6a26e9f338a989ee5", "ts": "2026-08-08T23:31:38.290Z", "l2": {"source": "frontend", "destination": "telegram"}, "ttl": 16, "hops": 0, "l3": {"source": "acme:hq:frontend", "destination": "acme:hq:telegram"}, "payload": {"text": "hello from frontend"}, "cursor": "1786231898811-0"}

```

---

## 4a. Four things a client builder learns the hard way

Reported by the lanes that built the console against this document.

⚠ **An office overview takes three calls, not one.** `GET /agents` returns names
only. Presence, `blocked`, queue depths and `port_type` come from `GET /agents/{agent}`,
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
  "port_type": "api",
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

- **Destination Addressing:**
  - Local agent name: e.g. `backend`, `frontend`, `all`.
  - Qualified address: `pod:tenant:agent` (e.g. `acme:hq:backend`). Qualified addresses within the local tenant resolve to the local agent.
  - ⚠ **Non-Local Destinations:** Addresses naming a foreign pod or tenant (e.g. `otherpod:othertenant:backend`) are refused synchronously with `422 Unprocessable Content` (`"no route to non-local destination 'otherpod:othertenant:backend'"`). The current fabric routes intra-tenant traffic.
- **Request Body Fields:**
  - `text` (optional string): Text message shorthand (implies `kind: "Message"`).
  - `as` (optional string): Enrolled application client name to declare as `source`. Must name an enrolled `port_type: "api"` client.
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

**Example Attachment Envelope Body:**
```json
{
  "kind": "Attachment",
  "payload": {
    "filename": "diagram.png",
    "mime_type": "image/png",
    "content_base64": "iVBORw0KGgo...",
    "caption": "current topology"
  }
}
```

**Response (`202 Accepted`):**
```json
{
  "stream_id": "b2e227d8a2e2490691c5829df798ecba",
  "correlation_id": "52e29ac10d8f49f3bea2bdcbc72cc63a"
}
```

### Tag-Based Policy & Synchronous 422 Refusal

Communication between participants can be governed by export and import policy tags:

1. **Tag Model:** Participants declare `export` tags (what tag scopes they can emit) and `import` tags (what tag scopes they accept).
2. **Intersection Rule:** Sending from `source` to `destination` is permitted if `source.export ∩ destination.import` is non-empty.
3. **Permit When Absent:** If either the sender has no `export` tags defined or the destination has no `import` tags defined (the standard state for default agents), the send is **permitted**.
4. **Synchronous Refusal (`422 Unprocessable Content`):**
   - If both participants define tags and their intersection is empty, the send is refused synchronously **before the envelope is enqueued to egress or minted onto the bus**.
   - An HTTP 422 response guarantees that **nothing was sent or enqueued** (not that a message was sent and lost).
   - The bus logs a `send_refused` custody record.

**Policy Denial Error Response (`422 Unprocessable Content`):**
```json
{
  "detail": "policy denied 'telegram' -> 'backend': no shared export/import tag"
}
```

**Invalid Client Error Response (`422 Unprocessable Content`):**
```json
{
  "detail": "invalid 'as' client: must be an enrolled client with port_type 'api'"
}
```

**Non-Local Destination Error Response (`422 Unprocessable Content`):**
```json
{
  "detail": "no route to non-local destination 'corp:prod:backend'"
}
```

### Per-Client Signatures (published door only)

On a loopback-only door, `as` is a declaration checked against the roster —
the container is the trust boundary and nothing more is asked of it. Once the
door is published (`API_PUBLISH=1` at setup, surfaced to the process as
`API_PUBLISHED`), a caller with the shared bearer token is no longer
necessarily a colleague inside that boundary, so using `"as"` additionally
requires `"kid"` and `"sig"`:

```json
{
  "kind": "Message",
  "payload": {"text": "hello backend"},
  "as": "telegram",
  "kid": "telegram-2026-08",
  "sig": "3f9c...  (hex hmac-sha256)"
}
```

`sig` is `HMAC-SHA256(secret, canonical_json)`, where `secret` is the value
registered for `(as, kid)` via `StartAgent` (see above) and `canonical_json`
is the request body with the `sig` field itself removed, serialised as
`json.dumps(body, sort_keys=True, separators=(",", ":"))`. `kid` is part of
the signed body, so a captured signature cannot be replayed under a
different `kid`.

Requests without `"as"` (the default `"api"` source) are unaffected on both
loopback-only and published doors — this only closes the specific gap where a
caller declares itself to *be* a named client without proving it.

**Invalid Signature Error Response (`401 Unauthorized`, published only):**
```json
{
  "detail": "invalid or missing signature for 'as' client"
}
```

### CORS (published door only)

Loopback-only, no CORS headers are added at all. Published, cross-origin
browser requests are allowed only for origins listed in `API_CORS_ORIGINS`
(comma-separated) at setup — unset or empty means no origin is allowed, there
is no wildcard default once the door leaves the container.

---

### Agent & Application Lifecycle

Lifecycle commands are sent as envelopes addressed to the `host` agent: `POST /agents/host/envelopes`.

Lifecycle payloads have a fixed vocabulary. `StartAgent` accepts `agent`,
`port_type`, `cli`, `profile`, `provider`, `export`, `import`, `resume`, and —
for `port_type: "api"` only — `hmac_secret`, `kid`, and `revoke_kid` (see
below); `StopAgent`, `PauseAgent`, and `ResumeAgent` accept only `agent`. An
omitted optional key keeps its documented default, but any unknown key is
refused with HTTP 422 and named in the error. This makes misspellings loud
instead of silently selecting a default.

#### Enrol Application Client (`StartAgent` with `port_type: api`)

⚠ **Enrolling a name that already exists is safe.** It re-registers and changes
nothing else — no mailbox is cleared, no messages are lost. Clients are expected
to enrol on every start rather than track whether they have before.

Registers an external application client without creating a terminal window or starting a CLI process, optionally configuring policy tags:

```json
{
  "kind": "StartAgent",
  "payload": {
    "agent": "telegram",
    "port_type": "api",
    "export": ["frontend", "ops"],
    "import": ["frontend"]
  }
}
```

| Field | Type | Description |
|---|---|---|
| `agent` | string | Unique agent name segment (lowercase alphanumeric, hyphens allowed). |
| `port_type` | string | `"api"` for external applications; `"tmux"` for terminal agents. |
| `export` | array of strings | *(Optional)* Policy tags this agent is permitted to send to. |
| `import` | array of strings | *(Optional)* Policy tags this agent accepts incoming messages for. |
| `hmac_secret` | string | *(Optional, `port_type: "api"` only)* Client-generated secret, 16+ characters, paired with `kid`. Required only if this client will ever use `"as"` on a **published** door — see [Per-Client Signatures](#per-client-signatures-published-door-only) below. Ignored (has no effect) on a loopback-only door. |
| `kid` | string | *(Optional)* Key identifier for `hmac_secret`, segment-shaped (e.g. `telegram-2026-08`). Required together with `hmac_secret`. |
| `revoke_kid` | string | *(Optional)* Removes one previously-registered key by `kid`. Can be sent alongside a new `hmac_secret`/`kid` in the same request to rotate in one call. |

Enrolling with `hmac_secret`/`kid` is additive: a repeated `StartAgent` with a
new `kid` adds a key without removing an older one, so both validate during a
rotation's overlap window — remove the old one explicitly with `revoke_kid`
when the rotation is done. `StopAgent` removes every registered key for that
client.

#### Enrol Terminal Agent (`StartAgent` with `port_type: tmux`)

Enrols a new terminal agent, creating its workspace window and starting its CLI:

```json
{
  "kind": "StartAgent",
  "payload": {
    "agent": "networking",
    "cli": "claude",
    "port_type": "tmux"
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
    "description": "Add Cache-Control headers to static providers",
    "priority": "normal"
  }
}
```

---

### Agent Activity Feed

The activity feed streams real-time execution facts about what an agent is doing (e.g., executing commands, reading files, generating responses). It is available for any agent in the tenant roster (not only `port_type: "api"` clients).

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
2. **`EventSource` cannot set headers.** The SSE providers require
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
| `422 Unprocessable Content` | Refused or Invalid | Policy refusal (disjoint tags), non-local unrouted destination, invalid `"as"` identity, Attachment schema violation, or payload exceeding size limits | Inspect `detail` field; correct request payload or permissions; do not retry without changes |
| `5xx` | Server Error | Redis database or internal backend failure — not a fault in your request payload | **Retry with backoff.** The same request will succeed once the server/database recovers |

### Distinguishing 422 Unprocessable Content Causes

`422 Unprocessable Content` is returned synchronously by the API door for several distinct reasons. Callers distinguish the cause by inspecting the `detail` property of the JSON response:

| Error Cause | Response `detail` Pattern | Meaning & Resolution |
|---|---|---|
| **Policy Denial** | `"policy denied '<source>' -> '<destination>': no shared export/import tag"` | Senders and recipients have disjoint policy tags. **Nothing was sent or enqueued.** Verify and update `export` / `import` tags via `StartAgent`. |
| **Non-Local Route** | `"no route to non-local destination '<destination>'"` | Destination specifies a qualified pod/tenant outside this tenant. Intra-tenant local routing cannot reach foreign nodes without a gateway. |
| **Invalid Client Identity** | `"invalid 'as' client: must be an enrolled client with port_type 'api'"` | The declared `"as"` client is not enrolled in the tenant roster as an `api` participant. Enrol with `StartAgent` first. |
| **Malformed Address / Payload** | `"destination must be a qualified pod:tenant:agent address"` or `"payload must be an object"` | Request envelope structure does not conform to the v4 frame specification. |
| **Payload Too Large** | `"envelope payload exceeds maximum size limit of 1MB"` or `"decoded attachment exceeds maximum size limit of 10MB..."` | Envelope payload exceeded the 1MB default or 10MB Attachment decoded limit. |
| **Invalid Attachment** | `"invalid attachment filename..."` or `"invalid attachment mime_type..."` or `"invalid attachment content_base64..."` | Attachment payload violates closed schema or field-level validation rules. |

### Custody Records & Observability

When an envelope is posted to the door or delivered across the bus, the platform emits structured custody records. Join them across system logs by `stream_id`:

- **`send_refused`** *(pre-queue refusal)*: Emitted synchronously by the sender door/port when a send is rejected (e.g. policy denial, unrouted non-local destination, or validation failure). **No frame is minted and nothing is enqueued to egress.**
- **`sent`**: Emitted when the envelope is assembled into a v4 frame and enqueued to the sender's `egress` list.
- **`popped`**: Emitted by the switch when taking the frame off egress.
- **`forwarded`**: Emitted by the switch when delivering the frame to the recipient's `ingress` list.
- **`dead_lettered`**: Emitted if the switch or port fails to deliver or parse the frame.
- **`received`**: Emitted when the recipient's port dequeues the frame from `ingress`.
- **`opened`**: Emitted when the port's kind opener successfully completes processing.

**Request & Payload Size Limits:**
- **Maximum Envelope Payload:** Standard envelopes posted to `POST /agents/{agent}/envelopes` are limited to **1 MB (1,048,576 bytes)** of serialized JSON. `Attachment` envelopes are bounded by decoded file content up to **10 MiB (10,485,760 bytes)** (with `content_base64` bounded before decode at `4 * ceil(10,485,760 / 3) = 13,981,016` ASCII bytes). Requests exceeding these limits return `422 Unprocessable Content`.
- **Stream Query Bounds:** Pagination `limit` parameters on stream providers (`/messages`, `/activity`, `/alerts`) are bounded between `1` and `1000` entries (default `100`).

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
    "payload": {"agent": "mybot", "port_type": "api"}
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
