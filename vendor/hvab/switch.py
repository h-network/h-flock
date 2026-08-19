"""Byte-preserving forwarding and the single-domain acquisition loop."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import time

import redis

from .codec import candidate_record_fields, peek_route
from .errors import MalformedPacket, PortCongested, PortDetached, UnknownVersion
from .events import EventSink, SWITCH_COUNTERS
from .keys import Keys
from .metrics import PathTiming, StoreTiming
from .notify import sd_notify
from .queue import SwitchQueueAccess
from .store import StoreConfigurationError, classify_store_error, verify_store
from .table import ForwardingTable


class CustodyFailure(RuntimeError):
    """A failure after destructive packet pop; supervision must restart us."""


class Switch:
    def __init__(
        self,
        *,
        table: ForwardingTable,
        queues: SwitchQueueAccess,
        sink: EventSink,
        egress_limit: int,
        log_malformed_prefix: bool = False,
    ):
        self.table = table
        self.queues = queues
        self.sink = sink
        self.egress_limit = egress_limit
        self.log_malformed_prefix = log_malformed_prefix

    def forward(
        self, arrival_port: str, raw: bytes, *, path_timing: PathTiming | None = None
    ) -> bool:
        timing = StoreTiming(
            observer=None if path_timing is None else path_timing.observe_store
        )
        sink_ns = 0

        def emit_timed(event, **fields):
            nonlocal sink_ns
            rec = self.sink.emit(event, **fields)
            if "mono" in rec and fields.get("captured_mono_ns") is None:
                sink_ns += (
                    time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) - rec["mono"]
                )
            return rec

        seq = self.sink.next_seq()
        candidate = candidate_record_fields(raw)
        popped = emit_timed("popped", seq=seq, source=arrival_port, **candidate)
        if path_timing is not None:
            path_timing.popped_mono_ns = popped["mono"]
        try:
            claimed_source, destination = peek_route(raw)
        except (MalformedPacket, UnknownVersion) as exc:
            fields = {
                "source": arrival_port,
                "reason": str(exc),
                "length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if self.log_malformed_prefix:
                fields["header_prefix"] = raw[:64].hex()
            self.sink.emit("dropped_malformed", seq=seq, **fields)
            return False

        try:
            binding = self.table.port_binding(arrival_port, timing=timing)
        except Exception as exc:
            self.sink.emit(
                "route_lookup_failed",
                seq=seq,
                id=candidate["id"],
                source=str(claimed_source),
                destination=str(destination),
                targets=[],
                fanout=destination.is_group,
                target_count=0,
                reason=f"source binding lookup failed: {exc}",
            )
            raise
        if binding is None:
            self.sink.emit(
                "dropped_unbound_port",
                seq=seq,
                id=candidate["id"],
                claimed_source=str(claimed_source),
                source=arrival_port,
                destination=str(destination),
            )
            return False
        if binding.address != claimed_source:
            self.sink.emit(
                "dropped_source_mismatch",
                seq=seq,
                id=candidate["id"],
                claimed_source=str(claimed_source),
                attested_source=str(binding.address),
                source=arrival_port,
                destination=str(destination),
                reason="packet source does not match the arrival-port binding",
            )
            return False

        try:
            selection = self.table.select_egress(
                arrival_port, claimed_source, destination, timing=timing
            )
        except Exception as exc:
            self.sink.emit(
                "route_lookup_failed",
                seq=seq,
                id=candidate["id"],
                source=str(claimed_source),
                destination=str(destination),
                targets=[],
                fanout=destination.is_group,
                target_count=0,
                reason=f"route lookup failed: {exc}",
            )
            raise
        common = {
            "id": candidate["id"],
            "flow": candidate["flow"],
            "source": str(claimed_source),
            "destination": str(destination),
        }
        if selection.outcome == "denied":
            self.sink.emit("denied", seq=seq, **common)
            return False
        if selection.outcome == "unroutable":
            self.sink.emit("dropped_unroutable", seq=seq, **common)
            return False
        if selection.outcome == "target_detached":
            self.sink.emit(
                "target_detached", seq=seq, **common, target=str(destination)
            )
            return False

        count = len(selection.targets)
        if count == 0:
            forwarded_record = emit_timed(
                "forwarded",
                seq=seq,
                **common,
                target=None,
                count=0,
                total_store_ns_all_stages=timing.total_ns,
                store_round_trips=timing.round_trips,
                table_store_ns=timing.table_ns,
                egress_store_ns=timing.egress_ns,
                sink_ns=sink_ns,
            )
            if path_timing is not None:
                path_timing.observe_forwarded(forwarded_record["mono"])
            return True
        forwarded = False
        attempted = []
        for target in selection.targets:
            attempted.append(str(target.address))
            try:
                # The enqueue commit hands custody to a delivery process that
                # may act before FCALL returns. Capture before the call but
                # emit only on success; forwarded->dispatched is therefore an
                # upper bound that includes this measured egress round trip.
                forwarded_mono = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                self.queues.enqueue_egress(
                    target.port,
                    target.generation,
                    raw,
                    self.egress_limit,
                    timing=timing,
                )
            except PortDetached:
                self.sink.emit(
                    "target_detached",
                    seq=seq,
                    **common,
                    target=str(target.address),
                )
            except PortCongested:
                self.sink.emit(
                    "egress_full",
                    seq=seq,
                    **common,
                    target=str(target.address),
                )
            except Exception as exc:
                self.sink.emit(
                    "egress_write_failed",
                    seq=seq,
                    **common,
                    target=str(target.address),
                    targets=attempted,
                    fanout=destination.is_group,
                    target_count=count,
                    reason=f"egress write failed: {exc}",
                )
                raise
            else:
                forwarded = True
                forwarded_record = emit_timed(
                    "forwarded",
                    seq=seq,
                    captured_mono_ns=forwarded_mono,
                    **common,
                    target=str(target.address),
                    count=count,
                    total_store_ns_all_stages=timing.total_ns,
                    store_round_trips=timing.round_trips,
                    table_store_ns=timing.table_ns,
                    egress_store_ns=timing.egress_ns,
                    sink_ns=sink_ns,
                )
                if path_timing is not None:
                    path_timing.observe_forwarded(forwarded_record["mono"])
        return forwarded


class HintRateLimiter:
    def __init__(self, rate_per_second: float):
        self.minimum_interval = 0 if rate_per_second <= 0 else 1 / rate_per_second
        self.last = defaultdict(lambda: float("-inf"))
        self.last_event = defaultdict(lambda: float("-inf"))

    def accept(self, port: str, now: float) -> tuple[bool, bool]:
        if now - self.last[port] >= self.minimum_interval:
            self.last[port] = now
            return True, False
        report = now - self.last_event[port] >= 1.0
        if report:
            self.last_event[port] = now
        return False, report


class SwitchService:
    """Lossy hints lower latency; the unconditional sweep alone guarantees progress."""

    def __init__(
        self,
        r,
        *,
        keys: Keys,
        switch: Switch,
        sink: EventSink,
        block_timeout: float = 1.0,
        sweep_interval: float = 1.0,
        sweep_batch_per_port: int = 64,
        hint_rate_per_port: float = 1000.0,
    ):
        self.r = r
        self.keys = keys
        self.switch = switch
        self.sink = sink
        self.block_timeout = block_timeout
        self.sweep_interval = sweep_interval
        self.sweep_batch_per_port = sweep_batch_per_port
        self.rate_limiter = HintRateLimiter(hint_rate_per_port)
        self.pubsub = None
        self.state = "waiting_for_store"
        self.last_store_error_class = None
        self.counters = defaultdict(int)
        self.counters.update({name: 0 for name in SWITCH_COUNTERS})
        self._has_subscribed = False
        self._loop_started_ns = None

    @staticmethod
    def _mono_ns() -> int:
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)

    def _measure(self, counter: str, call):
        started = self._mono_ns()
        try:
            return call()
        finally:
            self.counters[counter] += self._mono_ns() - started

    def _timed_sweep(self) -> list[str]:
        before_scan = self.counters["sweep_scan_ns"]
        before_service = self.counters["sweep_service_ns"]
        before_whole = self.counters["sweep_ns"]
        ports = self._measure("sweep_ns", self.sweep)
        whole = self.counters["sweep_ns"] - before_whole
        parts = (
            self.counters["sweep_scan_ns"]
            - before_scan
            + self.counters["sweep_service_ns"]
            - before_service
        )
        # The whole and parts are measured independently. Preserve the sign:
        # a negative residual proves overlapping boundaries or broken timing.
        self.counters["sweep_unaccounted_ns"] += whole - parts
        return ports

    def _timed_hint(self, message) -> None:
        before_channel = self.counters["hint_channel_ns"]
        before_forward = self.counters["hint_service_forward_ns"]
        before_whole = self.counters["hint_service_ns"]
        self._measure("hint_service_ns", lambda: self._service_hint(message))
        whole = self.counters["hint_service_ns"] - before_whole
        parts = (
            self.counters["hint_channel_ns"]
            - before_channel
            + self.counters["hint_service_forward_ns"]
            - before_forward
        )
        self.counters["hint_unaccounted_ns"] += whole - parts

    def _timed_heartbeat(self, ports_observed=None) -> None:
        # This record reports completed heartbeat work. Its own sink duration
        # becomes visible on the next heartbeat; it cannot truthfully appear in
        # a record whose write has not completed yet.
        self._measure("heartbeat_ns", lambda: self._heartbeat(ports_observed))

    def _heartbeat(self, ports_observed: list[str] | None = None) -> None:
        self.counters["heartbeats_total"] += 1
        if self._loop_started_ns is not None:
            wall = self._mono_ns() - self._loop_started_ns
            accounted = sum(
                self.counters[name]
                for name in (
                    "get_message_ns",
                    "hint_service_ns",
                    "sweep_ns",
                    "heartbeat_ns",
                )
            )
            # Measure the whole independently from the parts. Never floor the
            # signed residual: negative proves overlap; positive is unmeasured
            # loop work. Both are findings.
            self.counters["loop_wall_ns"] = wall
            self.counters["loop_unaccounted_ns"] = wall - accounted
        self.sink.emit(
            "heartbeat",
            state=self.state,
            last_store_error_class=self.last_store_error_class,
            ports_observed=[] if ports_observed is None else ports_observed,
            **dict(self.counters),
        )
        status = "serving" if self.state == "serving" else "waiting for store"
        sd_notify("WATCHDOG=1", f"STATUS={status}")

    def _connect(self) -> list[str]:
        while True:
            try:
                verify_store(self.r)
                pubsub = self.r.pubsub(ignore_subscribe_messages=True)
                pubsub.psubscribe(self.keys.hint_pattern)
                self.pubsub = pubsub
                ports = self._timed_sweep()
            except StoreConfigurationError:
                raise
            except CustodyFailure:
                raise
            except Exception as exc:
                if not isinstance(exc, redis.RedisError):
                    raise
                self.state = "waiting_for_store"
                self.last_store_error_class = classify_store_error(exc)
                sd_notify("STATUS=waiting for store")
                self._timed_heartbeat()
                time.sleep(self.block_timeout)
                continue
            self.state = "serving"
            self.last_store_error_class = None
            event = "hint_resubscribed" if self._has_subscribed else "hint_subscribed"
            self.sink.emit(event, sweep_ran=True)
            self._has_subscribed = True
            sd_notify("READY=1", "STATUS=serving")
            self._timed_heartbeat(ports)
            return ports

    def _ports(self) -> list[str]:
        return sorted(
            value.decode() if isinstance(value, bytes) else str(value)
            for value in self.r.smembers(self.keys.ports)
        )

    def _service_port(
        self, port: str, limit: int = 1, *, timing: PathTiming | None = None
    ) -> int:
        serviced = 0
        for _ in range(limit):
            packet_timing = PathTiming()
            started = self._mono_ns()
            try:
                raw = self.switch.queues.pop_ingress(port)
            finally:
                packet_timing.pop_ns += self._mono_ns() - started
                packet_timing.store_round_trips += 1
            if raw is None:
                if timing is not None:
                    timing.absorb(packet_timing)
                break
            self.counters["packets_popped_total"] += 1
            try:
                self.switch.forward(port, raw, path_timing=packet_timing)
            except Exception as exc:
                raise CustodyFailure("forwarding failed with packet in custody") from exc
            finally:
                if timing is not None:
                    timing.absorb(packet_timing)
            serviced += 1
        return serviced

    def sweep(self) -> list[str]:
        """Run every tick: this is the sole correctness path, never an optimisation."""
        scan_started = self._mono_ns()
        ports = self._ports()
        scan_round_trips = 1
        pipe = self.r.pipeline(transaction=False)
        for port in ports:
            pipe.llen(self.keys.ingress(port))
        depths = pipe.execute() if ports else []
        if ports:
            scan_round_trips += 1
        self.counters["sweep_scan_ns"] += self._mono_ns() - scan_started
        self.counters["sweep_ports_scanned_total"] += len(ports)
        # Keep the scan-scoped count beside the scan itself. The aggregate
        # below also includes pop, table and enqueue calls and cannot answer
        # whether scan cost comes from trip count or per-trip latency.
        self.counters["sweep_scan_round_trips_total"] += scan_round_trips
        self.counters["sweep_redis_round_trips_total"] += scan_round_trips
        found = 0
        serviced_total = 0
        path = PathTiming()
        service_started = self._mono_ns()
        for port, depth in zip(ports, depths):
            if depth:
                found += 1
                serviced = self._service_port(
                    port, self.sweep_batch_per_port, timing=path
                )
                serviced_total += serviced
                if serviced == self.sweep_batch_per_port:
                    remaining = self.r.llen(self.keys.ingress(port))
                    path.store_round_trips += 1
                    if remaining:
                        self.counters["sweep_batch_exhausted_total"] += 1
                        self.sink.emit(
                            "sweep_batch_exhausted",
                            port=port,
                            batch_limit=self.sweep_batch_per_port,
                            remaining=remaining,
                        )
        service_elapsed = self._mono_ns() - service_started
        self.counters["sweep_service_ns"] += service_elapsed
        self.counters["sweeps_total"] += 1
        self.counters["sweep_nonempty_ports_total"] += found
        self.counters["sweep_packets_serviced_total"] += serviced_total
        self.counters["sweep_pop_ns"] += path.pop_ns
        self.counters["sweep_forward_interval_ns"] += path.forward_interval_ns
        self.counters["sweep_enqueue_ns"] += path.enqueue_ns
        self.counters["sweep_redis_round_trips_total"] += path.store_round_trips
        self.counters["sweep_service_unaccounted_ns"] += (
            service_elapsed
            - path.pop_ns
            - path.forward_interval_ns
            - path.enqueue_ns
        )
        return ports

    def _service_hint(self, message) -> None:
        channel_started = self._mono_ns()
        self.counters["hints_received_total"] += 1
        port = self._hint_port(message)
        accepted = report = False
        if port is not None:
            accepted, report = self.rate_limiter.accept(port, time.monotonic())
        if not accepted:
            if report:
                self.sink.emit("hint_rate_limited", port=port)
            self.counters["hint_channel_ns"] += self._mono_ns() - channel_started
            return
        self.counters["hint_channel_ns"] += self._mono_ns() - channel_started

        path = PathTiming()
        service_started = self._mono_ns()
        serviced = self._service_port(port, timing=path)
        service_elapsed = self._mono_ns() - service_started
        self.counters["hint_service_forward_ns"] += service_elapsed
        self.counters["hint_packets_serviced_total"] += serviced
        self.counters["hint_pop_ns"] += path.pop_ns
        self.counters["hint_forward_interval_ns"] += path.forward_interval_ns
        self.counters["hint_enqueue_ns"] += path.enqueue_ns
        self.counters["hint_service_forward_unaccounted_ns"] += (
            service_elapsed
            - path.pop_ns
            - path.forward_interval_ns
            - path.enqueue_ns
        )

    def _hint_port(self, message) -> str | None:
        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()
        prefix = self.keys.hint_pattern[:-1]
        if not isinstance(channel, str) or not channel.startswith(prefix):
            return None
        return channel[len(prefix) :]

    def run(self, should_stop=lambda: False) -> None:
        self._loop_started_ns = self._mono_ns()
        ports_observed = self._connect()
        now = time.monotonic()
        next_sweep = now + self.sweep_interval
        next_heartbeat = now + self.block_timeout
        while not should_stop():
            try:
                timeout = min(
                    self.block_timeout,
                    max(0.0, next_sweep - time.monotonic()),
                    max(0.0, next_heartbeat - time.monotonic()),
                )
                message = self._measure(
                    "get_message_ns",
                    lambda: self.pubsub.get_message(timeout=timeout),
                )
                if message is not None:
                    self._timed_hint(message)
                if time.monotonic() >= next_sweep:
                    ports_observed = self._timed_sweep()
                    next_sweep = time.monotonic() + self.sweep_interval
                if time.monotonic() >= next_heartbeat:
                    # Reuse the unconditional sweep's port-set read. This is
                    # the set this process actually observed, not a count.
                    self._timed_heartbeat(ports_observed)
                    next_heartbeat = time.monotonic() + self.block_timeout
            except CustodyFailure:
                raise
            except redis.RedisError as exc:
                self.sink.emit(
                    "hint_subscription_lost",
                    error_class=classify_store_error(exc),
                )
                if self.pubsub is not None:
                    self.pubsub.close()
                self.state = "waiting_for_store"
                self.last_store_error_class = classify_store_error(exc)
                ports_observed = self._connect()
                now = time.monotonic()
                next_sweep = now + self.sweep_interval
                next_heartbeat = now + self.block_timeout
