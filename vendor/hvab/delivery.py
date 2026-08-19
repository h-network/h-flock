"""Long-lived, per-port delivery loop."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import time

from .codec import candidate_record_fields, decode_packet
from .errors import MalformedPacket, UnknownVersion
from .events import EventSink
from .notify import sd_notify
from .queue import EgressReader
from .store import StoreConfigurationError, classify_store_error, verify_store


class DeliveryService:
    def __init__(
        self,
        r,
        *,
        reader: EgressReader,
        sink: EventSink,
        target: str,
        handlers: dict[str, object] | None = None,
        block_timeout: float = 1.0,
    ):
        self.r = r
        self.reader = reader
        self.sink = sink
        self.target = target
        self.handlers = handlers or {}
        self.block_timeout = block_timeout
        self.state = "waiting_for_store"
        self.last_store_error_class = None
        self.counters = defaultdict(int)

    def _heartbeat(self) -> None:
        self.counters["heartbeats_total"] += 1
        self.sink.emit(
            "heartbeat",
            state=self.state,
            last_store_error_class=self.last_store_error_class,
            **dict(self.counters),
        )
        status = "serving" if self.state == "serving" else "waiting for store"
        sd_notify("WATCHDOG=1", f"STATUS={status}")

    def _wait_for_store(self) -> None:
        while True:
            try:
                # The switch principal verifies the deployment-wide eviction
                # policy. Port principals deliberately have no CONFIG rights.
                verify_store(self.r, require_noeviction=False)
            except StoreConfigurationError:
                raise
            except Exception as exc:
                self.state = "waiting_for_store"
                self.last_store_error_class = classify_store_error(exc)
                sd_notify("STATUS=waiting for store")
                self._heartbeat()
                time.sleep(self.block_timeout)
                continue
            self.state = "serving"
            self.last_store_error_class = None
            sd_notify("READY=1", "STATUS=serving")
            return

    def run(self, should_stop=lambda: False) -> None:
        self._wait_for_store()
        while not should_stop():
            try:
                raw = self.reader.wait_pop(self.block_timeout)
            except Exception as exc:
                self.state = "waiting_for_store"
                self.last_store_error_class = classify_store_error(exc)
                self._wait_for_store()
                continue
            if raw is None:
                self._heartbeat()
                continue
            seq = self.sink.next_seq()
            self.counters["packets_popped_total"] += 1
            try:
                self.reader.account(raw)
            except Exception as exc:
                self.sink.emit(
                    "delivery_store_failed",
                    seq=seq,
                    target=self.target,
                    reason=f"egress accounting failed: {exc}",
                )
                raise
            # Record the destructive pop before parsing untrusted bytes. These
            # best-effort header values remain claims; only target is supplied
            # by this delivery process's configured attachment.
            candidate = candidate_record_fields(raw)
            self.sink.emit("dispatched", seq=seq, target=self.target, **candidate)
            try:
                packet = decode_packet(raw)
            except (MalformedPacket, UnknownVersion) as exc:
                self.sink.emit(
                    "delivery_decode_failed",
                    seq=seq,
                    target=self.target,
                    reason=str(exc),
                )
                continue
            common = {
                "id": str(packet.header.packet_id),
                "flow": packet.header.declared.flow,
                "source": str(packet.header.source),
                "destination": str(packet.header.declared.destination),
                "target": self.target,
            }
            self.sink.emit(
                "received",
                seq=seq,
                **common,
                body_sha256=hashlib.sha256(packet.payload).hexdigest(),
            )
            handler = self.handlers.get(packet.header.declared.packet_type)
            if handler is None:
                self.sink.emit("opened", seq=seq, **common, handled=False)
                continue
            try:
                handler(packet)
            except Exception as exc:
                self.sink.emit(
                    "handler_failed",
                    seq=seq,
                    **common,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            else:
                self.sink.emit("opened", seq=seq, **common, handled=True)
