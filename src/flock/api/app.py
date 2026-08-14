import asyncio
import hmac
import ipaddress
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import redis
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from flock.bus.doors import send
from flock.bus.envelope import EnvelopeError
from flock.bus.keys import prefix
from flock.bus.roster import is_member, members, port_type


@dataclass(frozen=True)
class Settings:
    pod: str
    tenant: str
    redis_url: str = "redis://127.0.0.1:6379/0"
    api_token: str | None = None
    api_bind: str = "127.0.0.1"
    api_port: int = 8080
    api_tls_cert: str | None = None
    api_tls_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            pod=os.environ["POD"],
            tenant=os.environ["TENANT"],
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            api_token=os.getenv("API_TOKEN") or None,
            api_bind=os.getenv("API_BIND", "127.0.0.1"),
            api_port=int(os.getenv("API_PORT", "8080")),
            api_tls_cert=os.getenv("API_TLS_CERT") or None,
            api_tls_key=os.getenv("API_TLS_KEY") or None,
        )

    def validate(self) -> None:
        if not self.api_token:
            if not _is_loopback(self.api_bind):
                raise RuntimeError("API_TOKEN is required when API_BIND is not loopback")
            raise RuntimeError("API_TOKEN is required")
        if not _is_loopback(self.api_bind) and not _plaintext_allowed():
            if not (self.api_tls_cert and self.api_tls_key):
                raise RuntimeError("API_TLS_CERT and API_TLS_KEY are required when API_BIND is not loopback")
        if bool(self.api_tls_cert) != bool(self.api_tls_key):
            raise RuntimeError("Both API_TLS_CERT and API_TLS_KEY must be provided for TLS")


def _plaintext_allowed() -> bool:
    """Whether something outside this process has already judged the exposure.

    ⚠ A bind is not an exposure. Inside a container the doors bind `0.0.0.0` by
    design (`Dockerfile`) — publishing is the deliberate act, and the port
    mapping that decides it is invisible from in here. So the entrypoint judges
    publication and sets this when plaintext cannot leave the host, or when the
    operator has acknowledged that it can. Outside a container nobody has
    judged anything and the bind is the exposure, which is why the default is
    to refuse. See `LLD-container` §3.
    """
    return os.getenv("FLOCK_ALLOW_PLAINTEXT") == "1"


