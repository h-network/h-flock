"""FastAPI application for a single running tenant."""

from __future__ import annotations

import hmac
import ipaddress
import os
import threading
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import redis
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from flock.bus.doors import receive, send
from flock.bus.keys import prefix
from flock.bus.logging import log_record
from flock.bus.roster import members

MAX_REPLY_CORRELATIONS = 1024
MAX_REPLIES_PER_CORRELATION = 100
RECEIVER_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class Settings:
    pod: str
    tenant: str
    redis_url: str = "redis://127.0.0.1:6379/0"
    api_token: str | None = None
    api_bind: str = "127.0.0.1"
    api_port: int = 8080

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            pod=os.environ["POD"],
            tenant=os.environ["TENANT"],
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            api_token=os.getenv("API_TOKEN") or None,
            api_bind=os.getenv("API_BIND", "127.0.0.1"),
            api_port=int(os.getenv("API_PORT", "8080")),
        )

    def validate(self) -> None:
        if not self.api_token:
            if not _is_loopback(self.api_bind):
                raise RuntimeError("API_TOKEN is required when API_BIND is not loopback")
            raise RuntimeError("API_TOKEN is required")


class MessageRequest(BaseModel):
    text: str


class ReplyStore:
    def __init__(
        self,
        max_correlations: int = MAX_REPLY_CORRELATIONS,
        max_replies_per_correlation: int = MAX_REPLIES_PER_CORRELATION,
    ) -> None:
        self._lock = threading.Lock()
        self._max_correlations = max_correlations
        self._max_replies_per_correlation = max_replies_per_correlation
        self._messages: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()

    def add(self, envelope: dict[str, Any]) -> None:
        correlation_id = envelope.get("correlation_id")
        if correlation_id:
            with self._lock:
                messages = self._messages.get(correlation_id)
                if messages is None:
                    messages = deque(maxlen=self._max_replies_per_correlation)
                    self._messages[correlation_id] = messages
                else:
                    self._messages.move_to_end(correlation_id)
                messages.append(envelope)
                while len(self._messages) > self._max_correlations:
                    self._messages.popitem(last=False)

    def get(self, correlation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._messages.get(correlation_id, ()))


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


def _receiver(
    client: Any,
    settings: Settings,
    replies: ReplyStore,
    stop: threading.Event,
    backoff_seconds: float = RECEIVER_BACKOFF_SECONDS,
) -> None:
    while not stop.is_set():
        try:
            receive(
                client,
                pod=settings.pod,
                tenant=settings.tenant,
                agent="api",
                openers={"Message": replies.add},
                timeout=1,
                module="api",
            )
        except Exception as exc:
            log_record("api", "receiver_error", reason=str(exc))
            stop.wait(backoff_seconds)


def create_app(*, settings: Settings | None = None, redis_client: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    client = redis_client or redis.Redis.from_url(settings.redis_url)
    replies = ReplyStore()
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        worker = threading.Thread(
            target=_receiver, args=(client, settings, replies, stop), daemon=True
        )
        worker.start()
        app.state.receiver_stop = stop
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=2)

    app = FastAPI(title="flock api", lifespan=lifespan, dependencies=[Depends(authorize)])
    app.state.redis = client
    app.state.settings = settings
    app.state.replies = replies

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
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc
        return {
            "agent": agent,
            "depths": {
                "ingress": client.llen(ingress),
                "egress": client.llen(egress),
                "dead": client.llen(dead),
            },
        }

    @app.post("/agents/{agent}/messages", status_code=status.HTTP_202_ACCEPTED)
    def post_message(agent: str, message: MessageRequest) -> dict[str, str]:
        correlation_id = uuid.uuid4().hex
        try:
            stream_id = send(
                client,
                pod=settings.pod,
                tenant=settings.tenant,
                producer="api",
                recipient=agent,
                payload={"text": message.text},
                correlation_id=correlation_id,
                module="api",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc
        return {"stream_id": stream_id, "correlation_id": correlation_id}

    def board_keys(agent: str) -> tuple[str, str, str]:
        try:
            return tuple(
                prefix(settings.pod, settings.tenant, agent, f"tasks.{state}")
                for state in ("todo", "doing", "done")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="invalid agent") from exc

    def board_response(agent: str, values: list[list[Any]]) -> dict[str, Any]:
        return {
            "agent": agent,
            "todo": [_decode(value) for value in values[0]],
            "doing": [_decode(value) for value in values[1]],
            "done": [_decode(value) for value in values[2]],
        }

    @app.get("/agents/{agent}/board")
    def agent_board(agent: str) -> dict[str, Any]:
        return board_response(agent, [client.lrange(key, 0, -1) for key in board_keys(agent)])

    @app.get("/board")
    def all_boards() -> dict[str, list[dict[str, Any]]]:
        agents = sorted(_decode(agent) for agent in members(client, pod=settings.pod, tenant=settings.tenant))
        pipeline = client.pipeline(transaction=False)
        for agent in agents:
            for key in board_keys(agent):
                pipeline.lrange(key, 0, -1)
        boards = pipeline.execute()
        return {
            "agents": [
                board_response(agent, boards[index : index + 3])
                for index, agent in zip(range(0, len(boards), 3), agents)
            ]
        }

    @app.get("/messages/{correlation_id}")
    def messages(correlation_id: str) -> dict[str, Any]:
        return {"correlation_id": correlation_id, "messages": replies.get(correlation_id)}

    return app
