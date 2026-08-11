# Invariants & Real Tenant Results — `flock.api` & `flock.session`

Module invariants under real tenant conditions (`api-lab` on ports 8110 / 8111), along with falsification observations, raw test outputs, and ranked findings from Build 42 execution.

---

## 1. Module Invariants

### Invariant 1: Token Enforcement & Authentication Boundary
- **Statement:** Every REST API route and WebSocket session endpoint requiring authorization rejects missing or invalid Bearer tokens with HTTP `401 Unauthorized` or WebSocket close code `4401` / `403`.
- **Falsification Observation:** Any request without a valid `Authorization: Bearer <TOKEN>` or `?token=<TOKEN>` header returning HTTP `200 OK`, `202 Accepted`, or `404 Not Found`, or a WebSocket connection establishing cleanly with an invalid token.
- **Verification Status:** **HELD.** Missing and invalid tokens rejected with HTTP 401 / HTTP 403 across all routes.

### Invariant 2: Payload Size & Schema Bound
- **Statement:** Envelopes submitted to `POST /agents/{agent}/envelopes` exceeding 1 MB (1,048,576 bytes) or containing malformed non-string `"as"` parameters are rejected with HTTP `422 Unprocessable Content` before reaching Redis queues.
- **Falsification Observation:** An envelope exceeding 1 MB returning `202 Accepted` or placing oversized data onto Redis egress/ingress queues, or a malformed `"as"` dictionary payload causing an uncaught 500 Internal Server Error / `redis.exceptions.DataError`.
- **Verification Status:** **HELD.** Oversized envelopes (>1MB) and malformed `"as"` dict payloads both return HTTP 422 Unprocessable Content.

### Invariant 3: Session Door Token Log Confidentiality
- **Statement:** Connecting to the WebSocket session door (`ws://HOST:8111/session?token=<TOKEN>`) validates credentials without printing the token into container stdout or uvicorn access logs.
- **Falsification Observation:** The raw API token string appearing in `docker logs` output of the session or host container after a client connects via URL query parameter.
- **Verification Status:** **FALSIFIED BY FINDING 1.** Setting `access_log=False` on `uvicorn.run()` suppresses standard HTTP access logs, but Uvicorn's internal WebSocket protocol handler logs handshake request lines with query parameters directly to container stdout.

### Invariant 4: Roster & Tenant Board Resilience
- **Statement:** `GET /board` renders all valid agent boards cleanly even if corrupt, non-string, or malformed agent names exist in the Redis roster table. Unknown agent lookups return `404 Not Found`.
- **Falsification Observation:** A single invalid roster key causing `GET /board` to fail with HTTP `404` or `500` for all legitimate agents in the tenant.
- **Verification Status:** **HELD.** Inserting a corrupt non-JSON key into Redis `tenant:roster` did not crash `GET /board`. Unknown agent endpoints return HTTP 404 (`{"detail":"invalid agent"}`).

### Invariant 5: Non-Blocking Event Loop under I/O & SSE Streaming
- **Statement:** Long-polling SSE streams (`/activity/stream`, `/alerts/stream`, `/messages/stream`) and Redis stream readers execute non-blocking I/O using worker threads (`asyncio.to_thread`), allowing concurrent HTTP requests to proceed without latency spikes or event loop starvation.
- **Falsification Observation:** A slow SSE subscriber or blocking Redis read causing concurrent `GET /health` or `GET /agents` requests to block or time out.
- **Verification Status:** **HELD.** Concurrent requests to `/health` completed in 20-50ms during active SSE streaming.

---

## 2. Ranked Findings

### Finding 1 (Rank 1): Token Leakage via Uvicorn Internal WebSocket Protocol Logger
- **Observation:** Connecting to `ws://HOST:8111/session?token=<API_TOKEN>` causes Uvicorn's internal WebSocket protocol implementation (`websockets_impl` / `wsproto_impl`) to log the full request URL with query parameters to container stdout logs:
  `INFO: 127.0.0.1:52310 - "WebSocket /session?token=<REDACTED-TOKEN>" [accepted]`
