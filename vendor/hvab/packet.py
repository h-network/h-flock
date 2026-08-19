"""The unit carried after the adapter accepts custody."""

from dataclasses import dataclass

from .headers import FabricHeader


@dataclass(frozen=True, slots=True)
class Packet:
    header: FabricHeader
    payload: bytes
