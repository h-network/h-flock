"""Append-only custody records with clocks suitable for stage deltas."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import uuid


EVENTS = frozenset(
    {
        # Process lifecycle.
        "started",
        "heartbeat",
        "stopped",
        # Adapter admission and custody.
        "filtered",
        "sent",
        "rejected_unknown_version",
        "rejected_forged_field",
        "rejected_malformed_address",
        "rejected_reserved_label",
        "rejected_unsupported_group",
        "rejected_packet_too_large",
        "rejected_port_congested",
        "rejected_port_detached",
        "rejected_cross_domain",
        # Administrative binding decision.
        "rebind_completed",
        "rebind_refused",
        # Switch outcomes.
        "popped",
        "dropped_malformed",
        "dropped_unbound_port",
        "dropped_source_mismatch",
        "dropped_unroutable",
        "denied",
        "target_detached",
        "egress_full",
        "forwarded",
        "route_lookup_failed",
        "egress_write_failed",
        # Lossy hint path. The sweep, not these events, guarantees progress.
        "hint_subscription_lost",
        "hint_subscribed",
        "hint_resubscribed",
        "hint_rate_limited",
        "sweep_batch_exhausted",
        # Delivery custody.
        "dispatched",
        "received",
        "opened",
        "handler_failed",
        "delivery_decode_failed",
        "delivery_store_failed",
    }
)
FATAL_EVENTS = frozenset(
    {
        "route_lookup_failed",
        "egress_write_failed",
    }
)
# A handover record is emitted only after its store commit succeeds, but its
# monotonic time is captured immediately before the call. The sender cannot
# observe the commit instant, and the receiver may act before the call returns.
# Every future store-backed process handover must use the same bracket.
HANDOVER_EVENTS = frozenset({"sent", "forwarded"})
# Counter values are cumulative since process start and mean nothing as raw
# absolutes. Consumers must subtract two heartbeats from the same instance and
# boot_id, then divide component deltas by the loop_wall_ns delta for shares.
# Never alert on a raw cumulative value: monotonic growth would eventually trip
# any threshold, while a cross-instance/boot delta spans a counter reset.
ADAPTER_COUNTERS = frozenset(
    {
        "hints_published_total",
        "hints_published_zero_subscribers_total",
    }
)
# Adapter counters ride on sent records because an in-process Adapter has no
# heartbeat loop. Bracket them with same-instance sent records (or started as a
# zero baseline); never compare their raw process totals with run-local counts.
SWITCH_COUNTERS = frozenset(
    {
        "heartbeats_total",
        "get_message_ns",
        "heartbeat_ns",
        "hint_channel_ns",
        "hint_enqueue_ns",
        "hint_forward_interval_ns",
        "hint_packets_serviced_total",
        "hint_pop_ns",
        "hint_service_ns",
        "hint_service_forward_ns",
        "hint_service_forward_unaccounted_ns",
        "hint_unaccounted_ns",
        "hints_received_total",
        "loop_unaccounted_ns",
        "loop_wall_ns",
        "packets_popped_total",
        "sweep_batch_exhausted_total",
        "sweep_enqueue_ns",
        "sweep_forward_interval_ns",
        "sweep_nonempty_ports_total",
        "sweep_packets_serviced_total",
        "sweep_pop_ns",
        "sweep_ports_scanned_total",
        "sweep_redis_round_trips_total",
        "sweep_scan_round_trips_total",
        "sweep_scan_ns",
        "sweep_service_ns",
        "sweep_service_unaccounted_ns",
        "sweeps_total",
        "sweep_ns",
        "sweep_unaccounted_ns",
    }
)
COUNTERS = ADAPTER_COUNTERS | SWITCH_COUNTERS
HEARTBEAT_FIELDS = frozenset(
    {
        "state",
        "last_store_error_class",
        "ports_observed",
    }
)
ENVELOPE_FIELDS = {
    "ts",
    "mono",
    "event",
    "pod",
    "domain",
    "component",
    "run_id",
    "instance",
    "rec",
    "seq",
    "boot_id",
    "host",
}


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


class EventSink:
    def __init__(
        self,
        root: str | os.PathLike,
        *,
        component: str,
        pod: str,
        domain: str,
        run_id: str | None = None,
    ):
        self.component = component
        self.pod = pod
        self.domain = domain
        self.run_id = run_id
        self.instance = str(uuid.uuid4())
        self.boot_id = _boot_id()
        self.host = socket.gethostname()
        self._sequence = 0
        self._record = 0
        self._counters = {name: 0 for name in COUNTERS}
        self._lock = threading.Lock()
        self._closed = False
        path = Path(root) / component
        path.mkdir(parents=True, exist_ok=True)
        self.path = path / f"{self.instance}.jsonl"
        self._stream = self.path.open("a", encoding="utf-8", buffering=1)
        self.emit("started")

    def increment_counters(self, **deltas: int) -> dict[str, int]:
        unknown = set(deltas).difference(COUNTERS)
        if unknown:
            raise ValueError(f"unknown counters: {', '.join(sorted(unknown))}")
        with self._lock:
            for name, delta in deltas.items():
                self._counters[name] += delta
            return {name: self._counters[name] for name in deltas}

    def next_seq(self) -> int:
        # seq belongs to the packet emitter and groups its outcomes. rec belongs
        # to this sink and proves record continuity. Neither replaces the other.
        with self._lock:
            self._sequence += 1
            return self._sequence

    def emit(
        self,
        event: str,
        *,
        seq: int | None = None,
        captured_mono_ns: int | None = None,
        **fields,
    ) -> dict:
        if event not in EVENTS:
            raise ValueError(f"unknown event name {event!r}")
        if captured_mono_ns is not None and event not in HANDOVER_EVENTS:
            raise ValueError(
                "a captured monotonic timestamp is valid only for a handover event"
            )
        collisions = ENVELOPE_FIELDS.intersection(fields)
        if collisions:
            names = ", ".join(sorted(collisions))
            raise ValueError(f"event fields collide with envelope: {names}")
        with self._lock:
            if self._closed:
                raise ValueError("event sink is closed")
            return self._emit_locked(event, seq, fields, captured_mono_ns)

    def _emit_locked(
        self,
        event: str,
        seq: int | None,
        fields: dict,
        captured_mono_ns: int | None = None,
    ) -> dict:
        self._record += 1
        record = {
            "ts": time.time_ns(),
            "mono": (
                captured_mono_ns
                if captured_mono_ns is not None
                else time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
            ),
            "event": event,
            "pod": self.pod,
            "domain": self.domain,
            "component": self.component,
            "instance": self.instance,
            "rec": self._record,
        }
        # run_id is a filter key, so it belongs on every member record. Absent
        # means "not part of a run" and never inherits a current/default run.
        # boot_id and host are metadata needed only on lifecycle probes.
        # Compose supplies "" when RUN_ID is unset. This truthiness check is
        # deliberate: `is not None` would turn that placeholder into a run and
        # defeat the reconciler's undeclared-run refusal.
        if self.run_id:
            record["run_id"] = self.run_id
        if seq is not None:
            record["seq"] = seq
        if event in {"started", "heartbeat"}:
            record["boot_id"] = self.boot_id
            record["host"] = self.host
        record.update(fields)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=True)
        if event in FATAL_EVENTS:
            print(line, file=sys.stderr, flush=True)
        try:
            self._stream.write(line + "\n")
            # flush survives process death, which is the fatal-path boundary.
            # fsync would cover host death at a per-record latency we reject.
            self._stream.flush()
        except (OSError, ValueError):
            if event not in FATAL_EVENTS:
                raise
            # The stderr copy already survived. Do not replace the forwarding
            # exception that supervision needs with a secondary sink failure,
            # including a file descriptor that was closed unexpectedly.
            pass
        return record

    def close(self, *, graceful: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            if graceful:
                self._emit_locked("stopped", None, {})
            self._closed = True
            self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.close(graceful=exc_type is None)
