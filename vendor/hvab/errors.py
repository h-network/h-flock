"""Closed, machine-readable failures returned by the data plane."""


class HvabError(Exception):
    code = "hvab_error"
    retryable = False

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail or self.code)


class MalformedAddress(HvabError):
    code = "malformed_address"


class ReservedLabel(HvabError):
    code = "reserved_label"


class UnsupportedGroup(HvabError):
    code = "unsupported_group"


class UnknownVersion(HvabError):
    code = "unknown_version"


class MalformedPacket(HvabError):
    code = "malformed_packet"


class PacketTooLarge(HvabError):
    code = "packet_too_large"


class PortCongested(HvabError):
    code = "port_congested"
    retryable = True


class PortDetached(HvabError):
    code = "port_detached"


class PortStillAdmitting(HvabError):
    code = "port_still_admitting"

    def __init__(self, port: str, depth: int):
        self.port = port
        self.depth = depth
        super().__init__(f"port {port!r} is still admitting; observed depth={depth}")


class PortNotDrained(HvabError):
    code = "port_not_drained"
    retryable = True

    def __init__(self, port: str, depth: int):
        self.port = port
        self.depth = depth
        super().__init__(f"port {port!r} is not drained; observed depth={depth}")


class AddressInUse(HvabError):
    code = "address_in_use"


class CrossDomainUnsupported(HvabError):
    code = "cross_domain_unsupported"
