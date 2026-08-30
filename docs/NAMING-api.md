# Naming & Vocabulary Inventory — `flock.api` & `flock.session`

Comprehensive inventory of names, identifiers, Redis keys, environment variables, wire fields, and doc terms for the `flock.api` REST API door (`:8080`), `flock.session` WebSocket door (`:8081`), and `API.md` public wire surface.

---

## 1. Inventory Table

| Name / Term | Where It Lives | Kind | Single-Line Meaning | Networking Analogue | Tier |
|---|---|---|---|---|---|
| `GET /health` | [`API.md:291`](file:///workspace/api/h-flock/docs/API.md#L291), [`app.py:755`](file:///workspace/api/h-flock/src/flock/api/app.py#L755) | `wire` | REST provider for tenant L1/L7 liveness check | L7 Health Probe | **Tier D** |
| `GET /agents` | [`API.md:305`](file:///workspace/api/h-flock/docs/API.md#L305), [`app.py:759`](file:///workspace/api/h-flock/src/flock/api/app.py#L759) | `wire` | REST provider returning list of all enrolled agent names | L7 Directory Service Query | **Tier D** |
| `GET /agents/{agent}` | [`API.md:322`](file:///workspace/api/h-flock/docs/API.md#L322), [`app.py:763`](file:///workspace/api/h-flock/src/flock/api/app.py#L763) | `wire` | REST provider returning queue depths, presence state, and port_type mode for an agent | L7 Node Status & Depths Query | **Tier D** |
| `POST /agents/{agent}/envelopes` | [`API.md:381`](file:///workspace/api/h-flock/docs/API.md#L381), [`app.py:800`](file:///workspace/api/h-flock/src/flock/api/app.py#L800) | `wire` | REST provider for posting an envelope onto the bus egress queue | L7 Packet Ingress Gateway | **Tier D** |
| `GET /agents/{agent}/messages` | [`API.md:204`](file:///workspace/api/h-flock/docs/API.md#L204), [`app.py:883`](file:///workspace/api/h-flock/src/flock/api/app.py#L883) | `wire` | Catch-up polling REST provider for an `api` client's inbox stream | L7 Mailbox Stream Pull | **Tier D** |
| `GET /agents/{agent}/messages/stream` | [`API.md:227`](file:///workspace/api/h-flock/docs/API.md#L227), [`app.py:900`](file:///workspace/api/h-flock/src/flock/api/app.py#L900) | `wire` | Live Server-Sent Events (SSE) stream of inbox messages for an `api` client | L7 Mailbox Event Push Stream | **Tier D** |
| `GET /agents/{agent}/activity` | [`API.md:693`](file:///workspace/api/h-flock/docs/API.md#L693), [`app.py:911`](file:///workspace/api/h-flock/src/flock/api/app.py#L911) | `wire` | Catch-up polling REST provider for an agent's execution activity feed | L7 Telemetry Log Query | **Tier D** |
| `GET /agents/{agent}/activity/stream` | [`API.md:725`](file:///workspace/api/h-flock/docs/API.md#L725), [`app.py:932`](file:///workspace/api/h-flock/src/flock/api/app.py#L932) | `wire` | Live SSE stream of execution activity events for an agent | L7 Telemetry Event Stream | **Tier D** |
| `GET /agents/{agent}/board` | [`API.md:595`](file:///workspace/api/h-flock/docs/API.md#L595), [`app.py:965`](file:///workspace/api/h-flock/src/flock/api/app.py#L965) | `wire` | REST provider returning task board columns (`todo`, `doing`, `hold`, `done`) for an agent | L7 Work Queue Inspection | **Tier D** |
| `GET /board` | [`API.md:626`](file:///workspace/api/h-flock/docs/API.md#L626), [`app.py:972`](file:///workspace/api/h-flock/src/flock/api/app.py#L972) | `wire` | REST provider returning task boards for all enrolled tenant agents | L7 Multi-Node Work Queue Dump | **Tier D** |
| `GET /alerts` | [`API.md:748`](file:///workspace/api/h-flock/docs/API.md#L748), [`app.py:993`](file:///workspace/api/h-flock/src/flock/api/app.py#L993) | `wire` | Catch-up polling REST provider for tenant-level watchdog alerts | L7 System Alarm Stream Query | **Tier D** |
| `GET /alerts/stream` | [`API.md:773`](file:///workspace/api/h-flock/docs/API.md#L773), [`app.py:1006`](file:///workspace/api/h-flock/src/flock/api/app.py#L1006) | `wire` | Live SSE stream of watchdog alert events across the tenant | L7 System Alarm Push Stream | **Tier D** |
| `GET /restdoc` | [`LLD-api.md:58`](file:///workspace/api/h-flock/docs/LLD-api.md#L58), [`app.py:751`](file:///workspace/api/h-flock/src/flock/api/app.py#L751) | `wire` | Self-contained HTML documentation page describing providers and schemas | L7 Documentation Endpoint | **Tier D** |
| `ws://HOST:8081/session` | [`API.md:825`](file:///workspace/api/h-flock/docs/API.md#L825), [`session/app.py:152`](file:///workspace/api/h-flock/src/flock/session/app.py#L152) | `wire` | WebSocket provider for live terminal output streaming and keystroke input | L7 Interactive Terminal Socket | **Tier D** |
| `as` | [`API.md:396`](file:///workspace/api/h-flock/docs/API.md#L396), [`app.py:814`](file:///workspace/api/h-flock/src/flock/api/app.py#L814) | `wire` | POST JSON field declaring application client source identity | Source Address Header | **Tier D** |
| `stream_id` | [`API.md:52`](file:///workspace/api/h-flock/docs/API.md#L52), [`app.py:870`](file:///workspace/api/h-flock/src/flock/api/app.py#L870) | `wire` | Unique trace identifier for published envelope | Flow ID / Packet Sequence ID | **Tier D** |
| `correlation_id` | [`API.md:53`](file:///workspace/api/h-flock/docs/API.md#L53), [`app.py:870`](file:///workspace/api/h-flock/src/flock/api/app.py#L870) | `wire` | Transaction correlation identifier for tracking request-reply pairs | Session Transaction ID | **Tier D** |
| `cursor` / `next_cursor` | [`API.md:223`](file:///workspace/api/h-flock/docs/API.md#L223), [`app.py:890`](file:///workspace/api/h-flock/src/flock/api/app.py#L890) | `wire` | Stream position token (Redis stream entry ID) for catching up on streams | Stream Sequence ACK Pointer | **Tier D** |
| `after` | [`API.md:208`](file:///workspace/api/h-flock/docs/API.md#L208), [`app.py:885`](file:///workspace/api/h-flock/src/flock/api/app.py#L885) | `wire` | Stream pagination query parameter specifying starting cursor ID | Sequence Resume Pointer | **Tier D** |
| `port_type` | [`API.md:354`](file:///workspace/api/h-flock/docs/API.md#L354), [`app.py:785`](file:///workspace/api/h-flock/src/flock/api/app.py#L785) | `wire` | Response JSON field stating virtual agent base mode (`api` \| `tmux` \| `control`) | Switch Port Encapsulation Type | **Tier D** |
| `depths` | [`API.md:355`](file:///workspace/api/h-flock/docs/API.md#L355), [`app.py:788`](file:///workspace/api/h-flock/src/flock/api/app.py#L788) | `wire` | Response JSON object containing queue lengths (`ingress`, `egress`, `dead`) | Buffer Queue Lengths | **Tier D** |
| `presence` | [`API.md:360`](file:///workspace/api/h-flock/docs/API.md#L360), [`app.py:794`](file:///workspace/api/h-flock/src/flock/api/app.py#L794) | `wire` | Response JSON object returning agent execution state (`working`, `idle`, `unknown`, `blocked`) | Link / Node Keepalive Status | **Tier D** |
| `kid` | [`API.md:481`](file:///workspace/api/h-flock/docs/API.md#L481), [`app.py:808`](file:///workspace/api/h-flock/src/flock/api/app.py#L808) | `wire` | POST JSON field naming which registered per-client key signs `sig`, published-door only | Key ID | **Tier D** |
| `sig` | [`API.md:482`](file:///workspace/api/h-flock/docs/API.md#L482), [`app.py:132`](file:///workspace/api/h-flock/src/flock/api/app.py#L132) | `wire` | POST JSON field, HMAC-SHA256 over the canonical envelope minus itself, published-door only | Message Signature | **Tier D** |
| `hmac_secret` / `kid` (StartAgent) | [`API.md:551`](file:///workspace/api/h-flock/docs/API.md#L551), [`control/openers.py:177-178`](file:///workspace/api/h-flock/src/flock/control/openers.py#L177-L178) | `wire` | `StartAgent` payload fields, `port_type: "api"` only — client-supplied secret and its key id, added not replaced | Client-Supplied Key Registration | **Tier D** |
| `revoke_kid` | [`API.md:553`](file:///workspace/api/h-flock/docs/API.md#L553), [`control/openers.py:179`](file:///workspace/api/h-flock/src/flock/control/openers.py#L179) | `wire` | `StartAgent` payload field removing one registered key by `kid` | Key Revocation | **Tier D** |
| `API_PUBLISHED` | [`entrypoint.sh`](file:///workspace/api/h-flock/container/entrypoint.sh), [`app.py:48`](file:///workspace/api/h-flock/src/flock/api/app.py#L48) | `env var` | Set by `entrypoint.sh` (not operator-facing) when the api door has a host mapping — gates per-client HMAC and CORS | Exposure-Judged Flag | **Tier C** |
| `API_CORS_ORIGINS` | [`app.py:53`](file:///workspace/api/h-flock/src/flock/api/app.py#L53) | `env var` | Comma-separated allowed browser origins, effective only when `API_PUBLISHED=1` | CORS Allow-List | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:hmac-keys` | [`app.py:145`](file:///workspace/api/h-flock/src/flock/api/app.py#L145), [`control/openers.py:205`](file:///workspace/api/h-flock/src/flock/control/openers.py#L205) | `redis key` | Hash of `kid → {secret, created_ts}` for a `port_type: "api"` client, stored in the clear | Symmetric Key Store | **Tier C** |
| `subscribe` | [`LLD-session.md:71`](file:///workspace/api/h-flock/docs/LLD-session.md#L71), [`session/app.py:193`](file:///workspace/api/h-flock/src/flock/session/app.py#L193) | `wire` | WebSocket JSON message array listing agent names to receive terminal output for | Multicast Channel Membership | **Tier D** |
| `mode` | [`LLD-session.md:104`](file:///workspace/api/h-flock/docs/LLD-session.md#L104), [`session/app.py:194`](file:///workspace/api/h-flock/src/flock/session/app.py#L194) | `wire` | WebSocket JSON field setting terminal driving permissions (`read-only` \| `read-write`) | Socket ACL Mode | **Tier D** |
| `API_TOKEN` | [`app.py:58`](file:///workspace/api/h-flock/src/flock/api/app.py#L58), [`session/app.py:55`](file:///workspace/api/h-flock/src/flock/session/app.py#L55) | `env var` | Tenant-wide shared Bearer token secret for HTTP and WebSocket authentication | Preshared Key (PSK) | **Tier C** |
| `API_BIND` | [`app.py:59`](file:///workspace/api/h-flock/src/flock/api/app.py#L59) | `env var` | IP address bound by uvicorn for REST API door (default `127.0.0.1`) | Network Interface Bind Address | **Tier C** |
| `API_PORT` | [`app.py:60`](file:///workspace/api/h-flock/src/flock/api/app.py#L60) | `env var` | Host/container TCP port number for REST API door (default `8080`) | Listening TCP Port | **Tier C** |
| `SESSION_BIND` | [`session/app.py:67`](file:///workspace/api/h-flock/src/flock/session/app.py#L67) | `env var` | IP address bound by uvicorn for Session WebSocket door (default `127.0.0.1`) | Network Interface Bind Address | **Tier C** |
| `SESSION_PORT` | [`session/app.py:68`](file:///workspace/api/h-flock/src/flock/session/app.py#L68) | `env var` | Host/container TCP port number for Session WebSocket door (default `8081`) | Listening TCP Port | **Tier C** |
| `API_TLS_CERT` / `API_TLS_KEY` | [`app.py:61-62`](file:///workspace/api/h-flock/src/flock/api/app.py#L61-L62) | `env var` | Filepaths to TLS certificate and key for REST API door | TLS Server Credential | **Tier C** |
| `SESSION_TLS_CERT` / `SESSION_TLS_KEY` | [`session/app.py:61-62`](file:///workspace/api/h-flock/src/flock/session/app.py#L61-L62) | `env var` | Filepaths to TLS certificate and key for Session WebSocket door | TLS Server Credential | **Tier C** |
| `FLOCK_ALLOW_PLAINTEXT` | [`app.py:90`](file:///workspace/api/h-flock/src/flock/api/app.py#L90), [`session/app.py:29`](file:///workspace/api/h-flock/src/flock/session/app.py#L29) | `env var` | Flag indicating non-loopback bind has been approved by entrypoint | Cleartext Transport Override | **Tier C** |
| `REDIS_URL` | [`app.py:57`](file:///workspace/api/h-flock/src/flock/api/app.py#L57) | `env var` | Connection URI for tenant Redis database | Bus Host Address | **Tier C** |
| `TMUX_SESSION` | [`session/app.py:66`](file:///workspace/api/h-flock/src/flock/session/app.py#L66) | `env var` | Target tmux session name attached by control-mode client | Terminal Session ID | **Tier C** |
| `TMUX_SOCKET` | [`session/app.py:69`](file:///workspace/api/h-flock/src/flock/session/app.py#L69) | `env var` | Custom socket path for tenant tmux server | Unix Domain Socket Path | **Tier C** |
| `pod:<p>:tenant:<t>:roster` | [`app.py:760`](file:///workspace/api/h-flock/src/flock/api/app.py#L760) | `redis key` | Hash storing mapping of enrolled agent names to VABs | MAC Address Table | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:ingress` | [`app.py:766`](file:///workspace/api/h-flock/src/flock/api/app.py#L766) | `redis key` | List queue holding inbound envelopes for an agent | Node Ingress Buffer | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:egress` | [`app.py:767`](file:///workspace/api/h-flock/src/flock/api/app.py#L767) | `redis key` | List queue holding outbound envelopes from an agent | Node Egress Buffer | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:dead` | [`app.py:768`](file:///workspace/api/h-flock/src/flock/api/app.py#L768) | `redis key` | List queue holding dead-lettered envelopes for an agent | Drop Queue | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:inbox` | [`app.py:889`](file:///workspace/api/h-flock/src/flock/api/app.py#L889) | `redis key` | Stream key holding per-client application inbox messages | Node Mailbox Stream | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:activity` | [`app.py:919`](file:///workspace/api/h-flock/src/flock/api/app.py#L919) | `redis key` | Stream key holding agent execution activity events | Telemetry Log Stream | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:presence` | [`app.py:769`](file:///workspace/api/h-flock/src/flock/api/app.py#L769) | `redis key` | Hash key storing agent presence state (`working`, `idle`, `unknown`) | Node Keepalive Record | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:blocked` | [`app.py:770`](file:///workspace/api/h-flock/src/flock/api/app.py#L770) | `redis key` | Hash key indicating unverified delivery status for an agent | Node Link Stall Marker | **Tier C** |
| `pod:<p>:tenant:<t>:agent:<a>:tasks.<state>` | [`app.py:950`](file:///workspace/api/h-flock/src/flock/api/app.py#L950) | `redis key` | List keys storing task board columns (`todo`, `doing`, `hold`, `done`) | Work Queue Lists | **Tier C** |
| `pod:<p>:tenant:<t>:alerts` | [`app.py:999`](file:///workspace/api/h-flock/src/flock/api/app.py#L999) | `redis key` | Stream key holding tenant watchdog alert events | Alarm Event Stream | **Tier C** |
| `pod:<p>:tenant:<t>:usage` | [`cli.py:962`](file:///workspace/api/h-flock/src/flock/office/cli.py#L962) | `redis key` | Aggregated tenant token usage and cost records stream (CLI `office usage`, not HTTP) | Usage Metering Stream | **Tier C** |
| `Settings` | [`app.py:39`](file:///workspace/api/h-flock/src/flock/api/app.py#L39) | `identifier` | Configuration dataclass for REST API server | Server Config Dataclass | **Tier B** |
| `SessionSettings` | [`session/app.py:45`](file:///workspace/api/h-flock/src/flock/session/app.py#L45) | `identifier` | Configuration dataclass for Session WebSocket server | Session Config Dataclass | **Tier B** |
| `ControlModeClient` | [`session/control.py:49`](file:///workspace/api/h-flock/src/flock/session/control.py#L49) | `identifier` | Class managing background `tmux -C` control-mode connection | Terminal Stream Multiplexer | **Tier B** |
| `Subscriber` | [`session/control.py:41`](file:///workspace/api/h-flock/src/flock/session/control.py#L41) | `identifier` | Dataclass tracking per-WebSocket connection queue and subscribed agents | Subscriber Connection State | **Tier B** |
| `create_app` | [`app.py:698`](file:///workspace/api/h-flock/src/flock/api/app.py#L698), [`session/app.py:132`](file:///workspace/api/h-flock/src/flock/session/app.py#L132) | `identifier` | Factory function returning configured FastAPI instance | App Builder Factory | **Tier B** |
| `_authorized` | [`session/app.py:90`](file:///workspace/api/h-flock/src/flock/session/app.py#L90) | `identifier` | Helper checking Bearer header or URL token parameter | Authentication Guard | **Tier B** |
| `authorize` | [`app.py:704`](file:///workspace/api/h-flock/src/flock/api/app.py#L704) | `identifier` | FastAPI dependency enforcing Bearer token authentication | Route Auth Guard | **Tier B** |
| `_read_stream_entries` | [`app.py:612`](file:///workspace/api/h-flock/src/flock/api/app.py#L612) | `identifier` | Redis stream XRANGE query and JSON decoding helper | Stream Reader Helper | **Tier B** |
| `_stream_response` | [`app.py:652`](file:///workspace/api/h-flock/src/flock/api/app.py#L652) | `identifier` | Generator creating FastAPI StreamingResponse for SSE providers | SSE Event Generator | **Tier B** |
| `_unescape_control` | [`session/control.py:19`](file:///workspace/api/h-flock/src/flock/session/control.py#L19) | `identifier` | Function turning tmux octal-escaped bytes into raw terminal bytes | Control Byte Unescaper | **Tier B** |
| `_connection_log` | [`session/app.py:107`](file:///workspace/api/h-flock/src/flock/session/app.py#L107) | `identifier` | Helper logging structured JSON connection closure records | Connection Audit Logger | **Tier B** |
| `REST API` | [`API.md:84`](file:///workspace/api/h-flock/docs/API.md#L84) | `doc term` | HTTP interface for data, envelopes, mailboxes, and state (`:8080`) | Control Plane REST Gateway | **Tier A** |
| `Session Service` | [`API.md:85`](file:///workspace/api/h-flock/docs/API.md#L85) | `doc term` | WebSocket interface for terminal output streaming and keystrokes (`:8081`) | Terminal Data Gateway | **Tier A** |
| `Mailbox` | [`API.md:196`](file:///workspace/api/h-flock/docs/API.md#L196) | `doc term` | Dedicated per-client inbox stream (`<prefix>:agent:<client>:inbox`) | Receiver Buffer Stream | **Tier A** |
| `sugar` | [`LLD-api.md:76`](file:///workspace/api/h-flock/docs/LLD-api.md#L76) | `doc term` | Shorthand JSON payload `{"text": "..."}` implying `kind: "Message"` | Convenience Payload Syntax | **Tier A** |
| `port_type` | [`LLD-api.md:48`](file:///workspace/api/h-flock/docs/LLD-api.md#L48), [`API.md:354`](file:///workspace/api/h-flock/docs/API.md#L354) | `doc term` | Virtual Agent Base mode (`api` \| `tmux` \| `control`) | Switch Port Encapsulation | **Tier A** |



---

## 2. Callouts for Collisions, Drifts, and Undeterminable Names

### 1. One Word, Two Meanings (Collisions)
- **`as`**: On `POST /agents/{agent}/envelopes` (wire), `"as"` declares source origin (`"as": "telegram"`). However, in CLI commands `office send -a <agent>`, `-a` means the destination destination. Thus, `-a` on the CLI means destination, while `"as"` on the wire means origin!
- **`session`**: Refers to `flock.session` (the WebSocket door service on `:8081`), the tenant tmux session (`TMUX_SESSION`), and an individual client's WebSocket connection (`session_socket`). Three distinct objects share the same noun.
- **`mode`**: In `SessionSettings` / WebSocket frame, `mode` means `read-only` vs `read-write` permission for terminal driving. In `presence.state` or `watchdog`, `mode` is sometimes used informally to refer to execution state.

### 2. Two Words, One Meaning (Drifts)
- **`after` vs `cursor` vs `Last-Event-ID`**: The pagination pointer for stream providers is called `after` in query parameters (`?after=`), `cursor` in JSON response bodies (`"cursor": "1786..."`), and `Last-Event-ID` in HTTP SSE request headers.
- **`source` vs `as`**: The envelope schema field naming the origin is `source`, but the HTTP JSON parameter used to declare it on `POST /agents/{agent}/envelopes` is `as`.
- **`port_type` vs `Virtual Agent Base`**: In Redis and JSON wire responses, the field is `port_type` (`"port_type": "api"`). In docs, it is expanded as "Virtual Agent Base".

### 3. Undeterminable / Misleading Names
- **`port_type` ("Virtual Agent Base")**: Documented as "Virtual Agent Base", but for an `api` client (which has no base, no workspace, no window, and no process) or `control` (host opener), calling it an "agent base" contradicts what it actually is (a switch port encapsulation type / delivery port).
- **`sugar`**: `POST /agents/{agent}/envelopes` accepting `{"text": "hi"}` without `kind` is called "sugar" in `LLD-api.md` and internal comments, but has no formal schema name in `API.md` or OpenAPI specifications.

### 4. Names Contradicting the Network Switch Model
- **`port_type`**: In the network switch model ([`HLD.md`](file:///workspace/api/h-flock/docs/HLD.md)), `port_type` is described as a "port config" or "port type". Calling it "Virtual Agent Base" treats it as a hosting platform rather than a switch port configuration.
- **`provider`**: Env vars `AGENT_PROVIDERS` / `PROVIDER_*` refer to LLM inference provider models (Ollama/vLLM), whereas in networking a provider is a network host:port socket tuple.

---

## 3. Three Most-Wanted Name Changes

1. **Change `as` parameter on `POST /agents/{agent}/envelopes` to `from` or `source` (Tier D):**
   - *Why:* On the wire, `"as"` specifies source identity, whereas in `office send -a <agent>` CLI syntax `-a` specifies destination destination. Renaming the JSON field to `"from"` or `"source"` eliminates the origin/destination collision and matches the envelope schema field (`source`).
2. **Change `port_type` (wire, redis, docs) to `port_type` or `driver` (Tier D / Tier C / Tier A):**
   - *Why:* "Virtual Agent Base" implies a hosting environment, which is false for `api` clients (mailboxes) and `control` (openers). Renaming `port_type` to `port_type` or `driver` accurately reflects its role as a switch port delivery encapsulation in the network model.
3. **Change route `GET /agents/{agent}/messages` to `GET /agents/{client}/inbox` (Tier D):**
   - *Why:* The route is only valid for enrolled application clients (`port_type: api`), returning 404 for terminal agents (`port_type: tmux`). Calling it `/messages` suggests a general message query, whereas it specifically polls that client's inbox mailbox stream (`<prefix>:agent:<client>:inbox`). Naming it `/inbox` makes its single-client mailbox nature explicit.
