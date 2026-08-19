"""Redis keys. The hash tag keeps each domain's functions cluster-safe."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Keys:
    pod: str
    domain: str

    @property
    def tag(self) -> str:
        return f"{{{self.pod}:{self.domain}}}"

    @property
    def ports(self) -> str:
        return f"hvab:{self.tag}:ports"

    @property
    def bindings(self) -> str:
        return f"hvab:{self.tag}:bindings"

    @property
    def counters(self) -> str:
        return f"hvab:{self.tag}:counters"

    def port(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:meta"

    def ingress(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:ingress"

    def ingress_bytes(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:ingress-bytes"

    def egress(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:egress"

    def egress_bytes(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:egress-bytes"

    def hint_channel(self, port: str) -> str:
        return f"hvab:{self.tag}:hint:{port}"

    @property
    def hint_pattern(self) -> str:
        return f"hvab:{self.tag}:hint:*"

    def acl_pattern(self, port: str) -> str:
        return f"hvab:{self.tag}:port:{port}:*"