def _is_loopback(bind: str) -> bool:
    host = bind.strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _decode(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


def _decode_entry(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _render_restdoc_html(app: FastAPI) -> str:
    path_meta = {
        "/health": {
            "desc": "Liveness check. Returns status ok.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/health',
        },
        "/agents": {
            "desc": "List all enrolled agents from the tenant roster.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/agents',
        },
        "/agents/{agent}": {
            "desc": "Get queue depths and presence state (working, idle, unknown, blocked) for an agent.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/agents/sme-2',
        },
        "/agents/{agent}/envelopes": {
            "desc": "Post an envelope of any kind to a specific agent or broadcast to 'all'. Accepts standard envelope shape, sugar `{\"text\": \"...\"}` for Message, and optional `\"as\"` for api client source identity.",
            "curl": 'curl -X POST -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" -d \'{"text": "hello", "as": "telegram"}\' http://localhost:8080/agents/sme-2/envelopes',
        },
        "/agents/{agent}/messages": {
            "desc": "Get stored inbox messages for an api client. Supports cursor catch-up (`?after=<cursor>`) and limit.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/agents/telegram/messages?after=1723150000000-0&limit=50"',
        },
        "/agents/{agent}/messages/stream": {
            "desc": "Live Server-Sent Events (SSE) stream of inbox messages for an api client. Supports cursor (`?after=<cursor>`).",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/agents/telegram/messages/stream"',
        },
        "/agents/{agent}/activity": {
            "desc": "Get stored activity feed events for an agent. Supports cursor catch-up (`?after=<cursor>`) and limit.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/agents/sme-2/activity?after=1723150000000-0&limit=50"',
        },
        "/agents/{agent}/activity/stream": {
            "desc": "Live Server-Sent Events (SSE) stream of activity events for an agent. Supports cursor (`?after=<cursor>`).",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/agents/sme-2/activity/stream"',
        },
        "/agents/{agent}/board": {
            "desc": "Get task board lists (todo, doing, hold, done) for a specific agent.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/agents/sme-2/board',
        },
        "/alerts": {
            "desc": "Get stored watchdog alert events across the tenant. Supports cursor catch-up (`?after=<cursor>`) and limit.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/alerts?after=1723150000000-0&limit=50"',
        },
        "/alerts/stream": {
            "desc": "Live Server-Sent Events (SSE) stream of watchdog alert events across the tenant. Supports cursor (`?after=<cursor>`).",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8080/alerts/stream"',
        },
        "/board": {
            "desc": "Get task boards for all enrolled agents across the tenant.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/board',
        },
        "/restdoc": {
            "desc": "Self-contained API and WebSocket documentation page.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/restdoc',
        },
        "/docs": {
            "desc": "Generated OpenAPI Swagger UI interactive documentation.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/docs',
        },
        "/redoc": {
            "desc": "Generated OpenAPI ReDoc documentation.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/redoc',
        },
        "/openapi.json": {
            "desc": "OpenAPI 3.0 schema specification JSON.",
            "curl": 'curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8080/openapi.json',
        },
    }

    routes_html = []
    seen = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(list(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}))
        if not path or not methods or (path, tuple(methods)) in seen:
            continue
        seen.add((path, tuple(methods)))
        method = methods[0]
        meta = path_meta.get(
            path,
            {
                "desc": getattr(route, "description", "")
                or getattr(route, "summary", "")
                or "API provider",
                "curl": f'curl -X {method} -H "Authorization: Bearer $API_TOKEN" http://localhost:8080{path}',
            },
        )
        badge_class = "badge-get" if method == "GET" else "badge-post"
        routes_html.append(
            f"""
        <div class="route-card" id="route-{path.replace('/', '-').strip('-')}">
          <div style="margin-bottom: 0.5rem;">
            <span class="badge {badge_class}">{method}</span>
            <code style="font-size: 1.1em; font-weight: 600; color: #38bdf8;">{path}</code>
          </div>
          <p style="margin: 0.5rem 0; color: #cbd5e1;">{meta['desc']}</p>
          <pre><code>{meta['curl']}</code></pre>
        </div>
        """
        )

    routes_rendered = "\n".join(routes_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>flock API &amp; Session Documentation</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --code-bg: #090d16;
      --method-get: #16a34a;
      --method-post: #2563eb;
      --warning-bg: #451a03;
      --warning-border: #b45309;
      --warning-text: #fde68a;
    }}
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.6;
      margin: 0;
      padding: 2rem;
    }}
    .container {{
      max-width: 960px;
      margin: 0 auto;
    }}
    h1, h2, h3 {{
      color: var(--text);
      font-weight: 600;
    }}
    h1 {{
      font-size: 2.25rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
    }}
    h2 {{
      font-size: 1.5rem;
      margin-top: 2.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
    }}
    .auth-banner {{
      background: #1e1b4b;
      border: 1px solid #4338ca;
      padding: 1rem 1.25rem;
      border-radius: 8px;
      margin-bottom: 2rem;
    }}
    .warning-box {{
      background: var(--warning-bg);
      border: 1px solid var(--warning-border);
      color: var(--warning-text);
      padding: 1rem 1.25rem;
      border-radius: 8px;
      margin: 1.25rem 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
    }}
    th, td {{
      text-align: left;
      padding: 0.75rem;
      border: 1px solid var(--border);
    }}
    th {{
      background: #1e293b;
      color: #38bdf8;
    }}
    .badge {{
      display: inline-block;
      padding: 0.25rem 0.5rem;
      font-weight: bold;
      font-size: 0.85rem;
      border-radius: 4px;
      color: #fff;
    }}
    .badge-get {{ background: var(--method-get); }}
    .badge-post {{ background: var(--method-post); }}
    pre, code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      background: var(--code-bg);
      border-radius: 4px;
    }}
    code {{
      padding: 0.2rem 0.4rem;
      font-size: 0.9em;
      color: #e2e8f0;
    }}
    pre {{
      padding: 1rem;
      overflow-x: auto;
      border: 1px solid var(--border);
      color: #f1f5f9;
    }}
    pre code {{
      padding: 0;
      background: transparent;
    }}
    .route-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>flock API &amp; Session Documentation</h1>

    <div class="auth-banner">
      <h3 style="margin-top:0; color:#818cf8;">Authentication Required</h3>
      <p style="margin-bottom:0;">
        Every HTTP REST provider and generated documentation route (<code>/restdoc</code>, <code>/docs</code>, <code>/redoc</code>, <code>/openapi.json</code>) requires a valid Bearer token header:
        <br><code>Authorization: Bearer &lt;API_TOKEN&gt;</code>
      </p>
    </div>

    <h2>1. REST Endpoints</h2>
    <p>Below are all providers currently registered on the API server (:8080), with working <code>curl</code> examples:</p>

    {routes_rendered}

    <h2>2. Envelope Kinds</h2>
    <p>Envelopes posted via <code>POST /agents/{{agent}}/envelopes</code> carry a <code>kind</code> and a <code>payload</code>.</p>

    <table>
      <thead>
        <tr>
          <th><code>kind</code></th>
          <th>Payload Shape</th>
          <th>Description &amp; Behavior</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>Message</code></td>
          <td><code>{{"text": "..."}}</code></td>
          <td>Pastes <code>[message from &lt;source&gt;] &lt;text&gt;</code> into the destination agent's terminal window.</td>
        </tr>
        <tr>
          <td><code>Command</code></td>
          <td><code>{{"text": "..."}}</code></td>
          <td>Pastes <code>&lt;text&gt;</code> bare into the window — <strong>it executes in the terminal</strong>.</td>
        </tr>
        <tr>
          <td><code>StartAgent</code></td>
          <td><code>{{"agent": "...", "cli": "claude"}}</code></td>
          <td>Enrols agent in roster, creates terminal window, and starts CLI (defaults to <code>claude</code>).</td>
        </tr>
        <tr>
          <td><code>StopAgent</code></td>
          <td><code>{{"agent": "..."}}</code></td>
          <td>Reverses all three: terminates CLI process, kills terminal window, and removes from roster.</td>
        </tr>
      </tbody>
    </table>

    <div class="warning-box">
      <strong>⚠ Notice: This list of kinds is current, not authoritative.</strong><br>
      The API server does NOT validate <code>kind</code> or <code>payload</code>. An unknown <code>kind</code> is accepted with HTTP <code>202 Accepted</code> and dead-letters at the far edge if unopenable. An application MUST NOT treat this list as a whitelist. Adding new kinds is a capability of ports and openers, not an API schema change.
    </div>

    <h2>3. Meaning of HTTP 202 Accepted</h2>
    <p>
      An HTTP <code>202 Accepted</code> response from <code>POST /agents/{{agent}}/envelopes</code> means the envelope was successfully validated structurally, assigned a <code>stream_id</code> and <code>correlation_id</code>, and written to Redis on the source's egress queue.
    </p>
    <p>
      It does <strong>NOT</strong> mean the envelope has been delivered to the destination or executed. Delivery is asynchronous: the switch moves envelopes from egress to destination ingress queues and kicks the corresponding port process. If delivery fails (e.g. unknown destination or opener failure), the envelope dead-letters asynchronously. To trace envelope progress, inspect log output using the returned <code>stream_id</code>.
    </p>

    <h2>4. Live Terminal Session Protocol</h2>
    <p>
      Live terminal streaming and driving takes place over a dedicated WebSocket service on port 8081 at <code>ws://&lt;host&gt;:8081/session</code>.
    </p>
    <ul>
      <li><strong>Authentication:</strong> Checked once on connection via <code>Authorization: Bearer &lt;API_TOKEN&gt;</code> header.</li>
      <li><strong>Terminal Geometry:</strong> Fixed at <strong>120×32</strong> layout. Clients may NOT resize windows.</li>
    </ul>

    <h3>WebSocket Message Shapes</h3>
    <table>
      <thead>
        <tr>
          <th>Direction</th>
          <th>JSON Payload Shape</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Client &rarr; Server</td>
          <td><code>{{"subscribe": ["architect", "sme-2"], "mode": "read-only" | "read-write"}}</code></td>
          <td>Subscribe to output from listed agents. Mode defaults to <code>read-write</code> if omitted.</td>
        </tr>
        <tr>
          <td>Client &rarr; Server</td>
          <td><code>{{"agent": "sme-2", "data": "&lt;keystrokes&gt;"}}</code></td>
          <td>Send keystrokes to agent's terminal window. Refused with error if mode is <code>read-only</code>.</td>
        </tr>
        <tr>
          <td>Server &rarr; Client</td>
          <td><code>{{"agent": "sme-2", "data": "&lt;output bytes&gt;"}}</code></td>
          <td>Terminal output stream bytes or initial scrollback snapshot.</td>
        </tr>
        <tr>
          <td>Server &rarr; Client</td>
          <td><code>{{"error": "&lt;reason&gt;"}}</code></td>
          <td>Error notification (e.g. <code>read-only</code>, unknown agent, or stream disconnect).</td>
        </tr>
      </tbody>
    </table>

    <p>
      <strong>Snapshot + Stream:</strong> Upon subscribing to an agent, the server first emits a <code>capture-pane</code> snapshot of current scrollback, followed by real-time <code>%output</code> terminal bytes.
    </p>
  </div>
