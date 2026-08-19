"""Deterministic binary packet codec with an opaque-payload route peek."""

from __future__ import annotations

import struct
import uuid

from .address import Address
from .errors import MalformedPacket, PacketTooLarge, UnknownVersion
from .headers import ClientHeader, FabricHeader
from .packet import Packet


VERSION = 1
FABRIC_MAGIC = b"HVAB"
_FABRIC_PREFIX = struct.Struct(">4sHB16sQHI")
_CLIENT_PREFIX = struct.Struct(">BBHB")
DEFAULT_MTU = 1_048_576

__all__ = (
    "DEFAULT_MTU",
    "FABRIC_MAGIC",
    "MIN_PACKET_BYTES",
    "VERSION",
    "candidate_record_fields",
    "decode_client",
    "decode_packet",
    "encode_client",
    "encode_packet",
    "peek_route",
)


def _text(value: str, maximum: int, field: str) -> bytes:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MalformedPacket(f"{field} is not UTF-8 encodable") from exc
    if not encoded or len(encoded) > maximum:
        raise MalformedPacket(f"{field} length must be 1..{maximum}")
    return encoded


def encode_client(header: ClientHeader) -> bytes:
    if header.version != VERSION:
        raise UnknownVersion(str(header.version))
    destination = _text(str(header.destination), 127, "destination")
    packet_type = _text(header.packet_type, 65535, "type")
    flow = b"" if header.flow is None else _text(header.flow, 255, "flow")
    return b"".join(
        (
            _CLIENT_PREFIX.pack(
                header.version, len(destination), len(packet_type), len(flow)
            ),
            destination,
            packet_type,
            flow,
        )
    )


def decode_client(raw: bytes | memoryview) -> ClientHeader:
    view = memoryview(raw)
    if len(view) < _CLIENT_PREFIX.size:
        raise MalformedPacket("truncated client header")
    version, destination_len, type_len, flow_len = _CLIENT_PREFIX.unpack_from(view)
    if version != VERSION:
        raise UnknownVersion(str(version))
    end = _CLIENT_PREFIX.size + destination_len + type_len + flow_len
    if end != len(view):
        raise MalformedPacket("client header length mismatch")
    offset = _CLIENT_PREFIX.size
    try:
        destination_text = bytes(view[offset : offset + destination_len]).decode("utf-8")
        offset += destination_len
        packet_type = bytes(view[offset : offset + type_len]).decode("utf-8")
        offset += type_len
        flow = bytes(view[offset:end]).decode("utf-8") if flow_len else None
    except UnicodeDecodeError as exc:
        raise MalformedPacket("client header contains invalid UTF-8") from exc
    return ClientHeader(
        version=version,
        destination=Address.parse(destination_text, require_qualified=True),
        packet_type=packet_type,
        flow=flow,
    )


def encode_packet(packet: Packet, *, mtu: int = DEFAULT_MTU) -> bytes:
    declared = encode_client(packet.header.declared)
    source = _text(str(packet.header.source), 127, "source")
    payload = bytes(packet.payload)
    prefix = _FABRIC_PREFIX.pack(
        FABRIC_MAGIC,
        len(declared),
        len(source),
        packet.header.packet_id.bytes,
        packet.header.arrived_ns,
        packet.header.hops,
        len(payload),
    )
    encoded = prefix + declared + source + payload
    if len(encoded) > mtu:
        raise PacketTooLarge(f"encoded packet is {len(encoded)} bytes; MTU is {mtu}")
    return encoded


def _parts(raw: bytes | memoryview):
    view = memoryview(raw)
    if len(view) < _FABRIC_PREFIX.size:
        raise MalformedPacket("truncated fabric packet")
    magic, declared_len, source_len, packet_id, arrived_ns, hops, payload_len = (
        _FABRIC_PREFIX.unpack_from(view)
    )
    if magic != FABRIC_MAGIC:
        raise MalformedPacket("unknown fabric packet magic")
    declared_start = _FABRIC_PREFIX.size
    source_start = declared_start + declared_len
    payload_start = source_start + source_len
    if payload_start + payload_len != len(view):
        raise MalformedPacket("fabric packet length mismatch")
    return (
        view,
        view[declared_start:source_start],
        view[source_start:payload_start],
        view[payload_start:],
        packet_id,
        arrived_ns,
        hops,
    )


def decode_packet(raw: bytes | memoryview) -> Packet:
    view, declared_raw, source_raw, payload, packet_id, arrived_ns, hops = _parts(raw)
    del view
    try:
        source_text = bytes(source_raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedPacket("source contains invalid UTF-8") from exc
    return Packet(
        header=FabricHeader(
            declared=decode_client(declared_raw),
            source=Address.parse(source_text, require_qualified=True),
            packet_id=uuid.UUID(bytes=packet_id),
            arrived_ns=arrived_ns,
            hops=hops,
        ),
        payload=bytes(payload),
    )


def peek_route(raw: bytes | memoryview) -> tuple[Address, Address]:
    _, declared_raw, source_raw, _, _, _, _ = _parts(raw)
    declared = decode_client(declared_raw)
    try:
        source_text = bytes(source_raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedPacket("source contains invalid UTF-8") from exc
    source = Address.parse(source_text, require_qualified=True)
    return source, declared.destination


def candidate_record_fields(raw: bytes | memoryview) -> dict:
    """Best-effort fields for the pre-validation ``popped`` record.

    Everything returned except the arrival port supplied by the caller remains
    attacker-controlled. Failure to recover a field is represented by ``None``;
    this function never raises for malformed bytes.
    """
    result = {"id": None, "flow": None, "claimed_destination": None}
    try:
        view = memoryview(raw)
        if len(view) < _FABRIC_PREFIX.size:
            return result
        _, declared_len, _, packet_id, _, _, _ = _FABRIC_PREFIX.unpack_from(view)
        result["id"] = str(uuid.UUID(bytes=packet_id))
        start = _FABRIC_PREFIX.size
        declared = view[start : start + declared_len]
        if len(declared) < _CLIENT_PREFIX.size:
            return result
        _, destination_len, type_len, flow_len = _CLIENT_PREFIX.unpack_from(declared)
        offset = _CLIENT_PREFIX.size
        result["claimed_destination"] = bytes(
            declared[offset : offset + destination_len]
        ).decode("utf-8", errors="replace")
        offset += destination_len + type_len
        if flow_len:
            result["flow"] = bytes(declared[offset : offset + flow_len]).decode(
                "utf-8", errors="replace"
            )
    except Exception:
        pass
    return result


# Compute the lower bound through the production encoder. Any structural
# change to either header format therefore changes the watchdog tripwire with
# it instead of leaving a hand-maintained size literal behind.
MIN_PACKET_BYTES = len(
    encode_packet(
        Packet(
            FabricHeader(
                declared=ClientHeader(VERSION, Address.parse("a/a"), "a"),
                source=Address.parse("a/a"),
                packet_id=uuid.UUID(int=0),
                arrived_ns=0,
                hops=0,
            ),
            b"",
        )
    )
)
