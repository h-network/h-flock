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
import pathlib
from typing import Iterator, Mapping, Sequence

import grpc
from openshell import ExecResult, SandboxClient, SandboxError, SandboxRef, TlsConfig, WorkspaceClient

# `_proto` is underscore-private in the SDK's own naming, but it is the only
# way to build a `SandboxSpec` carrying providers/environment — the SDK's
# public surface has no non-proto spec builder, and `sandbox.py` reaches
# into the same module internally (`_default_spec`). Also used below for
# every RPC the SDK's own high-level wrappers don't cover at all (service
# exposure, provider CRUD, watch, logs) — those have no wrapper to call,
# only the raw stub (`self._client._stub`), which the SDK's own client
# object already carries.
from openshell._proto import datamodel_pb2, openshell_pb2, sandbox_pb2

OPENSHELL_GATEWAY_ENDPOINT_ENV = "OPENSHELL_GATEWAY_ENDPOINT"
# mTLS material, all optional -- the real test gateway requires client-cert
# auth (confirmed directly: a plaintext/no-cert attempt gets a TLS
# "certificate required" alert), but a from-scratch OpenShellClient() had
# no way to supply any of this at all until this was found and fixed. See
# docs/LLD-port-openshell.md for what identity these paths should actually
# point to -- still an open question, unrelated to whether the mechanism
# itself works.
OPENSHELL_GATEWAY_TLS_CA_ENV = "OPENSHELL_GATEWAY_TLS_CA"
OPENSHELL_GATEWAY_TLS_CERT_ENV = "OPENSHELL_GATEWAY_TLS_CERT"
OPENSHELL_GATEWAY_TLS_KEY_ENV = "OPENSHELL_GATEWAY_TLS_KEY"
OPENSHELL_GATEWAY_BEARER_TOKEN_ENV = "OPENSHELL_GATEWAY_BEARER_TOKEN"
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


