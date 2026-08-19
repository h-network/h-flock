"""The client-declared and fabric-attested header types."""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from .address import Address


@dataclass(frozen=True, slots=True)
class ClientHeader:
    version: int
    destination: Address
    packet_type: str
    flow: str | None = None


@dataclass(frozen=True, slots=True)
class FabricHeader:
    declared: ClientHeader
    source: Address
    packet_id: uuid.UUID
    arrived_ns: int
    hops: int = 0
