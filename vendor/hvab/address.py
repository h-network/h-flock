"""Qualified and client-facing address grammar."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import MalformedAddress, ReservedLabel, UnsupportedGroup


_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9]|[-.](?=[a-z0-9]))*$", re.ASCII)
_MAX_LABEL = 63
_MAX_QUALIFIED = 127
ALL_STATIONS = "all-stations"


def _validate_component(value: str, *, allow_reserved: bool) -> None:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise MalformedAddress("address labels must be ASCII") from exc
    if not encoded or len(encoded) > _MAX_LABEL:
        raise MalformedAddress("address labels must contain 1..63 bytes")
    label = value
    if value.startswith("_"):
        if not allow_reserved:
            raise ReservedLabel(f"client cannot name reserved label {value!r}")
        label = value[1:]
        if not label:
            raise MalformedAddress("reserved label requires a name after '_'")
    if not _LABEL.fullmatch(label):
        raise MalformedAddress(f"invalid address label {value!r}")


@dataclass(frozen=True, slots=True)
class Address:
    station: str
    domain: str | None = None

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        client: bool = False,
        require_qualified: bool = False,
    ) -> Address:
        if not isinstance(text, str):
            raise MalformedAddress("address must be text")
        parts = text.split("/")
        if len(parts) == 1:
            domain, station = None, parts[0]
        elif len(parts) == 2:
            domain, station = parts
        else:
            raise MalformedAddress("address contains more than one '/'")
        if require_qualified and domain is None:
            raise MalformedAddress("qualified address required")
        allow_reserved = not client
        _validate_component(station, allow_reserved=allow_reserved)
        if domain is not None:
            _validate_component(domain, allow_reserved=allow_reserved)
            if len(text.encode("ascii")) > _MAX_QUALIFIED:
                raise MalformedAddress("qualified address exceeds 127 bytes")
        if client and station.startswith("all-") and station != ALL_STATIONS:
            raise UnsupportedGroup(f"phase 1 supports only {ALL_STATIONS!r}")
        return cls(station=station, domain=domain)

    @property
    def qualified(self) -> bool:
        return self.domain is not None

    @property
    def is_group(self) -> bool:
        return self.station.startswith("all-")

    @property
    def is_reserved(self) -> bool:
        return self.station.startswith("_") or bool(
            self.domain and self.domain.startswith("_")
        )

    def qualify(self, domain: str) -> Address:
        if self.domain is not None:
            return self
        _validate_component(domain, allow_reserved=True)
        qualified = Address(station=self.station, domain=domain)
        if len(str(qualified).encode("ascii")) > _MAX_QUALIFIED:
            raise MalformedAddress("qualified address exceeds 127 bytes")
        return qualified

    def __str__(self) -> str:
        if self.domain is None:
            return self.station
        return f"{self.domain}/{self.station}"