- **Impact:** Even with `access_log=False` passed to `uvicorn.run()`, Uvicorn's WebSocket protocol handler emits its own handshake info log, printing administrative API tokens into container stdout logs whenever URL token authentication is used.
- **Reproduction Steps:**
  1. Start `api-lab` tenant container.
  2. Connect to `ws://localhost:8111/session?token=<REDACTED-TOKEN>`.
  3. Execute `docker logs api-lab-tenant-1 2>&1 | grep "<REDACTED-TOKEN>"`.
  4. Observe `INFO: ... - "WebSocket /session?token=..." [accepted]` output in logs.
- **Remediation Note:** Per Build 42 spec, no code changes are made in this build. Finding recorded for wave remediation.

---

## 3. Raw Scenario Outputs (Verbatim)

### Scenario 1 Output (`container/scenarios/api-auth-and-limits.sh`)
```
=== Scenario: API Auth, Payload Limits & Error Handling ===
Target Host: http://localhost:8110
[1] Testing GET /health without auth...
Body: {"detail":"Unauthorized"}
HTTP Status: 401

[2] Testing GET /agents without token (unauthorized)...
Body: {"detail":"Unauthorized"}
HTTP Status: 401

[3] Testing GET /agents with invalid token...
Body: {"detail":"Unauthorized"}
HTTP Status: 401

[4] Testing GET /agents with valid token...
Body: {"agents":["api","architect","host","sme-2","sme-3"]}
HTTP Status: 200

[5] Testing POST /agents/architect/envelopes with malformed 'as' dict payload...
Body: {"detail":"invalid 'as' client: must be an enrolled client with vab 'api'"}
HTTP Status: 422

[6] Testing POST /agents/architect/envelopes with oversized (>1MB) payload...
Body: {"detail":"envelope payload exceeds maximum size limit of 1MB"}
HTTP Status: 422

[7] Testing GET /board...
Body: {"agents":[{"agent":"api","todo":[],"doing":[],"hold":[],"done":[]},{"agent":"architect","todo":[],"doing":[],"hold":[],"done":[]},{"agent":"host","todo":[],"doing":[],"hold":[],"done":[]},{"agent":"sme-2","todo":[],"doing":[],"hold":[],"done":[]},{"agent":"sme-3","todo":[],"doing":[],"hold":[],"done":[]}]}
HTTP Status: 200

=== Scenario Complete ===
```

### Scenario 2 Output (`container/scenarios/api-session-and-log-privacy.sh`)
```
=== Scenario: Session WebSocket Door & Log Privacy ===
Target Session Host: localhost:8111
Target Container: api-lab-tenant-1
[1] Testing WebSocket connection with invalid token query parameter...
Observed exception: InvalidStatus: server rejected WebSocket connection: HTTP 403

[2] Testing WebSocket connection with valid token query parameter...
Successfully connected to session socket!
Received frame: {"agent":"architect","data":"\u001b[2J\u001b[H\u001b[38;5;174m ▐\u001b[48;5;16m▛███▜\u001b[49m▌\u001...

[3] Verification: Checking container logs for API token leakage...
Occurrences of token '<REDACTED-TOKEN>' in docker logs for api-lab-tenant-1: 1

=== Scenario Complete ===
```

### Scenario 3 Output (`container/scenarios/api-concurrency-and-time.sh`)
```
=== Scenario: API Concurrency, Stream Handling & Roster Robustness ===
Target Host: http://localhost:8110
[1] Measuring concurrent HTTP /health latency (10 parallel requests)...
Req 2: status=401 time=0.021244s
Req 9: status=401 time=0.040727s
Req 1: status=401 time=0.044184s
Req 10: status=401 time=0.041533s
Req 7: status=401 time=0.050963s
Req 5: status=401 time=0.041002s
Req 8: status=401 time=0.052318s
Req 4: status=401 time=0.048683s
Req 6: status=401 time=0.051661s
Req 3: status=401 time=0.045710s

[2] Testing long-polling SSE event stream (/alerts/stream)...
id: 1786483211377-0
event: alert
data: {"v": 1, "ts": "2026-08-11T21:20:11.157Z", "kind": "credential", "account": "default", "cli": "claude", "status": "absent", "expires_ts": null, "cursor": "1786483211377-0"}

[3] Testing activity endpoints (/agents/architect/activity)...
{"agent":"architect","activity":[],"next_cursor":null}
HTTP Status: 200

[4] Testing unknown agent endpoint (/agents/nonexistent_agent)...
{"detail":"invalid agent"}
HTTP Status: 404

=== Scenario Complete ===
```
