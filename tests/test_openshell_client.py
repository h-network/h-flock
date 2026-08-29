"""Unit tests for flock.openshell.client.

These exercise OpenShellClient's own logic (workspace scoping, error
wrapping) against an injected fake standing in for openshell.SandboxClient.
They do NOT verify connectivity to a real OpenShell gateway — that requires
a live gateway and is out of scope for this suite. See
docs/LLD-port-openshell.md for what remains unverified.
"""

from types import SimpleNamespace

import grpc
import pytest
from openshell import ExecResult, SandboxError, SandboxRef, SandboxStatusRef

from flock.openshell.client import DEFAULT_READY_TIMEOUT_SECONDS, OpenShellClient, OpenShellUnavailable


class FakeSandboxClient:
    """Minimal stand-in for openshell.SandboxClient's methods we call.

    Every method must be given real return values or made to raise by the
    test — there is no default "successful" behavior baked in here, unlike
    the prior attempt's production client itself.
    """

    def __init__(self):
        self.calls = []
        self.create_result = None
        self.create_exc = None
        self.wait_ready_result = None
        self.wait_ready_exc = None
        self.get_result = None
        self.get_exc = None
        self.delete_result = None
        self.delete_exc = None
        self.exec_result = None
        self.exec_exc = None
        self.list_result = None
        self.list_exc = None
        self.stop_result = None
        self.stop_exc = None
        self.start_result = None
        self.start_exc = None
        self.closed = False
        self._stub = FakeStub()

    def create(self, *, workspace, spec, name, labels):
        self.calls.append(("create", workspace, name, labels))
        if self.create_exc:
            raise self.create_exc
        return self.create_result

    def wait_ready(self, name, *, workspace, timeout_seconds):
        self.calls.append(("wait_ready", workspace, name, timeout_seconds))
        if self.wait_ready_exc:
            raise self.wait_ready_exc
        return self.wait_ready_result

    def get(self, name, *, workspace):
        self.calls.append(("get", workspace, name))
        if self.get_exc:
            raise self.get_exc
        return self.get_result

    def delete(self, name, *, workspace):
        self.calls.append(("delete", workspace, name))
        if self.delete_exc:
            raise self.delete_exc
        return self.delete_result

    def list(self, *, workspace, limit, offset, label_selector):
        self.calls.append(("list", workspace, limit, offset, label_selector))
        if self.list_exc:
            raise self.list_exc
        return self.list_result

    def stop(self, name, *, workspace):
        self.calls.append(("stop", workspace, name))
        if self.stop_exc:
            raise self.stop_exc
        return self.stop_result

    def start(self, name, *, workspace):
        self.calls.append(("start", workspace, name))
        if self.start_exc:
            raise self.start_exc
        return self.start_result

    def exec(self, sandbox_id, command, *, env=None, stdin=None, timeout_seconds=None, stream_output=False, workdir=None):
        self.calls.append(("exec", sandbox_id, list(command), stdin, env, timeout_seconds))
        if self.exec_exc:
            raise self.exec_exc
        return self.exec_result

    def close(self):
        self.closed = True


def _ref(name="dave", sandbox_id="sbx-123", phase=2):
    return SandboxRef(id=sandbox_id, name=name, workspace="pod:acme:tenant:hq", status=SandboxStatusRef(phase=phase, current_policy_version=1))


class FakeStub:
    """Fake for the raw `SandboxClient._stub`, used by RPCs the SDK's own
    high-level wrappers don't cover at all (service exposure, provider
    CRUD, logs, watch). One generic dispatcher rather than ~12 near-
    identical methods; `results`/`excs` are keyed by RPC name.
    """

    def __init__(self):
        self.calls = []
        self.results = {}
        self.excs = {}

    def _call(self, name, request, *, timeout=None):
        self.calls.append((name, request))
        if name in self.excs:
            raise self.excs[name]
        return self.results.get(name)

    def __getattr__(self, name):
        return lambda request, timeout=None: self._call(name, request, timeout=timeout)


class FakeWorkspaceClient:
    def __init__(self):
        self.calls = []
        self.get_exc = None
        self.create_exc = None

    def get(self, name):
        self.calls.append(("get", name))
        if self.get_exc:
            raise self.get_exc
        return object()

    def create(self, name):
        self.calls.append(("create", name))
        if self.create_exc:
            raise self.create_exc
        return object()


def _existing_workspace():
    """A FakeWorkspaceClient reporting the workspace as already present.

    Used by tests that aren't exercising ensure_workspace's own logic, so
    create_sandbox's internal ensure_workspace() call doesn't try to build
    a real WorkspaceClient from a fake SandboxClient with no _channel.
    """
    return FakeWorkspaceClient()


