"""Forward tenant egress queues without interpreting payloads."""

import os

import redis

from flock.bus import EnvelopeError, emit, members, parse, prefix


class Router:
    def __init__(self, r, *, pod: str, tenant: str, poll_seconds: int = 5):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.poll_seconds = poll_seconds
        self._offset = 0

    def _agents(self) -> set[str]:
        return members(self.r, pod=self.pod, tenant=self.tenant) | {"api"}

    def step(self) -> bool:
        agents = sorted(self._agents())
        if not agents:
            return False
        self._offset %= len(agents)
        agents = agents[self._offset :] + agents[: self._offset]
        self._offset = (self._offset + 1) % len(agents)
        keys = [prefix(self.pod, self.tenant, agent, "egress") for agent in agents]
        item = self.r.blpop(keys, timeout=self.poll_seconds)
        if item is None:
            return False
        source_key, raw = item
        if isinstance(source_key, bytes):
            source_key = source_key.decode()
        sender = source_key.split(":")[-2]
        try:
            envelope = parse(raw)
        except EnvelopeError as exc:
            dead = prefix(self.pod, self.tenant, sender, "dead")
            self.r.rpush(dead, raw)
            emit("router", "popped", {}, str(exc))
            emit("router", "dead_lettered", {}, str(exc))
            return True
        emit("router", "popped", envelope)
        recipient = envelope["recipient"]
        if recipient == "all":
            recipients = sorted(self._agents() - {sender, "api"})
            pipe = self.r.pipeline()
            for agent in recipients:
                pipe.rpush(prefix(self.pod, self.tenant, agent, "ingress"), raw)
            pipe.execute()
            emit("router", "forwarded", envelope, count=len(recipients))
            return True
        if recipient not in self._agents():
            self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
            emit("router", "dead_lettered", envelope, "recipient is not in tenant roster")
            return True
        self.r.rpush(prefix(self.pod, self.tenant, recipient, "ingress"), raw)
        emit("router", "forwarded", envelope)
        return True

    def run(self) -> None:
        while True:
            self.step()


def main() -> None:
    Router(
        redis.Redis.from_url(os.environ["REDIS_URL"]),
        pod=os.environ["POD"],
        tenant=os.environ["TENANT"],
        poll_seconds=int(os.environ.get("ROSTER_POLL_SECONDS", "5")),
    ).run()
