"""Forward tenant egress queues without interpreting payloads."""

import os
import signal
import subprocess
import time

import redis

from flock.bus import EnvelopeError, emit, is_member, members, parse, prefix
from .activity import ActivityTailer
from .verification import DeliveryVerifier


class Router:
    def __init__(self, r, *, pod: str, tenant: str, poll_seconds: int = 5):
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.poll_seconds = poll_seconds
        self._offset = 0

    def _agents(self) -> set[str]:
        return members(self.r, pod=self.pod, tenant=self.tenant)

    @staticmethod
    def _kick(agent: str) -> None:
        try:
            subprocess.Popen(["flock.adapter", agent])
        except OSError as exc:
            emit("router", "error", {"recipient": agent}, reason=f"adapter kick failed: {exc}")

    def step(self, timeout: float | None = None) -> bool:
        agents = sorted(self._agents())
        if not agents:
            return False
        self._offset %= len(agents)
        agents = agents[self._offset :] + agents[: self._offset]
        self._offset = (self._offset + 1) % len(agents)
        keys = [prefix(self.pod, self.tenant, agent, "egress") for agent in agents]
        item = self.r.blpop(keys, timeout=self.poll_seconds if timeout is None else timeout)
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
            recipients = sorted(self._agents() - {sender})
            pipe = self.r.pipeline()
            for agent in recipients:
                pipe.rpush(prefix(self.pod, self.tenant, agent, "ingress"), raw)
            pipe.execute()
            emit("router", "forwarded", envelope, count=len(recipients))
            for agent in recipients:
                self._kick(agent)
            return True
        if not is_member(self.r, pod=self.pod, tenant=self.tenant, agent=recipient):
            self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
            emit("router", "dead_lettered", envelope, "recipient is not in tenant roster")
            return True
        self.r.rpush(prefix(self.pod, self.tenant, recipient, "ingress"), raw)
        emit("router", "forwarded", envelope)
        self._kick(recipient)
        return True

    def run(
        self,
        activity_tailer: ActivityTailer | None = None,
        activity_poll_seconds: float = 2.0,
        delivery_verifier: DeliveryVerifier | None = None,
    ) -> None:
        next_activity = 0.0
        while True:
            now = time.monotonic()
            if activity_tailer is not None and now >= next_activity:
                try:
                    agents = self._agents()
                    activity_tailer.poll(agents)
                    if delivery_verifier is not None:
                        delivery_verifier.poll(agents)
                except Exception as exc:
                    emit("router", "error", {}, reason=f"activity/verification pass failed: {type(exc).__name__}")
                next_activity = now + activity_poll_seconds
            timeout = self.poll_seconds
            if activity_tailer is not None:
                timeout = min(timeout, max(0.1, next_activity - time.monotonic()))
            self.step(timeout=timeout)


def main() -> None:
    # Let the kernel reap kicked adapters. Without this the router accumulates a
    # zombie per delivery under load: CPython only reaps children that have
    # already exited, at the top of the next Popen, so during a burst the
    # reaping lags the spawning. Measured at 65 zombies for a 100-envelope run,
    # and they persist at rest until traffic resumes.
    #
    # Safe here precisely because the kick is fire and forget (LLD-bus-and-router
    # §3.3, rail 3): SIG_IGN makes wait()/poll() unusable, and we never call
    # them — we do not want a return code.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    router = Router(
        r,
        pod=os.environ["POD"],
        tenant=os.environ["TENANT"],
        poll_seconds=int(os.environ.get("ROSTER_POLL_SECONDS", "5")),
    )
    # Config for the same reason ROSTER_POLL_SECONDS is: two offices can
    # legitimately trade feed latency against filesystem polling. A knob beside
    # an existing knob is consistency; a knob on its own would be speculation.
    router.run(
        ActivityTailer(r, pod=router.pod, tenant=router.tenant),
        activity_poll_seconds=float(os.environ.get("ACTIVITY_POLL_SECONDS", "2")),
        delivery_verifier=DeliveryVerifier(
            r,
            pod=router.pod,
            tenant=router.tenant,
            verify_after_seconds=float(os.environ.get("VERIFY_AFTER_SECONDS", "10")),
        ),
    )