def _tls_from_env() -> TlsConfig | None:
    """Build TlsConfig from env-supplied paths, or None for a plaintext channel.

    None is a deliberate, valid choice (e.g. a local dev gateway with no
    TLS at all) -- this only builds a config when at least one of the
    three paths is actually set, rather than defaulting to `TlsConfig()`
    (system roots, no client identity) the moment any env var is present.
    """
    ca = os.environ.get(OPENSHELL_GATEWAY_TLS_CA_ENV)
    cert = os.environ.get(OPENSHELL_GATEWAY_TLS_CERT_ENV)
    key = os.environ.get(OPENSHELL_GATEWAY_TLS_KEY_ENV)
    if not (ca or cert or key):
        return None
    return TlsConfig(
        ca_path=pathlib.Path(ca) if ca else None,
        cert_path=pathlib.Path(cert) if cert else None,
        key_path=pathlib.Path(key) if key else None,
    )


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
        self._client = sandbox_client or SandboxClient(
            _endpoint(endpoint),
            tls=_tls_from_env(),
            bearer_token=os.environ.get(OPENSHELL_GATEWAY_BEARER_TOKEN_ENV),
            timeout=timeout,
        )
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
        filesystem_read_only: Sequence[str] = (),
        filesystem_read_write: Sequence[str] = (),
        include_workdir: bool | None = None,
        run_as_user: str | None = None,
        run_as_group: str | None = None,
        network_allow: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
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

        The filesystem/process/network_allow parameters are a deliberately
        partial slice of the real `SandboxPolicy` — see
        docs/LLD-port-openshell.md for what's covered and what isn't.
        Omitting all of them (the default) omits `SandboxSpec.policy`
        entirely, unchanged from before this was added: the sandbox then
        discovers its policy from the image's own baked-in default, exactly
        as it always has. `network_allow` maps a rule name to a list of
        endpoint dicts passed through close to verbatim as
        `NetworkEndpoint` fields (`host`, `port`, `protocol`, ...) — this
        method does not attempt to default or validate them beyond what the
        proto itself requires, since the full `NetworkEndpoint` shape (L7
        rules, GraphQL/MCP-specific options, credential binding) is real
        but not verified here; only the plain `host`/`port`/`protocol`
        fields have actually been exercised against the live gateway.
        """
        self.ensure_workspace()
        try:
            spec_kwargs: dict[str, object] = {
                "environment": dict(environment or {}),
                "providers": list(providers),
            }
            policy = self._build_policy(
                filesystem_read_only=filesystem_read_only,
                filesystem_read_write=filesystem_read_write,
                include_workdir=include_workdir,
                run_as_user=run_as_user,
                run_as_group=run_as_group,
                network_allow=network_allow,
            )
            if policy is not None:
                spec_kwargs["policy"] = policy
            spec = openshell_pb2.SandboxSpec(**spec_kwargs)
            self._client.create(
                workspace=self.workspace, spec=spec, name=name, labels=labels
            )
            return self._client.wait_ready(
                name, workspace=self.workspace, timeout_seconds=ready_timeout
            )
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"create_sandbox({name!r}) failed: {exc}") from exc

    @staticmethod
    def _build_policy(
        *,
        filesystem_read_only: Sequence[str],
        filesystem_read_write: Sequence[str],
        include_workdir: bool | None,
        run_as_user: str | None,
        run_as_group: str | None,
        network_allow: Mapping[str, Sequence[Mapping[str, object]]] | None,
    ) -> sandbox_pb2.SandboxPolicy | None:
        """Build a `SandboxPolicy` only from whatever the caller actually
        supplied — never set `policy` at all if nothing was, so a sandbox
        created without any of these keeps discovering the image's own
        baked-in default exactly as before.

        Confirmed directly against the live gateway: setting `policy` at
        all replaces the ENTIRE baked-in default, including whatever
        network access it implicitly grants — `run_as_user="sandbox"`
        alone (no `network_allow`) creates a sandbox that immediately
        exits (`ContainerExited`, seen only via the raw
        `SandboxCondition`, not surfaced as a creation-time error at all),
        while the identical policy plus one valid `network_allow` rule
        creates and reaches READY normally. So `filesystem`/`run_as_user`/
        `run_as_group` without `network_allow` fails silently at the
        gateway, past what this wrapper can catch as a clean error — this
        raises `ValueError` up front instead, before ever calling the
        gateway, rather than let a caller hit that opaquely later.
        """
        has_filesystem = bool(filesystem_read_only) or bool(filesystem_read_write) or include_workdir is not None
        has_process = run_as_user is not None or run_as_group is not None
        has_network = bool(network_allow)
        if not (has_filesystem or has_process or has_network):
            return None
        if (has_filesystem or has_process) and not has_network:
            raise ValueError(
                "create_sandbox: setting a filesystem or process policy without network_allow "
                "replaces the sandbox's baked-in default network policy with nothing, which "
                "causes the sandbox's container to exit immediately on creation (confirmed "
                "directly against the live gateway) -- pass network_allow explicitly, even if "
                "it only re-grants what the default already allowed"
            )

        policy_kwargs: dict[str, object] = {}
        if has_filesystem:
            policy_kwargs["filesystem"] = sandbox_pb2.FilesystemPolicy(
                include_workdir=include_workdir if include_workdir is not None else True,
                read_only=list(filesystem_read_only),
                read_write=list(filesystem_read_write),
            )
        if has_process:
            policy_kwargs["process"] = sandbox_pb2.ProcessPolicy(
                run_as_user=run_as_user or "", run_as_group=run_as_group or ""
            )
        if has_network:
            policy_kwargs["network_policies"] = {
                rule_name: sandbox_pb2.NetworkPolicyRule(
                    name=rule_name,
                    endpoints=[sandbox_pb2.NetworkEndpoint(**endpoint) for endpoint in endpoints],
                )
                for rule_name, endpoints in network_allow.items()
            }
        return sandbox_pb2.SandboxPolicy(**policy_kwargs)

    def get_sandbox(self, name: str) -> SandboxRef:
        try:
            return self._client.get(name, workspace=self.workspace)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"get_sandbox({name!r}) failed: {exc}") from exc

    def list_sandboxes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        label_selector: str | None = None,
    ) -> list[SandboxRef]:
        """List sandboxes in this client's workspace."""
        try:
            return self._client.list(
                workspace=self.workspace, limit=limit, offset=offset, label_selector=label_selector
            )
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"list_sandboxes() failed: {exc}") from exc

    def stop_sandbox(self, name: str) -> SandboxRef:
        """Stop a sandbox without deleting it — its filesystem survives a
        later `start_sandbox`, unlike `delete_sandbox`. Real lifecycle
        counterpart for `PauseAgent` (`flock.control`), which currently has
        no openshell-side implementation.
        """
        try:
            return self._client.stop(name, workspace=self.workspace)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"stop_sandbox({name!r}) failed: {exc}") from exc

    def start_sandbox(self, name: str, *, ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS) -> SandboxRef:
        """Resume a previously stopped sandbox. Real counterpart for
        `ResumeAgent`.
        """
        try:
            self._client.start(name, workspace=self.workspace)
            return self._client.wait_ready(name, workspace=self.workspace, timeout_seconds=ready_timeout)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"start_sandbox({name!r}) failed: {exc}") from exc

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

    # -- Service exposure -------------------------------------------------
    # No high-level SDK wrapper exists for any of these; the SDK only ships
    # convenience methods for the sandbox/workspace lifecycle and exec. All
    # four go through the raw stub the SDK's own SandboxClient already
    # holds (`self._client._stub`) building the proto request directly, the
    # same way `create_sandbox` already has to for `SandboxSpec`.

    def expose_service(
        self, sandbox_name: str, service_name: str, target_port: int, *, domain: bool = False
    ) -> str:
        """Expose a port inside a sandbox as a reachable service; returns its URL."""
        try:
            response = self._client._stub.ExposeService(
                openshell_pb2.ExposeServiceRequest(
                    sandbox=sandbox_name, service=service_name, target_port=target_port,
                    domain=domain, workspace=self.workspace,
                ),
                timeout=self.timeout,
            )
            return response.url
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"expose_service({sandbox_name!r}, {service_name!r}) failed: {exc}") from exc

    def get_service(self, sandbox_name: str, service_name: str) -> str:
        try:
            response = self._client._stub.GetService(
                openshell_pb2.GetServiceRequest(sandbox=sandbox_name, service=service_name, workspace=self.workspace),
                timeout=self.timeout,
            )
            return response.url
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"get_service({sandbox_name!r}, {service_name!r}) failed: {exc}") from exc

    def list_services(self, sandbox_name: str, *, limit: int = 100, offset: int = 0) -> list[str]:
        try:
            response = self._client._stub.ListServices(
                openshell_pb2.ListServicesRequest(
                    sandbox=sandbox_name, limit=limit, offset=offset, workspace=self.workspace
                ),
                timeout=self.timeout,
            )
            return [item.url for item in response.services]
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"list_services({sandbox_name!r}) failed: {exc}") from exc

    def delete_service(self, sandbox_name: str, service_name: str) -> bool:
        try:
            response = self._client._stub.DeleteService(
                openshell_pb2.DeleteServiceRequest(
                    sandbox=sandbox_name, service=service_name, workspace=self.workspace
                ),
                timeout=self.timeout,
            )
            return response.deleted
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"delete_service({sandbox_name!r}, {service_name!r}) failed: {exc}") from exc

    # -- Provider CRUD ------------------------------------------------------
    # This is OpenShell's own "provider" (named credential bundle) concept
    # (see docs/NAMING-openshell.md) — always call it "openshell provider"
    # in code/docs to avoid colliding with flock's unrelated model-backend
    # "provider". `create_sandbox`'s `providers` parameter only *references*
    # a provider that must already exist; these methods are what actually
    # define/manage one.

    def create_provider(
        self,
        name: str,
        provider_type: str,
        *,
        credentials: Mapping[str, str] | None = None,
        config: Mapping[str, str] | None = None,
    ) -> None:
        """Define a named openshell provider (e.g. type "claude-code").

        `credentials` values are real secret material — see this ticket's
        standing rule on not moving credentials without asking first.
        """
        try:
            provider = datamodel_pb2.Provider(
                metadata=datamodel_pb2.ObjectMeta(name=name),
                type=provider_type,
                credentials=dict(credentials or {}),
                config=dict(config or {}),
            )
            self._client._stub.CreateProvider(
                openshell_pb2.CreateProviderRequest(provider=provider, workspace=self.workspace),
                timeout=self.timeout,
            )
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"create_provider({name!r}) failed: {exc}") from exc

    def list_providers(self) -> list:
        try:
            response = self._client._stub.ListProviders(
                openshell_pb2.ListProvidersRequest(workspace=self.workspace),
                timeout=self.timeout,
            )
            return list(response.providers)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"list_providers() failed: {exc}") from exc

    def delete_provider(self, name: str) -> bool:
        try:
            response = self._client._stub.DeleteProvider(
                openshell_pb2.DeleteProviderRequest(name=name, workspace=self.workspace),
                timeout=self.timeout,
            )
            return response.deleted
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"delete_provider({name!r}) failed: {exc}") from exc

    def attach_sandbox_provider(self, sandbox_name: str, provider_name: str) -> bool:
        """Attach a provider to an already-running sandbox, without recreating it."""
        try:
            response = self._client._stub.AttachSandboxProvider(
                openshell_pb2.AttachSandboxProviderRequest(
                    sandbox_name=sandbox_name, provider_name=provider_name, workspace=self.workspace
                ),
                timeout=self.timeout,
            )
            return response.attached
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(
                f"attach_sandbox_provider({sandbox_name!r}, {provider_name!r}) failed: {exc}"
            ) from exc

    def detach_sandbox_provider(self, sandbox_name: str, provider_name: str) -> bool:
        try:
            response = self._client._stub.DetachSandboxProvider(
                openshell_pb2.DetachSandboxProviderRequest(
                    sandbox_name=sandbox_name, provider_name=provider_name, workspace=self.workspace
                ),
                timeout=self.timeout,
            )
            return response.detached
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(
                f"detach_sandbox_provider({sandbox_name!r}, {provider_name!r}) failed: {exc}"
            ) from exc

    def list_sandbox_providers(self, sandbox_name: str) -> list:
        try:
            response = self._client._stub.ListSandboxProviders(
                openshell_pb2.ListSandboxProvidersRequest(sandbox_name=sandbox_name, workspace=self.workspace),
                timeout=self.timeout,
            )
            return list(response.providers)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"list_sandbox_providers({sandbox_name!r}) failed: {exc}") from exc

    # -- Observability ------------------------------------------------------

    def get_sandbox_logs(
        self, sandbox_id: str, *, lines: int = 100, since_ms: int = 0, min_level: str = ""
    ) -> list:
        try:
            response = self._client._stub.GetSandboxLogs(
                openshell_pb2.GetSandboxLogsRequest(
                    sandbox_id=sandbox_id, lines=lines, since_ms=since_ms, min_level=min_level,
                    workspace=self.workspace,
                ),
                timeout=self.timeout,
            )
            return list(response.logs)
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"get_sandbox_logs({sandbox_id!r}) failed: {exc}") from exc

    def watch_sandbox(
        self,
        sandbox_id: str,
        *,
        follow_status: bool = True,
        follow_logs: bool = False,
        follow_events: bool = False,
        stop_on_terminal: bool = True,
    ) -> Iterator:
        """Stream real-time status/log/event updates for a sandbox.

        A generator: iterate it to receive `SandboxStreamEvent`s as they
        arrive, instead of polling `get_sandbox`/`get_sandbox_logs`. Unlike
        every other method here, this does not eagerly perform the RPC —
        it's lazy, only starting the stream once iteration begins, since a
        caller may want to hold the object before committing to consume it.
        """
        try:
            stream = self._client._stub.WatchSandbox(
                openshell_pb2.WatchSandboxRequest(
                    id=sandbox_id, follow_status=follow_status, follow_logs=follow_logs,
                    follow_events=follow_events, stop_on_terminal=stop_on_terminal,
                ),
                timeout=self.timeout,
            )
            yield from stream
        except (grpc.RpcError, SandboxError) as exc:
            raise OpenShellUnavailable(f"watch_sandbox({sandbox_id!r}) failed: {exc}") from exc
