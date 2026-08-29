"""Unit tests for flock.openshell.client.

These exercise OpenShellClient's own logic (workspace scoping, error
wrapping) against an injected fake standing in for openshell.SandboxClient.
They do NOT verify connectivity to a real OpenShell gateway — that requires
a live gateway and is out of scope for this suite. See
docs/LLD-port-openshell.md for what remains unverified.
"""

import grpc
import pytest
from openshell import ExecResult, SandboxError, SandboxRef, SandboxStatusRef

from flock.openshell.client import OpenShellClient, OpenShellUnavailable


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
        self.closed = False

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

    def exec(self, sandbox_id, command, *, env=None, stdin=None, timeout_seconds=None, stream_output=False, workdir=None):
        self.calls.append(("exec", sandbox_id, list(command), stdin, env, timeout_seconds))
        if self.exec_exc:
            raise self.exec_exc
        return self.exec_result

    def close(self):
        self.closed = True


def _ref(name="dave", sandbox_id="sbx-123", phase=2):
    return SandboxRef(id=sandbox_id, name=name, workspace="pod:acme:tenant:hq", status=SandboxStatusRef(phase=phase, current_policy_version=1))


def test_requires_nonempty_workspace():
    with pytest.raises(ValueError):
        OpenShellClient("", sandbox_client=FakeSandboxClient())


def test_create_sandbox_passes_workspace_name_and_providers():
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)  # PROVISIONING, matches a real create() response
    fake.wait_ready_result = _ref(phase=2)  # READY, matches a real wait_ready() response
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

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
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    with pytest.raises(OpenShellUnavailable):
        client.create_sandbox("dave")


def test_create_sandbox_wraps_grpc_error():
    fake = FakeSandboxClient()

    class _Unavailable(grpc.RpcError):
        pass

    fake.create_exc = _Unavailable()
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

    with pytest.raises(OpenShellUnavailable):
        client.create_sandbox("dave")


def test_create_sandbox_wraps_not_ready_in_time():
    fake = FakeSandboxClient()
    fake.create_result = _ref(phase=1)
    fake.wait_ready_exc = SandboxError("sandbox dave was not ready within timeout")
    client = OpenShellClient("pod:acme:tenant:hq", sandbox_client=fake)

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


def test_missing_endpoint_raises_before_touching_network():
    import os

    prior = os.environ.pop("OPENSHELL_GATEWAY_ENDPOINT", None)
    try:
        with pytest.raises(OpenShellUnavailable):
            OpenShellClient("pod:acme:tenant:hq")
    finally:
        if prior is not None:
            os.environ["OPENSHELL_GATEWAY_ENDPOINT"] = prior