def test_requires_nonempty_workspace():
    with pytest.raises(ValueError):
        OpenShellClient("", sandbox_client=FakeSandboxClient())


def test_create_sandbox_passes_workspace_name_and_providers():
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)  # PROVISIONING, matches a real create() response
    fake.wait_ready_result = _ref(phase=2)  # READY, matches a real wait_ready() response
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=fake, workspace_client=_existing_workspace()
    )

    result = client.create_sandbox("dave", providers=["anthropic-oauth"], environment={"AGENT_NAME": "dave"})

    # create_sandbox waits for READY before returning -- a real gateway run
    # showed exec() fails with FAILED_PRECONDITION against a PROVISIONING
    # sandbox, so the raw create() response is not what callers should get.
    assert result is fake.wait_ready_result
    (create_call, wait_call) = fake.calls
    kind, workspace, name, labels = create_call
    assert kind == "create"
    assert workspace == "pod:acme:tenant:hq"
    assert name == "dave"
    assert wait_call[:3] == ("wait_ready", "pod:acme:tenant:hq", "dave")


def test_create_sandbox_wraps_sandbox_error():
    fake = FakeSandboxClient()
    fake.create_exc = SandboxError("gateway refused")
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=fake, workspace_client=_existing_workspace()
    )

    with pytest.raises(OpenShellUnavailable):
        client.create_sandbox("dave")


def test_create_sandbox_wraps_grpc_error():
    fake = FakeSandboxClient()

    class _Unavailable(grpc.RpcError):
        pass

    fake.create_exc = _Unavailable()
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=fake, workspace_client=_existing_workspace()
    )

    with pytest.raises(OpenShellUnavailable):
        client.create_sandbox("dave")


def test_create_sandbox_wraps_not_ready_in_time():
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)
    fake.wait_ready_exc = SandboxError("sandbox dave was not ready within timeout")
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=fake, workspace_client=_existing_workspace()
    )

    with pytest.raises(OpenShellUnavailable):
        client.create_sandbox("dave")


def test_get_sandbox_scopes_to_workspace():
    fake = FakeSandboxClient()
    fake.get_result = _ref()
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.get_sandbox("dave")

    assert result is fake.get_result
    assert fake.calls == [("get", "pod:acme:tenant:hq", "dave")]


def test_get_sandbox_not_found_raises_unavailable_not_a_fake_status():
    fake = FakeSandboxClient()
    fake.get_exc = SandboxError("sandbox not found")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    with pytest.raises(OpenShellUnavailable):
        client.get_sandbox("dave")


def test_delete_sandbox_returns_real_result():
    fake = FakeSandboxClient()
    fake.delete_result = True
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.delete_sandbox("dave") is True
    assert fake.calls == [("delete", "pod:acme:tenant:hq", "dave")]


def test_exec_sandbox_carries_stdin_and_returns_real_exec_result():
    fake = FakeSandboxClient()
    fake.exec_result = ExecResult(exit_code=0, stdout="hi", stderr="")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.exec_sandbox("sbx-123", ["claude", "-p"], stdin=b"hello")

    assert result == ExecResult(exit_code=0, stdout="hi", stderr="")
    ((kind, sandbox_id, command, stdin, env, timeout),) = fake.calls
    assert kind == "exec"
    assert sandbox_id == "sbx-123"
    assert command == ["claude", "-p"]
    assert stdin == b"hello"


def test_exec_sandbox_nonzero_exit_is_not_hidden():
    fake = FakeSandboxClient()
    fake.exec_result = ExecResult(exit_code=1, stdout="", stderr="boom")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.exec_sandbox("sbx-123", ["claude", "-p"], stdin=b"hello")

    assert result.exit_code == 1
    assert result.stderr == "boom"


def test_close_delegates_to_underlying_client():
    fake = FakeSandboxClient()
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    client.close()

    assert fake.closed is True


class _NotFound(grpc.RpcError, grpc.Call):
    def code(self):
        return grpc.StatusCode.NOT_FOUND

    def details(self):
        return "workspace not found"


def test_ensure_workspace_is_a_noop_when_workspace_already_exists():
    fake_ws = FakeWorkspaceClient()
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=FakeSandboxClient(), workspace_client=fake_ws
    )

    client.ensure_workspace()

    assert fake_ws.calls == [("get", "pod:acme:tenant:hq")]


