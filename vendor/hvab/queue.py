"""Typed queue capabilities and Redis Function result handling."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PortCongested, PortDetached
from .keys import Keys
from .metrics import measured


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


@dataclass(frozen=True, slots=True)
class IngressWriter:
    """The only append capability exposed to an adapter.

    Source is attested to the container/Redis principal allowed to append this
    port, not to application code and not to a human identity. Container
    credential isolation is part of this property. It does not stop a station
    overfilling its own ingress by bypassing this function, publishing bogus
    hints on its own channel, or consuming Redis memory. Those are availability
    abuses, not attestation breaks.
    """

    r: object
    keys: Keys
    port: str
    generation: str
    byte_limit: int

    def append(self, raw: bytes) -> tuple[int, int]:
        result = self.r.fcall(
            "hvab_admit",
            3,
            self.keys.ingress(self.port),
            self.keys.ingress_bytes(self.port),
            self.keys.port(self.port),
            raw,
            self.port,
            self.generation,
            self.byte_limit,
            self.keys.hint_channel(self.port),
        )
        outcome = _text(result[0])
        if outcome == "DETACHED":
            raise PortDetached(self.port)
        if outcome == "FULL":
            raise PortCongested(f"port {self.port!r} ingress is full")
        if outcome != "OK":
            raise RuntimeError(f"unknown admission result {outcome!r}")
        return int(result[1]), int(result[2])


@dataclass(frozen=True, slots=True)
class SwitchQueueAccess:
    r: object
    keys: Keys

    def pop_ingress(self, port: str):
        result = self.r.fcall(
            "hvab_pop_ingress",
            2,
            self.keys.ingress(port),
            self.keys.ingress_bytes(port),
            port,
        )
        return result[0]

    def enqueue_egress(
        self,
        port: str,
        generation: str,
        raw: bytes,
        byte_limit: int,
        *,
        timing=None,
    ) -> int:
        result = measured(
            timing,
            "egress",
            lambda: self.r.fcall(
                "hvab_enqueue_egress",
                3,
                self.keys.egress(port),
                self.keys.egress_bytes(port),
                self.keys.port(port),
                raw,
                generation,
                byte_limit,
            ),
        )
        outcome = _text(result[0])
        if outcome == "DETACHED":
            raise PortDetached(port)
        if outcome == "FULL":
            raise PortCongested(f"port {port!r} egress is full")
        if outcome != "OK":
            raise RuntimeError(f"unknown egress result {outcome!r}")
        return int(result[1])


@dataclass(frozen=True, slots=True)
class EgressReader:
    r: object
    keys: Keys
    port: str

    def wait_pop(self, timeout: float):
        item = self.r.blpop(self.keys.egress(self.port), timeout=timeout)
        if item is None:
            return None
        return item[1]

    def account(self, raw: bytes) -> None:
        self.r.fcall(
            "hvab_account_egress_pop",
            1,
            self.keys.egress_bytes(self.port),
            len(raw),
        )

    def pop(self, timeout: float):
        raw = self.wait_pop(timeout)
        if raw is None:
            return None
        self.account(raw)
        return raw
