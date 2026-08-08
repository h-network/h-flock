"""FastAPI application for a single running tenant."""

from __future__ import annotations

import hmac
import ipaddress
import os
import uuid
from dataclasses import dataclass
from typing import Any

import redis
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from flock.bus.doors import send
from flock.bus.keys import prefix
from flock.bus.roster import members


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

    app = FastAPI(title="flock api", dependencies=[Depends(authorize)])
    app.state.redis = client
    app.state.settings = settings

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

    return app
