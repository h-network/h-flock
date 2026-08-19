"""Authoritative, destination-keyed forwarding table."""

from __future__ import annotations

from dataclasses import dataclass
import json

from redis.exceptions import WatchError

from .address import ALL_STATIONS, Address
from .errors import AddressInUse, PortNotDrained, PortStillAdmitting
from .keys import Keys
from .metrics import measured


@dataclass(frozen=True, slots=True)
class Admission:
    allowed_sources: frozenset[Address] | None

    @classmethod
    def any_source(cls):
        return cls(None)

    @classmethod
    def only(cls, *sources: Address):
        return cls(frozenset(sources))

    def allows(self, source: Address) -> bool:
        return self.allowed_sources is None or source in self.allowed_sources


@dataclass(frozen=True, slots=True)
class Target:
    port: str
    generation: str
    address: Address


@dataclass(frozen=True, slots=True)
class Selection:
    outcome: str
    targets: tuple[Target, ...] = ()


class ForwardingTable:
    def __init__(self, r, keys: Keys):
        self.r = r
        self.keys = keys

    def bind(
        self,
        address: Address,
        port: str,
        generation: str,
        admission: Admission,
    ) -> None:
        if not address.qualified or address.is_group:
            raise ValueError("only a qualified unicast address can be bound")
        entry = _entry(address, port, generation, admission)
        meta_key = self.keys.port(port)
        ingress_key = self.keys.ingress(port)
        with self.r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(self.keys.bindings, meta_key, ingress_key)
                    raw_meta = pipe.hgetall(meta_key)
                    depth = pipe.llen(ingress_key)
                    if raw_meta:
                        meta = {_decode(k): _decode(v) for k, v in raw_meta.items()}
                        if meta.get("state") == "active":
                            raise PortStillAdmitting(port, depth)
                        raise RuntimeError(
                            f"port {port!r} already has metadata; use rebind"
                        )
                    if depth:
                        raise PortNotDrained(port, depth)
                    if pipe.hexists(self.keys.bindings, str(address)):
                        raise AddressInUse(str(address))
                    pipe.multi()
                    pipe.hset(self.keys.bindings, str(address), json.dumps(entry))
                    pipe.sadd(self.keys.ports, port)
                    pipe.hset(
                        meta_key,
                        mapping={
                            "state": "active",
                            "generation": generation,
                            "address": str(address),
                        },
                    )
                    pipe.execute()
                    return
                except (AddressInUse, PortNotDrained, PortStillAdmitting):
                    pipe.unwatch()
                    raise
                except WatchError:
                    continue

    def rebind(
        self,
        address: Address,
        port: str,
        generation: str,
        admission: Admission,
    ) -> int:
        """Atomically refuse unless admission stopped and ingress is drained.

        Watching ingress is load-bearing: a port principal retains direct
        RPUSH rights, so metadata state alone cannot prevent a write between
        the empty check and commit.
        """
        if not address.qualified or address.is_group:
            raise ValueError("only a qualified unicast address can be bound")
        entry = _entry(address, port, generation, admission)
        meta_key = self.keys.port(port)
        ingress_key = self.keys.ingress(port)
        with self.r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(self.keys.bindings, meta_key, ingress_key)
                    raw_meta = pipe.hgetall(meta_key)
                    meta = {_decode(k): _decode(v) for k, v in raw_meta.items()}
                    depth = pipe.llen(ingress_key)
                    if meta.get("state") == "active":
                        raise PortStillAdmitting(port, depth)
                    if depth:
                        raise PortNotDrained(port, depth)
                    previous = meta.get("address")
                    existing = pipe.hget(self.keys.bindings, str(address))
                    if existing is not None and str(address) != previous:
                        raise AddressInUse(str(address))
                    pipe.multi()
                    if previous:
                        pipe.hdel(self.keys.bindings, previous)
                    pipe.hset(self.keys.bindings, str(address), json.dumps(entry))
                    pipe.sadd(self.keys.ports, port)
                    pipe.hset(
                        meta_key,
                        mapping={
                            "state": "active",
                            "generation": generation,
                            "address": str(address),
                        },
                    )
                    pipe.execute()
                    return depth
                except (AddressInUse, PortNotDrained, PortStillAdmitting):
                    pipe.unwatch()
                    raise
                except WatchError:
                    continue

    def unbind(self, address: Address, generation: str) -> bool:
        raw = self.r.hget(self.keys.bindings, str(address))
        if raw is None:
            return False
        entry = json.loads(_decode(raw))
        if entry["generation"] != generation:
            return False
        port = entry["port"]
        pipe = self.r.pipeline(transaction=True)
        pipe.hdel(self.keys.bindings, str(address))
        pipe.hset(self.keys.port(port), "state", "closing")
        pipe.execute()
        return True

    def port_binding(self, port: str, *, timing=None) -> Target | None:
        raw_meta = measured(
            timing, "table", lambda: self.r.hgetall(self.keys.port(port))
        )
        meta = {_decode(k): _decode(v) for k, v in raw_meta.items()}
        if not meta or meta.get("state") not in {"active", "closing"}:
            return None
        return Target(port, meta["generation"], Address.parse(meta["address"], require_qualified=True))

    def select_egress(
        self, source_port: str, source: Address, destination: Address, *, timing=None
    ) -> Selection:
        if destination.domain != self.keys.domain:
            return Selection("unroutable")
        if destination.station == ALL_STATIONS:
            targets = []
            raw_ports = measured(
                timing, "table", lambda: self.r.smembers(self.keys.ports)
            )
            ports = sorted(_decode(port) for port in raw_ports)
            if not ports:
                return Selection("selected", ())
            pipe = self.r.pipeline(transaction=False)
            for port in ports:
                pipe.hgetall(self.keys.port(port))
            result = measured(timing, "table", pipe.execute)
            for port, raw_meta in zip(ports, result):
                meta = {_decode(k): _decode(v) for k, v in raw_meta.items()}
                if port == source_port or meta.get("state") != "active":
                    continue
                targets.append(
                    Target(
                        port,
                        meta["generation"],
                        Address.parse(meta["address"], require_qualified=True),
                    )
                )
            return Selection("selected", tuple(targets))
        raw = measured(
            timing,
            "table",
            lambda: self.r.hget(self.keys.bindings, str(destination)),
        )
        if raw is None:
            return Selection("unroutable")
        entry = json.loads(_decode(raw))
        allowed = entry["allowed"]
        if allowed is not None and str(source) not in allowed:
            return Selection("denied")
        raw_meta = measured(
            timing, "table", lambda: self.r.hgetall(self.keys.port(entry["port"]))
        )
        meta = {
            _decode(k): _decode(v)
            for k, v in raw_meta.items()
        }
        if meta.get("state") != "active" or meta.get("generation") != entry["generation"]:
            return Selection("target_detached")
        return Selection(
            "selected",
            (
                Target(
                    entry["port"],
                    entry["generation"],
                    Address.parse(entry["address"], require_qualified=True),
                ),
            ),
        )


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _entry(
    address: Address, port: str, generation: str, admission: Admission
) -> dict:
    return {
        "port": port,
        "generation": generation,
        "address": str(address),
        "allowed": (
            None
            if admission.allowed_sources is None
            else sorted(str(source) for source in admission.allowed_sources)
        ),
    }