</body>
</html>"""


def _read_stream_entries(
    client: Any,
    key: str,
    after: str | None,
    limit: int,
    preferred_field: str = "envelope",
) -> list[dict[str, Any]]:
    min_id = f"({after}" if after else "-"
    try:
        raw_entries = client.xrange(key, min=min_id, max="+", count=limit)
    except Exception as exc:
        if isinstance(exc, redis.exceptions.RedisError):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
        return []

    entries = []
    b_pref = preferred_field.encode()
    s_pref = preferred_field

    for entry_id, fields in raw_entries:
        cid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        raw_val = None
        if b_pref in fields:
            raw_val = fields[b_pref]
        elif s_pref in fields:
            raw_val = fields[s_pref]
        elif fields:
            raw_val = next(iter(fields.values()))
        if not raw_val:
            continue
        val_str = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)
        try:
            val_dict = json.loads(val_str)
        except (json.JSONDecodeError, TypeError):
            continue
        val_dict["cursor"] = cid
        entries.append(val_dict)
    return entries


def _stream_response(
    request: Request,
    client: Any,
    key: str,
    event_name: str,
    after: str | None,
    preferred_field: str,
) -> StreamingResponse:
    header_last_id = request.headers.get("last-event-id")
    cursor = after or header_last_id

    async def event_generator():
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                break
            try:
                entries = await asyncio.to_thread(
                    _read_stream_entries,
                    client, key, cursor, 100, preferred_field
                )
            except Exception as exc:
                err_detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                err_payload = json.dumps({"error": err_detail})
                yield f"event: error\ndata: {err_payload}\n\n"
                break
            if entries:
                for entry in entries:
                    cid = entry["cursor"]
                    cursor = cid
                    data_json = json.dumps(entry)
                    yield f"id: {cid}\nevent: {event_name}\ndata: {data_json}\n\n"
            else:
                await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def create_app(*, settings: Settings | None = None, redis_client: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    client = redis_client or redis.Redis.from_url(settings.redis_url)
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if settings.api_token is None:
            return
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not hmac.compare_digest(credentials.credentials, settings.api_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app = FastAPI(
        title="flock api",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(authorize)],
    )
    app.state.redis = client
    app.state.settings = settings

    @app.get("/openapi.json", include_in_schema=False)
    def openapi() -> Any:
        return get_openapi(title=app.title, version="0.1.0", routes=app.routes)

    @app.get("/docs", include_in_schema=False)
    def docs() -> Any:
        return get_swagger_ui_html(openapi_url="/openapi.json", title=app.title + " - Swagger UI")

    @app.get("/redoc", include_in_schema=False)
    def redoc() -> Any:
        return get_redoc_html(openapi_url="/openapi.json", title=app.title + " - ReDoc")

    @app.get("/restdoc", response_class=HTMLResponse, include_in_schema=False)
    def restdoc() -> HTMLResponse:
        return HTMLResponse(content=_render_restdoc_html(app))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def agents() -> dict[str, list[str]]:
        return {"agents": sorted(_decode(agent) for agent in members(client, pod=settings.pod, tenant=settings.tenant))}

    @app.get("/agents/{agent}")
    def agent_queues(agent: str) -> dict[str, Any]:
        try:
            ingress = prefix(settings.pod, settings.tenant, agent, "ingress")
            egress = prefix(settings.pod, settings.tenant, agent, "egress")
            dead = prefix(settings.pod, settings.tenant, agent, "dead")
            presence_key = prefix(settings.pod, settings.tenant, agent, "presence")
            blocked_key = prefix(settings.pod, settings.tenant, agent, "blocked")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc
        if not is_member(client, pod=settings.pod, tenant=settings.tenant, agent=agent):
            raise HTTPException(status_code=404, detail="unknown agent")
        raw_presence = client.hgetall(presence_key) or {}
        try:
            raw_blocked = client.hgetall(blocked_key) or None
        except Exception:
            raw_blocked = None
        presence_state = _decode(raw_presence.get(b"state") or raw_presence.get("state")) or "unknown"
        state = "blocked" if raw_blocked else presence_state
        since = _decode(raw_presence.get(b"since") or raw_presence.get("since")) or ""
        last_activity = _decode(raw_presence.get(b"last_activity") or raw_presence.get("last_activity")) or ""
        agent_port_type = port_type(client, pod=settings.pod, tenant=settings.tenant, agent=agent)
        return {
            "agent": agent,
            "port_type": agent_port_type,
            "depths": {
                "ingress": client.llen(ingress),
                "egress": client.llen(egress),
                "dead": client.llen(dead),
            },
            "presence": {
                "state": state,
                "since": since,
                "last_activity": last_activity,
            },
        }

    @app.post("/agents/{agent}/envelopes", status_code=status.HTTP_202_ACCEPTED)
    def post_envelope(agent: str, envelope: dict[str, Any]) -> dict[str, str]:
        if agent != "all":
            try:
                prefix(settings.pod, settings.tenant, agent)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="invalid agent") from exc
            if not is_member(client, pod=settings.pod, tenant=settings.tenant, agent=agent):
                raise HTTPException(status_code=404, detail="unknown agent")
        source = "api"
        if "as" in envelope:
            as_client = envelope["as"]
            if not isinstance(as_client, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="invalid 'as' client: must be an enrolled client with port_type 'api'",
                )
            try:
                if port_type(client, pod=settings.pod, tenant=settings.tenant, agent=as_client) != "api":
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="invalid 'as' client: must be an enrolled client with port_type 'api'",
                    )
            except (KeyError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="invalid 'as' client: must be an enrolled client with port_type 'api'",
                ) from exc
            source = as_client
        try:
            payload_str = json.dumps(envelope)
        except (TypeError, ValueError):
            payload_str = ""
        if len(payload_str.encode("utf-8")) > 1_048_576:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="envelope payload exceeds maximum size limit of 1MB",
            )
        if "text" in envelope and set(envelope) <= {"text", "as"}:
            kind = "Message"
            payload = {"text": envelope["text"]}
        else:
            kind = envelope.get("kind")
            payload = envelope.get("payload")
        correlation_id = uuid.uuid4().hex
        try:
            stream_id = send(
                client,
                pod=settings.pod,
                tenant=settings.tenant,
                source=source,
                destination=agent,
                kind=kind,
                payload=payload,
                correlation_id=correlation_id,
                module="api",
            )
        except EnvelopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"stream_id": stream_id, "correlation_id": correlation_id}

    @app.get("/agents/{agent}/messages")
    def get_messages(
        agent: str,
        after: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        if port_type(client, pod=settings.pod, tenant=settings.tenant, agent=agent) != "api":
            raise HTTPException(status_code=404, detail="invalid client agent")
        inbox_key = prefix(settings.pod, settings.tenant, agent, "inbox")
        messages = _read_stream_entries(client, inbox_key, after=after, limit=limit, preferred_field="envelope")
        next_cursor = messages[-1]["cursor"] if messages else after
        return {
            "agent": agent,
            "messages": messages,
            "next_cursor": next_cursor,
        }

    @app.get("/agents/{agent}/messages/stream", include_in_schema=False)
    async def stream_messages(
        agent: str,
        request: Request,
        after: str | None = None,
    ) -> StreamingResponse:
        if port_type(client, pod=settings.pod, tenant=settings.tenant, agent=agent) != "api":
            raise HTTPException(status_code=404, detail="invalid client agent")
        inbox_key = prefix(settings.pod, settings.tenant, agent, "inbox")
        return _stream_response(request, client, inbox_key, "message", after, "envelope")

    @app.get("/agents/{agent}/activity")
    def get_activity(
        agent: str,
        after: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            prefix(settings.pod, settings.tenant, agent)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc
        if not is_member(client, pod=settings.pod, tenant=settings.tenant, agent=agent):
            raise HTTPException(status_code=404, detail="unknown agent")
        activity_key = prefix(settings.pod, settings.tenant, agent, "activity")
        activity = _read_stream_entries(client, activity_key, after=after, limit=limit, preferred_field="event")
        next_cursor = activity[-1]["cursor"] if activity else after
        return {
            "agent": agent,
            "activity": activity,
            "next_cursor": next_cursor,
        }

    @app.get("/agents/{agent}/activity/stream", include_in_schema=False)
    async def stream_activity(
        agent: str,
        request: Request,
        after: str | None = None,
    ) -> StreamingResponse:
        try:
            prefix(settings.pod, settings.tenant, agent)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc
        if not is_member(client, pod=settings.pod, tenant=settings.tenant, agent=agent):
            raise HTTPException(status_code=404, detail="unknown agent")
        activity_key = prefix(settings.pod, settings.tenant, agent, "activity")
        return _stream_response(request, client, activity_key, "activity", after, "event")

    def board_keys(agent: str) -> tuple[str, str, str, str]:
        try:
            return tuple(
                prefix(settings.pod, settings.tenant, agent, f"tasks.{state}")
                for state in ("todo", "doing", "hold", "done")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc

    def board_response(agent: str, values: list[list[Any]]) -> dict[str, Any]:
        return {
            "agent": agent,
            "todo": [item for val in values[0] if (item := _decode_entry(val)) is not None],
            "doing": [item for val in values[1] if (item := _decode_entry(val)) is not None],
            "hold": [item for val in values[2] if (item := _decode_entry(val)) is not None],
            "done": [item for val in values[3] if (item := _decode_entry(val)) is not None],
        }

    @app.get("/agents/{agent}/board")
    def agent_board(agent: str) -> dict[str, Any]:
        keys = board_keys(agent)
        if not is_member(client, pod=settings.pod, tenant=settings.tenant, agent=agent):
            raise HTTPException(status_code=404, detail="unknown agent")
        return board_response(agent, [client.lrange(key, 0, -1) for key in keys])

    @app.get("/board")
    def all_boards() -> dict[str, list[dict[str, Any]]]:
        agents = sorted(_decode(agent) for agent in members(client, pod=settings.pod, tenant=settings.tenant))
        valid_agents = []
        pipeline = client.pipeline(transaction=False)
        for agent in agents:
            try:
                keys = board_keys(agent)
            except HTTPException:
                continue
            valid_agents.append(agent)
            for key in keys:
                pipeline.lrange(key, 0, -1)
        boards = pipeline.execute() if valid_agents else []
        return {
            "agents": [
                board_response(agent, boards[index : index + 4])
                for index, agent in zip(range(0, len(boards), 4), valid_agents)
            ]
        }

    @app.get("/alerts")
    def get_alerts(
        after: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        alerts_key = prefix(settings.pod, settings.tenant, resource="alerts")
        alerts = _read_stream_entries(client, alerts_key, after=after, limit=limit, preferred_field="alert")
        next_cursor = alerts[-1]["cursor"] if alerts else after
        return {
            "alerts": alerts,
            "next_cursor": next_cursor,
        }

    @app.get("/alerts/stream", include_in_schema=False)
    async def stream_alerts(
        request: Request,
        after: str | None = None,
    ) -> StreamingResponse:
        alerts_key = prefix(settings.pod, settings.tenant, resource="alerts")
        return _stream_response(request, client, alerts_key, "alert", after, "alert")

    return app
