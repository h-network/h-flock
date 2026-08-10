"""Authenticated WebSocket service for viewing and driving tenant terminals."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .control import ControlModeClient, ControlModeError, Subscriber


def _plaintext_allowed() -> bool:
    """Whether something outside this process has already judged the exposure.

    ⚠ A bind is not an exposure — inside a container both doors bind `0.0.0.0`
    by design and the port mapping that decides publication is invisible from
    here. The entrypoint judges it and sets this. See `flock.api.app` for the
    same helper and `LLD-container` §3 for why the judgement lives there.
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


@dataclass(frozen=True)
class SessionSettings:
    tenant: str
    api_token: str
    session_name: str
    session_bind: str = "127.0.0.1"
    session_port: int = 8081
    tmux_socket: str | None = None
    session_tls_cert: str | None = None
    session_tls_key: str | None = None

    @classmethod
    def from_env(cls) -> "SessionSettings":
        token = os.getenv("API_TOKEN")
        if not token:
            raise RuntimeError("API_TOKEN is required")
        tenant = os.environ["TENANT"]
        cert = os.getenv("SESSION_TLS_CERT") or os.getenv("API_TLS_CERT") or None
        key = os.getenv("SESSION_TLS_KEY") or os.getenv("API_TLS_KEY") or None
        return cls(
            tenant=tenant,
            api_token=token,
            session_name=os.getenv("TMUX_SESSION", tenant),
            session_bind=os.getenv("SESSION_BIND", "127.0.0.1"),
            session_port=int(os.getenv("SESSION_PORT", "8081")),
            tmux_socket=os.getenv("TMUX_SOCKET") or None,
            session_tls_cert=cert,
            session_tls_key=key,
        )

    def validate(self) -> None:
        if not self.api_token:
            if not _is_loopback(self.session_bind):
                raise RuntimeError("API_TOKEN is required when SESSION_BIND is not loopback")
            raise RuntimeError("API_TOKEN is required")
        if not _is_loopback(self.session_bind) and not _plaintext_allowed():
            if not (self.session_tls_cert and self.session_tls_key):
                raise RuntimeError("SESSION_TLS_CERT and SESSION_TLS_KEY are required when SESSION_BIND is not loopback")
        if bool(self.session_tls_cert) != bool(self.session_tls_key):
            raise RuntimeError("Both SESSION_TLS_CERT and SESSION_TLS_KEY must be provided for TLS")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _authorized(websocket: WebSocket, token: str) -> bool:
    authorization = websocket.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and credential
        and hmac.compare_digest(credential, token)
    )


def _connection_log(
    connection_id: str,
    client: str,
    agents: set[str],
    mode: str | None,
    connected_at: str,
) -> None:
    print(
        json.dumps(
            {
                "ts": _now(),
                "module": "session",
                "event": "closed",
                "connection_id": connection_id,
                "client": client,
                "agents": sorted(agents),
                "mode": mode or "unselected",
                "connected_at": connected_at,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def create_app(
    *,
    settings: SessionSettings | None = None,
    controller: ControlModeClient | None = None,
) -> FastAPI:
    settings = settings or SessionSettings.from_env()
    settings.validate()
    controller = controller or ControlModeClient(settings.session_name, settings.tmux_socket)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await controller.start()
        app.state.controller = controller
        try:
            yield
        finally:
            await controller.stop()

    app = FastAPI(title="flock session", lifespan=lifespan)
    app.state.controller = controller
    app.state.settings = settings

    @app.websocket("/session")
    async def session_socket(websocket: WebSocket) -> None:
        if not _authorized(websocket, settings.api_token):
            await websocket.close(code=4401, reason="unauthorized")
            return
        await websocket.accept()
        subscriber = Subscriber()
        connection_id = uuid.uuid4().hex
        connected_at = _now()
        client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
        mode: str | None = None
        seen_agents: set[str] = set()

        async def forward_output() -> None:
            while True:
                event = await subscriber.queue.get()
                await websocket.send_json(event)
                if "error" in event:
                    await websocket.close(code=1011, reason=event["error"])
                    return

        forward_task = asyncio.create_task(forward_output())
        receive_task = asyncio.create_task(websocket.receive_json())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {forward_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if forward_task in done:
                    await forward_task
                    return
                message = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive_json())
                if not isinstance(message, dict):
                    await websocket.send_json({"error": "message must be an object"})
                    continue
                if "subscribe" in message:
                    requested_mode = message.get("mode", mode or "read-write")
                    if requested_mode not in {"read-only", "read-write"}:
                        await websocket.send_json({"error": "invalid mode"})
                        continue
                    if mode is not None and requested_mode != mode:
                        await websocket.send_json({"error": "mode cannot change"})
                        continue
                    requested = message["subscribe"]
                    if not isinstance(requested, list) or not all(
                        isinstance(agent, str) for agent in requested
                    ):
                        await websocket.send_json({"error": "subscribe must be a list of agents"})
                        continue
                    unknown = await controller.update_subscription(subscriber, set(requested))
                    if unknown:
                        await websocket.send_json({"error": "unknown agents", "agents": unknown})
                        continue
                    mode = requested_mode
                    seen_agents.update(requested)
                    continue
                if "agent" in message and "data" in message:
                    if mode == "read-only":
                        await websocket.send_json({"error": "read-only"})
                        continue
                    agent, data = message["agent"], message["data"]
                    if not isinstance(agent, str) or not isinstance(data, str):
                        await websocket.send_json({"error": "agent and data must be strings"})
                        continue
                    if agent not in subscriber.agents:
                        await websocket.send_json({"error": "agent is not subscribed"})
                        continue
                    try:
                        await controller.send_keys(agent, data)
                    except ControlModeError as exc:
                        await websocket.send_json({"error": str(exc)})
                    continue
                await websocket.send_json({"error": "unsupported message"})
        except WebSocketDisconnect:
            pass
        finally:
            controller.unsubscribe(subscriber)
            for task in (forward_task, receive_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(forward_task, receive_task, return_exceptions=True)
            _connection_log(connection_id, client, seen_agents, mode, connected_at)

    return app
