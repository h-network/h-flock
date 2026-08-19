"""Station-facing attachment, send and receive API."""

from __future__ import annotations

import hashlib
import time

from .address import Address
from .codec import DEFAULT_MTU, VERSION, decode_packet, encode_packet
from .errors import (
    CrossDomainUnsupported,
    MalformedAddress,
    PacketTooLarge,
    PortCongested,
    PortDetached,
    ReservedLabel,
    UnsupportedGroup,
)
from .events import EventSink
from .headers import ClientHeader, FabricHeader
from .ids import uuid7
from .packet import Packet
from .queue import EgressReader, IngressWriter
from .table import ForwardingTable


class Adapter:
    def __init__(
        self,
        *,
        ingress: IngressWriter,
        egress: EgressReader,
        table: ForwardingTable,
        sink: EventSink,
        address: Address,
        mtu: int = DEFAULT_MTU,
        packet_filter=None,
    ):
        self.ingress = ingress
        self.egress = egress
        self.table = table
        self.sink = sink
        self.address = address
        self.mtu = mtu
        self.packet_filter = packet_filter

    @classmethod
    def attach(
        cls,
        r,
        *,
        keys,
        port: str,
        address: Address,
        generation: str,
        ingress_limit: int,
        sink: EventSink,
        mtu: int = DEFAULT_MTU,
        packet_filter=None,
    ):
        table = ForwardingTable(r, keys)
        binding = table.port_binding(port)
        if binding is None or binding.generation != generation or binding.address != address:
            raise PortDetached(f"port {port!r} is not provisioned with that binding")
        return cls(
            ingress=IngressWriter(r, keys, port, generation, ingress_limit),
            egress=EgressReader(r, keys, port),
            table=table,
            sink=sink,
            address=address,
            mtu=mtu,
            packet_filter=packet_filter,
        )

    def send(
        self,
        destination: str | Address,
        packet_type: str,
        payload: bytes,
        flow: str | None = None,
    ):
        try:
            destination = Address.parse(str(destination), client=True)
        except MalformedAddress as exc:
            self.sink.emit("rejected_malformed_address", reason=str(exc))
            raise
        except ReservedLabel as exc:
            self.sink.emit("rejected_reserved_label", reason=str(exc))
            raise
        except UnsupportedGroup as exc:
            self.sink.emit("rejected_unsupported_group", reason=str(exc))
            raise
        destination = destination.qualify(self.address.domain)
        if destination.domain != self.address.domain:
            exc = CrossDomainUnsupported(str(destination))
            self.sink.emit(
                "rejected_cross_domain",
                destination=str(destination),
                reason=str(exc),
            )
            raise exc
        body = bytes(payload)
        if self.packet_filter is not None and not self.packet_filter(
            destination, packet_type, body
        ):
            seq = self.sink.next_seq()
            self.sink.emit("filtered", seq=seq, destination=str(destination))
            return None
        packet_id = uuid7()
        declared = ClientHeader(
            VERSION,
            destination,
            packet_type,
            flow if flow is not None else str(packet_id),
        )
        packet = Packet(
            FabricHeader(
                declared=declared,
                source=self.address,
                packet_id=packet_id,
                arrived_ns=time.time_ns(),
                hops=0,
            ),
            body,
        )
        try:
            raw = encode_packet(packet, mtu=self.mtu)
        except PacketTooLarge as exc:
            self.sink.emit(
                "rejected_packet_too_large",
                seq=self.sink.next_seq(),
                id=str(packet_id),
                source=str(self.address),
                destination=str(destination),
                reason=str(exc),
            )
            raise
        try:
            # Capture before the Redis call but emit only after it succeeds.
            # sent->popped therefore includes the append round trip and is an
            # upper bound, while preserving causal timestamp ordering.
            sent_mono = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
            _, hint_subscribers = self.ingress.append(raw)
        except PortCongested as exc:
            self.sink.emit(
                "rejected_port_congested",
                seq=self.sink.next_seq(),
                id=str(packet_id),
                source=str(self.address),
                destination=str(destination),
                reason=str(exc),
            )
            raise
        except PortDetached as exc:
            self.sink.emit(
                "rejected_port_detached",
                seq=self.sink.next_seq(),
                id=str(packet_id),
                source=str(self.address),
                destination=str(destination),
                reason=str(exc),
            )
            raise
        seq = self.sink.next_seq()
        hint_counters = self.sink.increment_counters(
            hints_published_total=1,
            hints_published_zero_subscribers_total=int(hint_subscribers == 0),
        )
        self.sink.emit(
            "sent",
            seq=seq,
            captured_mono_ns=sent_mono,
            id=str(packet_id),
            flow=declared.flow,
            source=str(self.address),
            destination=str(destination),
            body_sha256=hashlib.sha256(body).hexdigest(),
            **hint_counters,
        )
        return packet_id

    def receive(self, timeout: float | None = None) -> Packet | None:
        raw = self.egress.pop(0 if timeout is None else timeout)
        if raw is None:
            return None
        packet = decode_packet(raw)
        seq = self.sink.next_seq()
        self.sink.emit(
            "received",
            seq=seq,
            id=str(packet.header.packet_id),
            flow=packet.header.declared.flow,
            source=str(packet.header.source),
            destination=str(packet.header.declared.destination),
            target=str(self.address),
            body_sha256=hashlib.sha256(packet.payload).hexdigest(),
        )
        return packet

    def detach(self) -> bool:
        return bool(
            self.ingress.r.fcall(
                "hvab_detach",
                1,
                self.ingress.keys.port(self.ingress.port),
                self.ingress.generation,
            )
        )


def port_acl_rules(keys, port: str) -> tuple[str, ...]:
    """Least-privilege Redis 7.4.2 rules for a station container."""
    return (
        "reset",
        "on",
        "resetkeys",
        "resetchannels",
        "-@all",
        "+auth",
        "+ping",
        "+fcall",
        "+hget",
        "+hgetall",
        "+hset",
        "+get",
        "+llen",
        "+rpush",
        "+incrby",
        "+decrby",
        "+set",
        "+blpop",
        "+publish",
        f"~{keys.acl_pattern(port)}",
        f"&{keys.hint_channel(port)}",
        "-del",
        "-lpop",
        "-flushall",
        "-flushdb",
        "-config",
        "-acl",
        "-eval",
        "-evalsha",
        "-subscribe",
        "-psubscribe",
        "-function|load",
    )
