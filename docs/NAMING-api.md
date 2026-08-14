# Naming & Vocabulary Inventory — `flock.api` & `flock.session`

Comprehensive inventory of names, identifiers, Redis keys, environment variables, wire fields, and doc terms for the `flock.api` REST API door (`:8080`), `flock.session` WebSocket door (`:8081`), and `API.md` public wire surface.

---

## 1. Inventory Table

| Name / Term | Where It Lives | Kind | Single-Line Meaning | Networking Analogue | Tier |
|---|---|---|---|---|---|
| `GET /health` | [`API.md:243`](file:///workspace/api/h-flock/docs/API.md#L243), [`app.py:562`](file:///workspace/api/h-flock/src/flock/api/app.py#L562) | `wire` | REST provider for tenant L1/L7 liveness check | L7 Health Probe | **Tier D** |
| `GET /agents` | [`API.md:257`](file:///workspace/api/h-flock/docs/API.md#L257), [`app.py:566`](file:///workspace/api/h-flock/src/flock/api/app.py#L566) | `wire` | REST provider returning list of all enrolled agent names | L7 Directory Service Query | **Tier D** |
| `GET /agents/{agent}` | [`API.md:274`](file:///workspace/api/h-flock/docs/API.md#L274), [`app.py:570`](file:///workspace/api/h-flock/src/flock/api/app.py#L570) | `wire` | REST provider returning queue depths, presence state, and port_type mode for an agent | L7 Node Status & Depths Query | **Tier D** |
| `POST /agents/{agent}/envelopes` | [`API.md:333`](file:///workspace/api/h-flock/docs/API.md#L333), [`app.py:607`](file:///workspace/api/h-flock/src/flock/api/app.py#L607) | `wire` | REST provider for posting an envelope onto the bus egress queue | L7 Packet Ingress Gateway | **Tier D** |
| `GET /agents/{agent}/messages` | [`API.md:156`](file:///workspace/api/h-flock/docs/API.md#L156), [`app.py:668`](file:///workspace/api/h-flock/src/flock/api/app.py#L668) | `wire` | Catch-up polling REST provider for an `api` client's inbox stream | L7 Mailbox Stream Pull | **Tier D** |
| `GET /agents/{agent}/messages/stream` | [`API.md:179`](file:///workspace/api/h-flock/docs/API.md#L179), [`app.py:685`](file:///workspace/api/h-flock/src/flock/api/app.py#L685) | `wire` | Live Server-Sent Events (SSE) stream of inbox messages for an `api` client | L7 Mailbox Event Push Stream | **Tier D** |
| `GET /agents/{agent}/activity` | [`API.md:532`](file:///workspace/api/h-flock/docs/API.md#L532), [`app.py:696`](file:///workspace/api/h-flock/src/flock/api/app.py#L696) | `wire` | Catch-up polling REST provider for an agent's execution activity feed | L7 Telemetry Log Query | **Tier D** |
| `GET /agents/{agent}/activity/stream` | [`API.md:564`](file:///workspace/api/h-flock/docs/API.md#L564), [`app.py:717`](file:///workspace/api/h-flock/src/flock/api/app.py#L717) | `wire` | Live SSE stream of execution activity events for an agent | L7 Telemetry Event Stream | **Tier D** |
| `GET /agents/{agent}/board` | [`API.md:434`](file:///workspace/api/h-flock/docs/API.md#L434), [`app.py:750`](file:///workspace/api/h-flock/src/flock/api/app.py#L750) | `wire` | REST provider returning task board columns (`todo`, `doing`, `hold`, `done`) for an agent | L7 Work Queue Inspection | **Tier D** |
| `GET /board` | [`API.md:465`](file:///workspace/api/h-flock/docs/API.md#L465), [`app.py:757`](file:///workspace/api/h-flock/src/flock/api/app.py#L757) | `wire` | REST provider returning task boards for all enrolled tenant agents | L7 Multi-Node Work Queue Dump | **Tier D** |
| `GET /alerts` | [`API.md:587`](file:///workspace/api/h-flock/docs/API.md#L587), [`app.py:778`](file:///workspace/api/h-flock/src/flock/api/app.py#L778) | `wire` | Catch-up polling REST provider for tenant-level watchdog alerts | L7 System Alarm Stream Query | **Tier D** |
| `GET /alerts/stream` | [`API.md:612`](file:///workspace/api/h-flock/docs/API.md#L612), [`app.py:791`](file:///workspace/api/h-flock/src/flock/api/app.py#L791) | `wire` | Live SSE stream of watchdog alert events across the tenant | L7 System Alarm Push Stream | **Tier D** |
| `GET /restdoc` | [`API.md:151`](file:///workspace/api/h-flock/docs/API.md#L151), [`app.py:558`](file:///workspace/api/h-flock/src/flock/api/app.py#L558) | `wire` | Self-contained HTML documentation page describing providers and schemas | L7 Documentation Endpoint | **Tier D** |
| `ws://HOST:8111/session` | [`API.md:664`](file:///workspace/api/h-flock/docs/API.md#L664), [`session/app.py:152`](file:///workspace/api/h-flock/src/flock/session/app.py#L152) | `wire` | WebSocket provider for live terminal output streaming and keystroke input | L7 Interactive Terminal Socket | **Tier D** |
| `as` | [`API.md:99`](file:///workspace/api/h-flock/docs/API.md#L99), [`app.py:617`](file:///workspace/api/h-flock/src/flock/api/app.py#L617) | `wire` | POST JSON field declaring application client producer identity | Source Address Header | **Tier D** |
| `stream_id` | [`API.md:84`](file:///workspace/api/h-flock/docs/API.md#L84), [`app.py:666`](file:///workspace/api/h-flock/src/flock/api/app.py#L666) | `wire` | Unique trace identifier for published envelope | Flow ID / Packet Sequence ID | **Tier D** |
| `correlation_id` | [`API.md:85`](file:///workspace/api/h-flock/docs/API.md#L85), [`app.py:666`](file:///workspace/api/h-flock/src/flock/api/app.py#L666) | `wire` | Transaction correlation identifier for tracking request-reply pairs | Session Transaction ID | **Tier D** |
| `cursor` / `next_cursor` | [`API.md:140`](file:///workspace/api/h-flock/docs/API.md#L140), [`app.py:678`](file:///workspace/api/h-flock/src/flock/api/app.py#L678) | `wire` | Stream position token (Redis stream entry ID) for catching up on streams | Stream Sequence ACK Pointer | **Tier D** |
| `after` | [`API.md:161`](file:///workspace/api/h-flock/docs/API.md#L161), [`app.py:671`](file:///workspace/api/h-flock/src/flock/api/app.py#L671) | `wire` | Stream pagination query parameter specifying starting cursor ID | Sequence Resume Pointer | **Tier D** |
| `port_type` | [`API.md:307`](file:///workspace/api/h-flock/docs/API.md#L307), [`app.py:591`](file:///workspace/api/h-flock/src/flock/api/app.py#L591) | `wire` | Response JSON field stating virtual agent base mode (`api` \| `tmux` \| `control`) | Switch Port Encapsulation Type | **Tier D** |
| `depths` | [`API.md:308`](file:///workspace/api/h-flock/docs/API.md#L308), [`app.py:595`](file:///workspace/api/h-flock/src/flock/api/app.py#L595) | `wire` | Response JSON object containing queue lengths (`ingress`, `egress`, `dead`) | Buffer Queue Lengths | **Tier D** |
| `presence` | [`API.md:313`](file:///workspace/api/h-flock/docs/API.md#L313), [`app.py:600`](file:///workspace/api/h-flock/src/flock/api/app.py#L600) | `wire` | Response JSON object returning agent execution state (`working`, `idle`, `unknown`, `blocked`) | Link / Node Keepalive Status | **Tier D** |
| `subscribe` | [`API.md:405`](file:///workspace/api/h-flock/docs/API.md#L405), [`session/app.py:193`](file:///workspace/api/h-flock/src/flock/session/app.py#L193) | `wire` | WebSocket JSON message array listing agent names to receive terminal output for | Multicast Channel Membership | **Tier D** |
| `mode` | [`API.md:405`](file:///workspace/api/h-flock/docs/API.md#L405), [`session/app.py:194`](file:///workspace/api/h-flock/src/flock/session/app.py#L194) | `wire` | WebSocket JSON field setting terminal driving permissions (`read-only` \| `read-write`) | Socket ACL Mode | **Tier D** |
| `API_TOKEN` | [`app.py:40`](file:///workspace/api/h-flock/src/flock/api/app.py#L40), [`session/app.py:55`](file:///workspace/api/h-flock/src/flock/session/app.py#L55) | `env var` | Tenant-wide shared Bearer token secret for HTTP and WebSocket authentication | Preshared Key (PSK) | **Tier C** |
| `API_BIND` | [`app.py:41`](file:///workspace/api/h-flock/src/flock/api/app.py#L41) | `env var` | IP address bound by uvicorn for REST API door (default `127.0.0.1`) | Network Interface Bind Address | **Tier C** |
| `API_PORT` | [`app.py:42`](file:///workspace/api/h-flock/src/flock/api/app.py#L42) | `env var` | Host/container TCP port number for REST API door (default `8080`) | Listening TCP Port | **Tier C** |
| `SESSION_BIND` | [`session/app.py:65`](file:///workspace/api/h-flock/src/flock/session/app.py#L65) | `env var` | IP address bound by uvicorn for Session WebSocket door (default `127.0.0.1`) | Network Interface Bind Address | **Tier C** |
| `SESSION_PORT` | [`session/app.py:66`](file:///workspace/api/h-flock/src/flock/session/app.py#L66) | `env var` | Host/container TCP port number for Session WebSocket door (default `8081`) | Listening TCP Port | **Tier C** |
| `API_TLS_CERT` / `KEY` | [`app.py:43`](file:///workspace/api/h-flock/src/flock/api/app.py#L43) | `env var` | Filepaths to TLS certificate and key for REST API door | TLS Server Credential | **Tier C** |
| `SESSION_TLS_CERT` / `KEY` | [`session/app.py:59`](file:///workspace/api/h-flock/src/flock/session/app.py#L59) | `env var` | Filepaths to TLS certificate and key for Session WebSocket door | TLS Server Credential | **Tier C** |
| `FLOCK_ALLOW_PLAINTEXT` | [`app.py:70`](file:///workspace/api/h-flock/src/flock/api/app.py#L70), [`session/app.py:29`](file:///workspace/api/h-flock/src/flock/session/app.py#L29) | `env var` | Flag indicating non-loopback bind has been approved by entrypoint | Cleartext Transport Override | **Tier C** |
| `REDIS_URL` | [`app.py:39`](file:///workspace/api/h-flock/src/flock/api/app.py#L39) | `env var` | Connection URI for tenant Redis database | Bus Host Address | **Tier C** |
| `TMUX_SESSION` | [`session/app.py:64`](file:///workspace/api/h-flock/src/flock/session/app.py#L64) | `env var` | Target tmux session name attached by control-mode client | Terminal Session ID | **Tier C** |
| `TMUX_SOCKET` | [`session/app.py:67`](file:///workspace/api/h-flock/src/flock/session/app.py#L67) | `env var` | Custom socket path for tenant tmux server | Unix Domain Socket Path | **Tier C** |
| `pod:<p>:tenant:<t>:roster` | [`app.py:568`](file:///workspace/api/h-flock/src/flock/api/app.py#L568) | `redis key` | Hash storing mapping of enrolled agent names to VABs | MAC Address Table | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:ingress` | [`app.py:573`](file:///workspace/api/h-flock/src/flock/api/app.py#L573) | `redis key` | List queue holding inbound envelopes for an agent | Node Ingress Buffer | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:egress` | [`app.py:574`](file:///workspace/api/h-flock/src/flock/api/app.py#L574) | `redis key` | List queue holding outbound envelopes from an agent | Node Egress Buffer | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:dead` | [`app.py:575`](file:///workspace/api/h-flock/src/flock/api/app.py#L575) | `redis key` | List queue holding dead-lettered envelopes for an agent | Drop Queue | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:inbox` | [`app.py:676`](file:///workspace/api/h-flock/src/flock/api/app.py#L676) | `redis key` | Stream key holding per-client application inbox messages | Node Mailbox Stream | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:activity` | [`app.py:708`](file:///workspace/api/h-flock/src/flock/api/app.py#L708) | `redis key` | Stream key holding agent execution activity events | Telemetry Log Stream | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:presence` | [`app.py:576`](file:///workspace/api/h-flock/src/flock/api/app.py#L576) | `redis key` | Hash key storing agent presence state (`working`, `idle`, `unknown`) | Node Keepalive Record | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:blocked` | [`app.py:577`](file:///workspace/api/h-flock/src/flock/api/app.py#L577) | `redis key` | Hash key indicating unverified delivery status for an agent | Node Link Stall Marker | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:tasks.<s` | [`app.py:735`](file:///workspace/api/h-flock/src/flock/api/app.py#L735) | `redis key` | List keys storing task board columns (`todo`, `doing`, `hold`, `done`) | Work Queue Lists | **Tier C** |
| `pod:<p>:tenant:<t>:alerts` | [`app.py:783`](file:///workspace/api/h-flock/src/flock/api/app.py#L783) | `redis key` | Stream key holding tenant watchdog alert events | Alarm Event Stream | **Tier C** |
| `Settings` | [`app.py:24`](file:///workspace/api/h-flock/src/flock/api/app.py#L24) | `identifier` | Configuration dataclass for REST API server | Server Config Dataclass | **Tier B** |
| `SessionSettings` | [`session/app.py:43`](file:///workspace/api/h-flock/src/flock/session/app.py#L43) | `identifier` | Configuration dataclass for Session WebSocket server | Session Config Dataclass | **Tier B** |
| `ControlModeClient` | [`session/control.py:49`](file:///workspace/api/h-flock/src/flock/session/control.py#L49) | `identifier` | Class managing background `tmux -C` control-mode connection | Terminal Stream Multiplexer | **Tier B** |
| `Subscriber` | [`session/control.py:41`](file:///workspace/api/h-flock/src/flock/session/control.py#L41) | `identifier` | Dataclass tracking per-WebSocket connection queue and subscribed agents | Subscriber Connection State | **Tier B** |
| `create_app` | [`app.py:520`](file:///workspace/api/h-flock/src/flock/api/app.py#L520), [`session/app.py:130`](file:///workspace/api/h-flock/src/flock/session/app.py#L130) | `identifier` | Factory function returning configured FastAPI instance | App Builder Factory | **Tier B** |
| `_authorized` | [`session/app.py:88`](file:///workspace/api/h-flock/src/flock/session/app.py#L88) | `identifier` | Helper checking Bearer header or URL token parameter | Authentication Guard | **Tier B** |
| `authorize` | [`app.py:526`](file:///workspace/api/h-flock/src/flock/api/app.py#L526) | `identifier` | FastAPI dependency enforcing Bearer token authentication | Route Auth Guard | **Tier B** |
| `_read_stream_entries` | [`app.py:434`](file:///workspace/api/h-flock/src/flock/api/app.py#L434) | `identifier` | Redis stream XRANGE query and JSON decoding helper | Stream Reader Helper | **Tier B** |
| `_stream_response` | [`app.py:474`](file:///workspace/api/h-flock/src/flock/api/app.py#L474) | `identifier` | Generator creating FastAPI StreamingResponse for SSE providers | SSE Event Generator | **Tier B** |
| `_unescape_control` | [`session/control.py:19`](file:///workspace/api/h-flock/src/flock/session/control.py#L19) | `identifier` | Function turning tmux octal-escaped bytes into raw terminal bytes | Control Byte Unescaper | **Tier B** |
| `_connection_log` | [`session/app.py:105`](file:///workspace/api/h-flock/src/flock/session/app.py#L105) | `identifier` | Helper logging structured JSON connection closure records | Connection Audit Logger | **Tier B** |
| `REST API` | [`API.md:39`](file:///workspace/api/h-flock/docs/API.md#L39) | `doc term` | HTTP interface for data, envelopes, mailboxes, and state (`:8080`) | Control Plane REST Gateway | **Tier A** |
| `Session Service` | [`API.md:40`](file:///workspace/api/h-flock/docs/API.md#L40) | `doc term` | WebSocket interface for terminal output streaming and keystrokes (`:8081`) | Terminal Data Gateway | **Tier A** |
| `Mailbox` | [`API.md:150`](file:///workspace/api/h-flock/docs/API.md#L150) | `doc term` | Dedicated per-client inbox stream (`<prefix>:agent:<client>:inbox`) | Receiver Buffer Stream | **Tier A** |
| `Sugar` | [`LLD-api.md:76`](file:///workspace/api/h-flock/docs/LLD-api.md#L76) | `doc term` | Shorthand JSON payload `{"text": "..."}` implying `kind: "Message"` | Convenience Payload Syntax | **Tier A** |
| `port_type` | [`LLD-api.md:48`](file:///workspace/api/h-flock/docs/LLD-api.md#L48), [`API.md:307`](file:///workspace/api/h-flock/docs/API.md#L307) | `doc term` | Virtual Agent Base mode (`api` \| `tmux` \| `control`) | Switch Port Encapsulation | **Tier A** |

---

## 2. Callouts for Collisions, Drifts, and Undeterminable Names

### 1. One Word, Two Meanings (Collisions)
- **`as`**: On `POST /agents/{agent}/envelopes` (wire), `"as"` declares producer origin (`"as": "telegram"`). However, in CLI commands `office send -a <agent>`, `-a` means the destination recipient. Thus, `-a` on the CLI means destination, while `"as"` on the wire means origin!
- **`session`**: Refers to `flock.session` (the WebSocket door service on `:8081`), the tenant tmux session (`TMUX_SESSION`), and an individual client's WebSocket connection (`session_socket`). Three distinct objects share the same noun.
- **`mode`**: In `SessionSettings` / WebSocket frame, `mode` means `read-only` vs `read-write` permission for terminal driving. In `presence.state` or `watchdog`, `mode` is sometimes used informally to refer to execution state.

### 2. Two Words, One Meaning (Drifts)
- **`after` vs `cursor` vs `Last-Event-ID`**: The pagination pointer for stream providers is called `after` in query parameters (`?after=`), `cursor` in JSON response bodies (`"cursor": "1786..."`), and `Last-Event-ID` in HTTP SSE request headers.
- **`producer` vs `as`**: The envelope schema field naming the origin is `producer`, but the HTTP JSON parameter used to declare it on `POST /agents/{agent}/envelopes` is `as`.
- **`port_type` vs `Virtual Agent Base`**: In Redis and JSON wire responses, the field is `port_type` (`"port_type": "api"`). In docs, it is expanded as "Virtual Agent Base".

### 3. Undeterminable / Misleading Names
- **`port_type` ("Virtual Agent Base")**: Documented as "Virtual Agent Base", but for an `api` client (which has no base, no workspace, no window, and no process) or `control` (host opener), calling it an "agent base" contradicts what it actually is (a switch port encapsulation type / delivery port).
- **`sugar`**: `POST /agents/{agent}/envelopes` accepting `{"text": "hi"}` without `kind` is called "sugar" in `LLD-api.md` and internal comments, but has no formal schema name in `API.md` or OpenAPI specifications.

### 4. Names Contradicting the Network Switch Model
- **`port_type`**: In the network switch model ([`HLD.md`](file:///workspace/api/h-flock/docs/HLD.md)), `port_type` is described as a "port config" or "port type". Calling it "Virtual Agent Base" treats it as a hosting platform rather than a switch port configuration.
- **`provider`**: Env vars `AGENT_PROVIDERS` / `PROVIDER_*` refer to LLM inference provider models (Ollama/vLLM), whereas in networking an provider is a network host:port socket tuple.

---

## 3. Three Most-Wanted Name Changes

1. **Change `as` parameter on `POST /agents/{agent}/envelopes` to `from` or `producer` (Tier D):**
   - *Why:* On the wire, `"as"` specifies producer identity, whereas in `office send -a <agent>` CLI syntax `-a` specifies destination recipient. Renaming the JSON field to `"from"` or `"producer"` eliminates the origin/destination collision and matches the envelope schema field (`producer`).
2. **Change `port_type` (wire, redis, docs) to `port_type` or `driver` (Tier D / Tier C / Tier A):**
   - *Why:* "Virtual Agent Base" implies a hosting environment, which is false for `api` clients (mailboxes) and `control` (openers). Renaming `port_type` to `port_type` or `driver` accurately reflects its role as a switch port delivery encapsulation in the network model.
3. **Change route `GET /agents/{agent}/messages` to `GET /agents/{client}/inbox` (Tier D):**
   - *Why:* The route is only valid for enrolled application clients (`port_type: api`), returning 404 for terminal agents (`port_type: tmux`). Calling it `/messages` suggests a general message query, whereas it specifically polls that client's inbox mailbox stream (`<prefix>:agent:<client>:inbox`). Naming it `/inbox` makes its single-client mailbox nature explicit.
