"""OpenShell port_type support: sandbox client wrapper and headless invocation.

Delivery (`flock.port`) and lifecycle (`flock.control`) wiring for
port_type: openshell are not implemented here yet — see
docs/LLD-port-openshell.md for status. This package currently holds only
the pieces that do not require a live gateway to build or test.
"""

from .client import OPENSHELL_GATEWAY_ENDPOINT_ENV, OpenShellClient, OpenShellUnavailable
from .headless import UNVERIFIED_HEADLESS_CLIS, headless_command

__all__ = [
    "OPENSHELL_GATEWAY_ENDPOINT_ENV",
    "OpenShellClient",
    "OpenShellUnavailable",
    "UNVERIFIED_HEADLESS_CLIS",
    "headless_command",
]
