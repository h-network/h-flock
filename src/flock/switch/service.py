"""Forward tenant egress queues without interpreting payloads."""

import os
import signal
import subprocess
import time

import redis

from flock.bus import EnvelopeError, emit, is_member, log_record, members, prefix
from flock.bus.envelope import advance_hop, header_record_fields, parse_for_switch, stamp_source
from flock.bus.queues import admit_ingress
from .retention import RetentionTrimmer
from .windowlog import WindowLogTailer

# ⚠ activity, presence and verification are NOT here. They observe agents; the
# watchdog owns them. What is left runs on the forwarding thread because it is
# the switch's own housekeeping — the window spool it tails into its own stdout,
# and the queues it writes.


class Switch:
    def __init__(
        self,
        r,
        *,
        pod: str,
        tenant: str,
        poll_seconds: int = 5,
        ingress_max: int = 300,
    ):
        if ingress_max < 1:
            raise ValueError("ingress_max must be positive")
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.poll_seconds = poll_seconds
        self.ingress_max = ingress_max
        self._offset = 0

    def _agents(self) -> set[str]:
        return members(self.r, pod=self.pod, tenant=self.tenant)

    @staticmethod
    def _record_popped(raw, sender: str) -> None:
        """Record removal before validating the untrusted frame."""
        candidate = header_record_fields(raw)
        stream_id = candidate.get("stream_id")
        correlation_id = candidate.get("correlation_id")
        destination = candidate.get("destination")
        log_record(
            "switch",
            "popped",
            stream_id=stream_id if isinstance(stream_id, str) else None,
            correlation_id=correlation_id if isinstance(correlation_id, str) else None,
            source=sender,
            destination=destination if isinstance(destination, str) else None,
        )

    def _dead_letter_full(
        self, sender: str, destination: str, raw, envelope: dict, depth: int
    ) -> None:
        self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
        log_record(
            "switch",
            "dead_lettered",
            stream_id=envelope.get("stream_id"),
            correlation_id=envelope.get("correlation_id"),
            source=envelope.get("l2", {}).get("source"),
            destination=destination,
            reason=(
                f"ingress full for destination {destination!r}: "
                f"depth {depth} has reached INGRESS_MAX {self.ingress_max}"
            ),
        )

    def _admit(
        self, destinations: list[str], raw
    ) -> tuple[bool, str | None, int | None]:
        """Apply shared atomic admission with this switch's configured bound."""
        return admit_ingress(
            self.r,
            pod=self.pod,
            tenant=self.tenant,
            destinations=destinations,
            raw=raw,
            limit=self.ingress_max,
        )

    @staticmethod
    def _kick(agent: str, envelope: dict) -> None:
        try:
            subprocess.Popen(["flock.port", agent])
        except OSError as exc:
            log_record(
                "switch",
                "kick_unknown",
                stream_id=envelope.get("stream_id"),
                correlation_id=envelope.get("correlation_id"),
                source=envelope.get("l2", {}).get("source"),
                destination=agent,
                reason=f"port kick outcome UNKNOWN after {exc}",
            )
            return
        # Popen success proves only that the switch started a delivery attempt;
        # it does not claim that the child reached or popped the ingress queue.
        log_record(
            "switch",
            "kick_started",
            stream_id=envelope.get("stream_id"),
            correlation_id=envelope.get("correlation_id"),
            source=envelope.get("l2", {}).get("source"),
            destination=agent,
        )

    def step(self, timeout: float | None = None) -> bool:
        agents = sorted(self._agents())
        if not agents:
            delay = self.poll_seconds if timeout is None else timeout
            if delay > 0:
                time.sleep(delay)
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
        self._record_popped(raw, sender)
        try:
            envelope = parse_for_switch(raw)
        except EnvelopeError as exc:
            dead = prefix(self.pod, self.tenant, sender, "dead")
            self.r.rpush(dead, raw)
            emit("switch", "dead_lettered", {}, str(exc))
            return True
        # The forwarding decision reads L2 and the roster only. L3 rides through
        # untouched for a future switch; this local switch never parses it.
        claimed_producer = envelope["l2"]["source"]
        if claimed_producer != sender:
            # The popped queue is the ingress port and therefore the attribution
            # source of truth. Correct rather than reject: rejecting a mismatch
            # would let a raw queue writer destroy another participant's traffic.
            envelope["l2"]["source"] = sender
            raw = stamp_source(raw, sender)
        if claimed_producer != sender:
            emit(
                "switch",
                "source_stamped",
                envelope,
                reason=f"claimed source {claimed_producer!r} stamped from egress sender {sender!r}",
            )
        try:
            raw = advance_hop(raw, envelope)
        except EnvelopeError as exc:
            self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
            emit("switch", "dead_lettered", envelope, str(exc))
            return True
        if envelope["ttl"] == 0:
            self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
            emit("switch", "dead_lettered", envelope, "ttl expired at forward")
            return True
        destination = envelope["l2"]["destination"]
        if destination == "all":
            recipients = sorted(self._agents() - {sender})
            if not recipients:
                emit("switch", "forwarded", envelope, count=0)
                return True
            try:
                admitted, _, depth = self._admit(recipients, raw)
            except Exception as exc:
                emit(
                    "switch", "forward_unknown", envelope,
                    f"broadcast ingress write outcome UNKNOWN after {exc}",
                )
                raise
            if not admitted:
                self._dead_letter_full(sender, "all", raw, envelope, depth)
                return True
            emit("switch", "forwarded", envelope, count=len(recipients))
            for agent in recipients:
                self._kick(agent, envelope)
            return True
        if not is_member(self.r, pod=self.pod, tenant=self.tenant, agent=destination):
            self.r.rpush(prefix(self.pod, self.tenant, sender, "dead"), raw)
            emit("switch", "dead_lettered", envelope, "destination is not in tenant roster")
            return True
        try:
            admitted, _, depth = self._admit([destination], raw)
        except Exception as exc:
            emit(
                "switch", "forward_unknown", envelope,
                f"ingress write outcome UNKNOWN after {exc}",
            )
            raise
        if not admitted:
            self._dead_letter_full(sender, destination, raw, envelope, depth)
            return True
        emit("switch", "forwarded", envelope)
        self._kick(destination, envelope)
        return True

    def run(
        self,
        window_log_tailer: WindowLogTailer | None = None,
        retention_trimmer: RetentionTrimmer | None = None,
        maintenance_poll_seconds: float = 2.0,
    ) -> None:
        """Forward, with the switch's own housekeeping between blocking pops.

        ⚠ Each job gets its own try. One failing job used to take the other four
        down silently, and the record named only the exception class — from a
        five-job block that was close to undiagnosable.
        """
        next_maintenance = 0.0
        while True:
            now = time.monotonic()
            if now >= next_maintenance:
                agents = None
                if retention_trimmer is not None:
                    try:
                        agents = self._agents()
                        retention_trimmer.poll(agents)
                    except Exception as exc:
                        emit("switch", "error", {},
                             reason=f"retention pass failed: {type(exc).__name__}: {exc}")
                if window_log_tailer is not None:
                    try:
                        window_log_tailer.poll()
                    except Exception as exc:
                        emit("switch", "error", {},
                             reason=f"window log pass failed: {type(exc).__name__}: {exc}")
                next_maintenance = now + maintenance_poll_seconds
            timeout = min(self.poll_seconds, max(0.1, next_maintenance - time.monotonic()))
            self.step(timeout=timeout)


