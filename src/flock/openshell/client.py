"""Thin wrapper around the real NVIDIA OpenShell SDK (`openshell.SandboxClient`).

Verified against `openshell` 0.0.116 (`SandboxClient.create/get/delete/exec`,
`SandboxRef`, `ExecResult`) — see docs/LLD-port-openshell.md. There is
deliberately no fake-success fallback anywhere in this module: every method
either reaches the real gateway through the SDK or raises
`OpenShellUnavailable`. A prior attempt at this integration shipped a
default path that fabricated "running" / exit code 0 whenever the gateway
was unreachable, and its test suite only ever exercised an injected mock,
never that default path — this module and its tests are built specifically
not to repeat that.
"""

from __future__ import annotations

import os
from typing import Mapping, Sequence

import grpc
from openshell import ExecResult, SandboxClient, SandboxError, SandboxRef, WorkspaceClient

# `_proto` is underscore-private in the SDK's own naming, but it is the only
# way to build a `SandboxSpec` carrying providers/environment — the SDK's
# public surface has no non-proto spec builder, and `sandbox.py` reaches
# into the same module internally (`_default_spec`).
from openshell._proto import openshell_pb2

OPENSHELL_GATEWAY_ENDPOINT_ENV = "OPENSHELL_GATEWAY_ENDPOINT"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_READY_TIMEOUT_SECONDS = 120.0


class OpenShellUnavailable(RuntimeError):
    """The gateway could not be reached, or an RPC failed.

    Wraps `grpc.RpcError` and `openshell.SandboxError` so callers in
    `flock.port`/`flock.control` depend on one error type, not on grpc or
    openshell's own exception hierarchy.
    """


def _endpoint(explicit: str | None) -> str:
    endpoint = explicit or os.environ.get(OPENSHELL_GATEWAY_ENDPOINT_ENV)
    if not endpoint:
        raise OpenShellUnavailable(
            f"no OpenShell gateway endpoint: pass one explicitly or set {OPENSHELL_GATEWAY_ENDPOINT_ENV}"
        )
    return endpoint


class OpenShellClient:
    """Sandbox lifecycle and exec, scoped to one OpenShell workspace.

    One workspace per tenant (`pod:tenant`) — see docs/LLD-port-openshell.md
    §workspace for why. `sandbox_client` is accepted for tests: pass a
    fake that implements the same methods as `openshell.SandboxClient`. It
    is never used to fabricate success — a test double still has to raise
    to signal failure, exactly like the real one.
    """

    def __init__(
        self,
        workspace: str,
        *,
        endpoint: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        sandbox_client: SandboxClient | None = None,
        workspace_client: WorkspaceClient | None = None,
    ) -> None:
        if not workspace:
            raise ValueError("workspace must be a non-empty string")
        self.workspace = workspace
        self.timeout = timeout
        self._client = sandbox_client or SandboxClient(_endpoint(endpoint), timeout=timeout)
        # Built lazily from `self._client` in the real case (needs its live
        # grpc channel); accepted directly here so tests can inject a fake
        # without needing a fake that also mimics `SandboxClient._channel`.
        self._workspace_client = workspace_client

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenShellClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def ensure_workspace(self) -> None:
        """Create this client's workspace if it doesn't already exist.

        Real gateway behavior, confirmed directly: a sandbox `create()` in
        a workspace that was never explicitly created fails with
        `NOT_FOUND: workspace '<name>' not found` — there is no implicit,
        lazy workspace creation the way there might be for a namespace in
        some other systems. `create_sandbox` calls this itself, so callers
        never need to know about the two-step requirement.
        """
        if self._workspace_client is None:
            self._workspace_client = WorkspaceClient.from_sandbox_client(self._client)
        ws_client = self._workspace_client
        try:
            ws_client.get(self.workspace)
            return
        except (grpc.RpcError, SandboxError) as exc:
            if not (isinstance(exc, grpc.Call) and exc.code() == grpc.StatusCode.NOT_FOUND):
                raise OpenShellUnavailable(
                    f"ensure_workspace({self.workspace!r}) failed: {exc}"
                ) from exc
        try:
            ws_client.create(self.workspace)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(
                f"ensure_workspace({self.workspace!r}) failed: {exc}"
            ) from exc

    def create_sandbox(
        self,
        name: str,
        *,
        providers: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
    ) -> SandboxRef:
        """Create a sandbox named `name` in this client's workspace, and
        block until it is ready to accept `exec_sandbox`.

        Creation is asynchronous on the gateway side: a freshly created
        sandbox reports phase PROVISIONING, and calling `exec` before it
        reaches READY fails with `FAILED_PRECONDITION: sandbox is not
        ready` — observed directly against the real gateway, not assumed.
        So this method waits, the same way the SDK's own `Sandbox` context
        manager does internally, rather than handing back a ref that isn't
        actually usable yet.

        `providers` names OpenShell's own credential-bundle mechanism
        (`SandboxSpec.providers`) — unrelated to flock's own "provider"
        concept (a model backend selected for tmux agents). See
        docs/NAMING-openshell.md for the collision.
        """
        self.ensure_workspace()
        try:
            spec = openshell_pb2.SandboxSpec(
                environment=dict(environment or {}),
                providers=list(providers),
            )
            self._client.create(
                workspace=self.workspace, spec=spec, name=name, labels=labels
            )
            return self._client.wait_ready(
                name, workspace=self.workspace, timeout_seconds=ready_timeout
            )
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"create_sandbox({name!r}) failed: {exc}") from exc

    def get_sandbox(self, name: str) -> SandboxRef:
        try:
            return self._client.get(name, workspace=self.workspace)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"get_sandbox({name!r}) failed: {exc}") from exc

    def delete_sandbox(self, name: str) -> bool:
        try:
            return self._client.delete(name, workspace=self.workspace)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"delete_sandbox({name!r}) failed: {exc}") from exc

    def exec_sandbox(
        self,
        sandbox_id: str,
        command: Sequence[str],
        *,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecResult:
        """Run one command to completion inside a running sandbox.

        This is a one-shot process spawn, not an attach to an already
        running interactive process — there is no tmux-style "paste into a
        live pane" equivalent in the OpenShell RPC surface. Each delivery
        is its own invocation; per-CLI headless/resume flags carry
        conversation continuity instead (docs/LLD-port-openshell.md).
        """
        try:
            return self._client.exec(
                sandbox_id,
                command,
                env=env,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
            )
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"exec_sandbox({sandbox_id!r}) failed: {exc}") from exc
