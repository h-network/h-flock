"""Minimal sd_notify client suitable for a container-mounted notify socket."""

import os
import socket


def sd_notify(*lines: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    payload = "\n".join(line for line in lines if line).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.connect(address)
        client.sendall(payload)
    return True
