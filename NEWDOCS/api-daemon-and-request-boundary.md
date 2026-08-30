# API server and request-handler boundary

This note describes the current `flock.api` implementation. The useful
distinction is between the process that continuously serves HTTP, handlers that
run for one request, and SSE response generators that remain alive only while a
particular client connection is open.

## The continuously running server

The continuously running component is the `python -m flock.api` process:

- `src/flock/api/__main__.py` is the executable entry point. `main()` loads and
  validates `Settings`, adds uvicorn TLS arguments when both certificate paths
  are configured, constructs the FastAPI application, and calls
  `uvicorn.run()`.
- `uvicorn.run()` owns the server lifecycle and HTTP event loop. There is no
  API-owned polling or reconciliation loop beside it.
- `create_app()` in `src/flock/api/app.py` constructs the long-lived FastAPI
  application, Redis client, bearer-token dependency, optional CORS middleware,
  generated-documentation routes, and business routes. The returned app and
  its Redis client live for the server process, but `create_app()` itself is a
  factory call, not a loop.

Most route handlers registered by `create_app()` are ordinary per-request
work. They validate the path and body, perform bounded Redis operations or call
the bus send door, build one response, and return. This includes health, agent
and roster reads, envelope submission, mailbox and activity catch-up reads,
board reads, alert reads, and the generated documentation providers.

## Connection-lived streaming work

The three SSE routes are neither process daemons nor ordinary finite reads:

- `GET /agents/{agent}/messages/stream`
- `GET /agents/{agent}/activity/stream`
- `GET /alerts/stream`

Each calls `_stream_response()`, which creates an asynchronous
`event_generator()` for that response. The generator repeatedly checks whether
its request disconnected, runs one bounded Redis stream read in a worker
thread, emits available events, and sleeps briefly when none exist. It ends on
disconnect or after emitting an error event.

These are continuous loops from one client's perspective, but they do not own
an independent process lifecycle: uvicorn schedules one generator per open SSE
response, and closing that response removes the loop. There is no shared
subscriber, fan-out worker, or background stream reader.

## Current package structure

`src/flock/api/__main__.py` is process bootstrap. It translates validated API
settings into the `uvicorn.run()` call, including TLS configuration.

`src/flock/api/__init__.py` is only the public import boundary. It exports
`Settings` and `create_app` and adds no runtime behavior.

`src/flock/api/app.py` currently contains almost every other concern:

- `Settings`, `Settings.from_env()`, and `Settings.validate()` own environment
  loading for token, bind, TLS, publication, and CORS, plus startup safety
  rules for the required token and non-loopback TLS exposure.
- `_plaintext_allowed()` and `_is_loopback()` support exposure validation.
- `_decode()` and `_decode_entry()` adapt Redis values and backward-compatible
  board entries.
- `_canonical_envelope()` and `_verify_client_signature()` implement the
  published-door per-client HMAC check for a declared `as` identity.
- `_validate_attachment_payload()` implements the one kind-specific admission
  exception, including schema, filename, MIME type, base64, and size checks.
- `_render_restdoc_html()` contains the self-contained human documentation
  page, including REST and session-door material.
- `_read_stream_entries()` performs one bounded Redis Stream read and decodes
  valid JSON records while skipping corrupt entries.
- `_stream_response()` implements the connection-lived SSE polling adapter.
- `create_app()` wires authentication and CORS, then defines and registers all
  routes as nested functions.

The routes fall into four real groups:

- service and discovery: `/health`, `/agents`, and `/agents/{agent}`;
- bus ingress: `POST /agents/{agent}/envelopes`;
- client and observability streams: mailbox, activity, and alert catch-up/SSE
  routes;
- task state: one-agent and aggregate board reads.

Documentation endpoints are a fifth HTTP group, but not domain behavior:
`/openapi.json`, `/docs`, `/redoc`, and `/restdoc` expose schemas or prose for
the other routes.

## Things that do not fit cleanly

`_stream_response()` is active, potentially long-lived work inside an otherwise
request-driven module. Calling it a daemon would be misleading because its
lifetime and state belong to one response, but calling it a simple passive
helper hides its polling loop and repeated Redis/thread activity.

`create_app()` is a factory that also serves as the module's composition root,
route registry, and closure-based dependency container. Its nested route
functions are passive until uvicorn invokes them, while the objects they close
over are process-lived. This makes application lifetime and request lifetime
coexist in one large function.

`_render_restdoc_html()` is documentation generation embedded in executable
server code. It derives some route rows from the FastAPI app, but most prose,
examples, CSS, and the separate WebSocket session protocol are a large static
template. It is neither API mechanism nor domain policy, despite occupying much
of `app.py`.

Envelope submission crosses several ownership boundaries. The route owns HTTP
status mapping, roster admission, declared-client authentication, request-size
checks, and Attachment admission; `flock.bus.doors.send()` owns policy checks,
frame construction, and the egress write. The route is not merely a thin HTTP
wrapper, but moving all of it into the bus would incorrectly make HTTP identity
and status semantics bus concerns.

The read helpers intentionally tolerate some corrupt stored data. Stream reads
skip malformed records, aggregate boards skip invalid roster names, and blocked
state read failure falls back to presence. Those are provider-specific
availability policies, not generic Redis utilities.

## A cleaner split and vocabulary

With freedom to reorganize the module, I would keep one server process while
making its request-domain boundaries visible:

- `flock.api.main`: executable configuration and `uvicorn.run()`. This is the
  only process bootstrap.
- `flock.api.config.ApiSettings`: environment loading and startup validation.
  `Settings` is too broad outside its current small package.
- `flock.api.application.create_app`: the composition root only. It would
  create dependencies, install middleware, and include routers rather than
  define every handler in one closure.
- `flock.api.auth`: bearer authentication plus published-client HMAC
  verification. I would rename `_canonical_envelope()` to
  `canonical_signing_body()` and `_verify_client_signature()` to
  `verify_declared_client()` because the signature authenticates the `as`
  claim, not a wire envelope.
- `flock.api.routers.envelopes`: envelope POST admission and HTTP-to-bus error
  mapping. A small `resolve_http_destination()` helper would return the local
  membership name while retaining the original L3 destination.
- `flock.api.routers.agents`, `boards`, and `observability`: discovery/presence,
  task-board reads, and mailbox/activity/alert providers respectively.
- `flock.api.streams`: one-shot stream decoding and SSE response production. I
  would rename `_read_stream_entries()` to `read_json_stream_page()` and
  `_stream_response()` to `polling_sse_response()` so the Redis polling design
  is explicit.
- `flock.api.attachments`: `validate_attachment_payload()` and its limits. This
  keeps the deliberate kind-specific exception visible rather than burying it
  among generic HTTP helpers.
- `flock.api.restdoc`: route metadata and rendering, with the HTML/CSS template
  outside Python source where packaging permits it.

I would also replace closure access to the Redis client and settings with a
small typed `ApiContext` supplied through FastAPI dependencies. That would make
process-lived dependencies explicit without turning each router into a class.

The central boundary would then be: `main` owns the server process;
`application` assembles it; routers perform finite request work; `streams`
provides connection-lived polling responses; and bus, Redis, authentication,
attachment admission, and documentation remain separately named mechanisms.