def main() -> None:
    # Let the kernel reap kicked ports. Without this the switch accumulates a
    # zombie per delivery under load: CPython only reaps children that have
    # already exited, at the top of the next Popen, so during a burst the
    # reaping lags the spawning. Measured at 65 zombies for a 100-envelope run,
    # and they persist at rest until traffic resumes.
    #
    # Safe here precisely because the kick is fire and forget (LLD-bus-and-switch
    # §3.3, rail 3): SIG_IGN makes wait()/poll() unusable, and we never call
    # them — we do not want a return code.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    switch = Switch(
        r,
        pod=os.environ["POD"],
        tenant=os.environ["TENANT"],
        poll_seconds=int(os.environ.get("ROSTER_POLL_SECONDS", "5")),
        ingress_max=int(os.environ.get("INGRESS_MAX", "300")),
    )
    # Config for the same reason ROSTER_POLL_SECONDS is: two offices can
    # legitimately trade feed latency against filesystem polling. A knob beside
    # an existing knob is consistency; a knob on its own would be speculation.
    switch.run(
        window_log_tailer=WindowLogTailer(
            r,
            pod=switch.pod,
            tenant=switch.tenant,
            max_bytes=int(os.environ.get("WINDOW_LOG_MAX_BYTES", str(8 * 1024 * 1024))),
        ),
        retention_trimmer=RetentionTrimmer(
            r,
            pod=switch.pod,
            tenant=switch.tenant,
            board_done_max=int(os.environ.get("BOARD_DONE_MAX", "500")),
            dead_max=int(os.environ.get("DEAD_MAX", "500")),
        ),
        maintenance_poll_seconds=float(os.environ.get("MAINTENANCE_POLL_SECONDS", "2")),
    )
