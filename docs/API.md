# h-flock Public API Reference

Documentation for external developers building web interfaces, mobile clients, desktop applications, or bots against an **h-flock** tenant.

---

## 1. Overview & Core Concepts

An **h-flock** tenant is a message bus for terminal agents and external applications. Every participant in a tenant is an **agent**, identified by a unique **name**.

- **Addresses:** An agent's name (e.g. `alice`, `bob`, `telegram`) is its sole address. All communication happens by addressing messages to names.
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

Send a message to an agent (e.g. `alice`), specifying your enrolled app name in the `"as"` parameter so replies route back to you:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "hello from telegram",
    "as": "telegram"
  }' \
  http://HOST:8080/agents/alice/envelopes
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
      "v": 1,
      "kind": "Message",
      "stream_id": "edd534563cdd46209f0f63924c5e0497",
      "correlation_id": "4ba8e30ce8354109901d7b09c3a01bb4",
      "ts": "2026-08-08T23:31:26.623Z",
      "producer": "alice",
      "recipient": "telegram",
      "payload": {
        "text": "hello from alice"
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
  - `Last-Event-ID` (optional HTTP header): Alternative standard SSE resume header.

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
data: {"v": 1, "kind": "Message", "stream_id": "71d1dec5203c434c91df2af82e693637", "correlation_id": "da93ce7c8ce84ba6a26e9f338a989ee5", "ts": "2026-08-08T23:31:38.290Z", "producer": "bob", "recipient": "telegram", "payload": {"text": "hello from bob"}, "cursor": "1786231898811-0"}

```

---

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
    "alice",
    "api",
    "bob",
    "carol",
    "host",
    "telegram"
  ]
}
```

#### `GET /agents/{agent}`
Returns queue depths for a specific agent's ingress, egress, and dead-letter queues.

**Response (`200 OK`):**
```json
{
  "agent": "alice",
  "depths": {
    "ingress": 0,
    "egress": 0,
    "dead": 0
  }
}
```

**Error Response (`404 Not Found` for invalid agent segment name):**
```json
{
  "detail": "invalid agent"
}
```

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
  "text": "hello alice",
  "as": "telegram"
}
```

**Example Full Envelope Body:**
```json
{
  "kind": "Message",
  "payload": {
    "text": "hello alice"
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

#### Enrol Application Client (`StartAgent` with `vab: api`)

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
    "agent": "dave",
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
Returns the task board for a specific agent.

**Response (`200 OK`):**
```json
{
  "agent": "alice",
  "todo": [
    {
      "v": 1,
      "id": "a1b2c3d4",
      "title": "Review authentication pipeline",
      "description": "Verify Bearer token middleware on all routes",
      "created_by": "architect",
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
      "agent": "alice",
      "todo": [],
      "doing": [],
      "hold": [],
      "done": []
    },
    {
      "agent": "bob",
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

## 6. Terminal Session WebSocket Door (`:8081`)

Port `:8081` provides WebSocket terminal access for rendering live terminal windows in a user interface.

- **URL:** `ws://HOST:8081/session`
- **Purpose:** Streaming raw terminal output (`%output`) and sending keystroke input (`send-keys`).
- **Important Note for Application Developers:** Terminal streaming is strictly for rendering terminal UI panes. Applications **must not scrape terminal text** to extract answers or data. All structured application communication must use the REST API (`:8080`) and inbox mailboxes.

---

## 7. Error Codes & Retries

| Status Code | Meaning | Cause | Action |
|---|---|---|---|
| `200 OK` | Success | Request succeeded | Process body |
| `202 Accepted` | Accepted | Envelope accepted for asynchronous routing | Poll/stream mailbox for reply |
| `401 Unauthorized` | Unauthorized | Missing or invalid Bearer token | Check `Authorization: Bearer <TOKEN>` header |
| `404 Not Found` | Not Found | Unknown route, invalid agent segment name, or reading `/messages` for a non-`api` agent | Verify agent name and roster enrolment |
| `422 Unprocessable Content` | Validation Error | Invalid `"as"` client name (not enrolled or `vab != "api"`), or malformed payload | Correct request payload |

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
TOKEN = "7af3ad5eb2cac57e9ca97a953908ef09"
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

# 2. Send message to alice as mybot
status, body = request("POST", "/agents/alice/envelopes", {
    "text": "Hello Alice, please check the status",
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
            print("Received reply from", msg["producer"], ":", msg["payload"])
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