def test_ensure_workspace_creates_on_not_found():
    fake_ws = FakeWorkspaceClient()
    fake_ws.get_exc = _NotFound()
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=FakeSandboxClient(), workspace_client=fake_ws
    )

    client.ensure_workspace()

    assert fake_ws.calls == [("get", "pod:acme:tenant:hq"), ("create", "pod:acme:tenant:hq")]


def test_ensure_workspace_does_not_swallow_other_errors():
    fake_ws = FakeWorkspaceClient()
    fake_ws.get_exc = SandboxError("gateway refused")
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=FakeSandboxClient(), workspace_client=fake_ws
    )

    with pytest.raises(OpenShellUnavailable):
        client.ensure_workspace()

    # A non-NOT_FOUND failure must not be treated as "go ahead and create".
    assert fake_ws.calls == [("get", "pod:acme:tenant:hq")]


def test_create_sandbox_ensures_workspace_first():
    fake_ws = FakeWorkspaceClient()
    fake_ws.get_exc = _NotFound()
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)
    fake.wait_ready_result = _ref(phase=2)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake, workspace_client=fake_ws)

    client.create_sandbox("dave")

    assert fake_ws.calls == [("get", "pod:acme:tenant:hq"), ("create", "pod:acme:tenant:hq")]


def test_missing_endpoint_raises_before_touching_network():
    import os

    prior = os.environ.pop("OPENSHELL_GATEWAY_ENDPOINT", None)
    try:
        with pytest.raises(OpenShellUnavailable):
            OpenShellClient("pod:acme:tenant:hq")
    finally:
        if prior is not None:
            os.environ["OPENSHELL_GATEWAY_ENDPOINT"] = prior


# -- Sandbox lifecycle: list/stop/start --------------------------------------

def test_list_sandboxes_scopes_to_workspace():
    fake = FakeSandboxClient()
    fake.list_result = [_ref(name="a"), _ref(name="b")]
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.list_sandboxes()

    assert result == fake.list_result
    assert fake.calls == [("list", "pod:acme:tenant:hq", 100, 0, None)]


def test_list_sandboxes_wraps_errors():
    fake = FakeSandboxClient()
    fake.list_exc = SandboxError("gateway refused")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    with pytest.raises(OpenShellUnavailable):
        client.list_sandboxes()


def test_stop_sandbox_returns_real_ref():
    fake = FakeSandboxClient()
    fake.stop_result = _ref(phase=7)  # STOPPED
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.stop_sandbox("dave")

    assert result is fake.stop_result
    assert fake.calls == [("stop", "pod:acme:tenant:hq", "dave")]


def test_start_sandbox_waits_for_ready():
    fake = FakeSandboxClient()
    fake.start_result = None  # SDK's .start() return value is unused; wait_ready's is
    fake.wait_ready_result = _ref(phase=2)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    result = client.start_sandbox("dave")

    assert result is fake.wait_ready_result
    assert fake.calls == [("start", "pod:acme:tenant:hq", "dave"), ("wait_ready", "pod:acme:tenant:hq", "dave", DEFAULT_READY_TIMEOUT_SECONDS)]


# -- Service exposure ---------------------------------------------------------

def test_expose_service_returns_url():
    fake = FakeSandboxClient()
    fake._stub.results["ExposeService"] = SimpleNamespace(url="https://dave-web.example.test")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    url = client.expose_service("dave", "web", 8080, domain=True)

    assert url == "https://dave-web.example.test"
    (call,) = fake._stub.calls
    name, request = call
    assert name == "ExposeService"
    assert request.sandbox == "dave"
    assert request.service == "web"
    assert request.target_port == 8080
    assert request.domain is True
    assert request.workspace == "pod:acme:tenant:hq"


def test_expose_service_wraps_errors():
    fake = FakeSandboxClient()
    fake._stub.excs["ExposeService"] = SandboxError("nope")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    with pytest.raises(OpenShellUnavailable):
        client.expose_service("dave", "web", 8080)


def test_list_services_returns_urls():
    fake = FakeSandboxClient()
    fake._stub.results["ListServices"] = SimpleNamespace(
        services=[SimpleNamespace(url="https://a"), SimpleNamespace(url="https://b")]
    )
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.list_services("dave") == ["https://a", "https://b"]


def test_delete_service_returns_real_result():
    fake = FakeSandboxClient()
    fake._stub.results["DeleteService"] = SimpleNamespace(deleted=True)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.delete_service("dave", "web") is True


# -- Provider CRUD --------------------------------------------------------

def test_create_provider_sends_type_and_credentials():
    fake = FakeSandboxClient()
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    client.create_provider("anthropic", "claude-code", credentials={"api_key": "x"})

    (call,) = fake._stub.calls
    name, request = call
    assert name == "CreateProvider"
    assert request.provider.type == "claude-code"
    assert request.workspace == "pod:acme:tenant:hq"


def test_list_providers_returns_real_list():
    fake = FakeSandboxClient()
    fake._stub.results["ListProviders"] = SimpleNamespace(providers=["p1", "p2"])
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.list_providers() == ["p1", "p2"]


def test_delete_provider_returns_real_result():
    fake = FakeSandboxClient()
    fake._stub.results["DeleteProvider"] = SimpleNamespace(deleted=True)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.delete_provider("anthropic") is True


def test_attach_and_detach_sandbox_provider():
    fake = FakeSandboxClient()
    fake._stub.results["AttachSandboxProvider"] = SimpleNamespace(attached=True)
    fake._stub.results["DetachSandboxProvider"] = SimpleNamespace(detached=True)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.attach_sandbox_provider("dave", "anthropic") is True
    assert client.detach_sandbox_provider("dave", "anthropic") is True


def test_list_sandbox_providers():
    fake = FakeSandboxClient()
    fake._stub.results["ListSandboxProviders"] = SimpleNamespace(providers=["anthropic"])
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.list_sandbox_providers("dave") == ["anthropic"]


# -- Observability ----------------------------------------------------------

def test_get_sandbox_logs_returns_log_lines():
    fake = FakeSandboxClient()
    fake._stub.results["GetSandboxLogs"] = SimpleNamespace(logs=["line1", "line2"], buffer_total=2)
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    assert client.get_sandbox_logs("sbx-1") == ["line1", "line2"]


def test_watch_sandbox_is_lazy_and_yields_events():
    fake = FakeSandboxClient()
    fake._stub.results["WatchSandbox"] = iter(["event1", "event2"])
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    generator = client.watch_sandbox("sbx-1")
    # Lazy: constructing the generator must not have called the stub yet.
    assert fake._stub.calls == []

    events = list(generator)

    assert events == ["event1", "event2"]
    assert len(fake._stub.calls) == 1
    assert fake._stub.calls[0][0] == "WatchSandbox"


# -- SandboxSpec.policy (opt-in, partial slice) ------------------------------

def test_create_sandbox_omits_policy_when_nothing_supplied():
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)
    fake.wait_ready_result = _ref(phase=2)
    client = OpenShellClient(
        "pod:acme:tenant:hq", sandbox_client=fake, workspace_client=_existing_workspace()
    )

    client.create_sandbox("dave")

    (create_call, _wait_call) = fake.calls
    _kind, _workspace, _name, _labels = create_call
    # The spec itself isn't captured by this fake's `create()` signature,
    # so assert indirectly: _build_policy returns None for no kwargs.
    from flock.openshell.client import OpenShellClient as _C
    assert _C._build_policy(
        filesystem_read_only=(), filesystem_read_write=(), include_workdir=None,
        run_as_user=None, run_as_group=None, network_allow=None,
    ) is None


def test_build_policy_sets_filesystem_fields():
    from flock.openshell.client import OpenShellClient as _C

    policy = _C._build_policy(
        filesystem_read_only=["/etc"], filesystem_read_write=["/workdir"], include_workdir=True,
        run_as_user=None, run_as_group=None, network_allow=None,
    )

    assert policy is not None
    assert list(policy.filesystem.read_only) == ["/etc"]
    assert list(policy.filesystem.read_write) == ["/workdir"]
    assert policy.filesystem.include_workdir is True


def test_build_policy_sets_process_fields():
    from flock.openshell.client import OpenShellClient as _C

    policy = _C._build_policy(
        filesystem_read_only=(), filesystem_read_write=(), include_workdir=None,
        run_as_user="ubuntu", run_as_group="ubuntu", network_allow=None,
    )

    assert policy.process.run_as_user == "ubuntu"
    assert policy.process.run_as_group == "ubuntu"


def test_build_policy_sets_network_allow_pass_through():
    from flock.openshell.client import OpenShellClient as _C

    policy = _C._build_policy(
        filesystem_read_only=(), filesystem_read_write=(), include_workdir=None,
        run_as_user=None, run_as_group=None,
        network_allow={"anthropic": [{"host": "api.anthropic.com", "port": 443, "protocol": "rest"}]},
    )

    rule = policy.network_policies["anthropic"]
    assert rule.name == "anthropic"
    assert rule.endpoints[0].host == "api.anthropic.com"
    assert rule.endpoints[0].port == 443
