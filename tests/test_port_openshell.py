"""Unit tests for flock.port.openshell.deliver_openshell.

Exercise the delivery logic against an injected fake standing in for
openshell.SandboxClient (via a real OpenShellClient wrapping it) -- these
do NOT verify gateway connectivity, only that this module calls the
wrapper correctly and reacts correctly to its results. See
docs/LLD-port-openshell.md for what has and hasn't been run against a
live gateway.
"""

from conftest import FakeRespRedis
from openshell import ExecResult

from flock.bus import build as build_envelope, encode, parse as parse_envelope, prefix
from flock.openshell.client import OpenShellClient
from flock.openshell.naming import sandbox_name, workspace_name
from flock.port.openshell import deliver_openshell


class FakeSandboxClient:
    def __init__(self):
        self.calls = []
        self.get_result = None
        self.get_exc = None
        self.exec_result = None
        self.exec_exc = None

    def get(self, name, *, workspace):
        self.calls.append(("get", workspace, name))
        if self.get_exc:
            raise self.get_exc
        return self.get_result

    def exec(self, sandbox_id, command, *, env=None, stdin=None, timeout_seconds=None, stream_output=False, workdir=None):
        self.calls.append(("exec", sandbox_id, list(command), stdin))
        if self.exec_exc:
            raise self.exec_exc
        return self.exec_result

    def close(self):
        pass


class _Ref:
    def __init__(self, id):
        self.id = id


def _client(exec_result=None, exec_exc=None, sandbox_id="sbx-1"):
    fake = FakeSandboxClient()
    fake.get_result = _Ref(sandbox_id)
    fake.exec_result = exec_result
    fake.exec_exc = exec_exc
    wrapped = OpenShellClient("acme-hq", sandbox_client=fake)
    return wrapped, fake


def _setup(r, pod, tenant, agent, source, kind, payload, cli="claude"):
    r.hset(prefix(pod, tenant, resource="roster"), agent, "openshell")
    r.set(prefix(pod, tenant, agent=agent, resource="launch"), cli)
    env = build_envelope(kind=kind, source=source, destination=agent, payload=payload, pod=pod, tenant=tenant)
    ingress_key = prefix(pod, tenant, agent, "ingress")
    r.rpush(ingress_key, encode(env))
    return env


def test_message_execs_headless_and_replies():
    r = FakeRespRedis()
    env = _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"})
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="hi back", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    dead_key = prefix("acme", "hq", "backend", "dead")
    assert r.lists.get(dead_key, []) == []

    ((kind, workspace, name), (exec_kind, sandbox_id, command, stdin)) = fake_sdk.calls
    assert kind == "get"
    assert name == sandbox_name("backend")
    assert sandbox_id == "sbx-1"
    assert command == ["claude", "-p", "-c"]  # resume=True always, see module docstring
    assert stdin == b"[message from alice] hi"

    egress_key = prefix("acme", "hq", "backend", "egress")
    assert len(r.lists.get(egress_key, [])) == 1
    reply = parse_envelope(r.lists[egress_key][0])
    assert reply["l2"]["destination"] == "alice"
    assert reply["payload"] == {"text": "hi back"}
    assert reply["correlation_id"] == env["stream_id"]


def test_command_execs_without_message_prefix():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Command", {"text": "git status"})
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="clean", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    (_get_call, (_kind, _id, _command, stdin)) = fake_sdk.calls
    assert stdin == b"git status"


def test_gateway_unavailable_dead_letters_and_sends_no_reply():
    from flock.openshell.client import OpenShellUnavailable

    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"})
    fake_client, _ = _client(exec_exc=OpenShellUnavailable("gateway down"))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1
    egress_key = prefix("acme", "hq", "backend", "egress")
    assert r.lists.get(egress_key, []) == []


def test_no_reply_sent_when_output_is_empty():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"})
    fake_client, _ = _client(exec_result=ExecResult(exit_code=0, stdout="", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    egress_key = prefix("acme", "hq", "backend", "egress")
    assert r.lists.get(egress_key, []) == []
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert r.lists.get(dead_key, []) == []


def test_nonzero_exit_still_replies_with_combined_output():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"})
    fake_client, _ = _client(exec_result=ExecResult(exit_code=1, stdout="", stderr="boom"))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    egress_key = prefix("acme", "hq", "backend", "egress")
    reply = parse_envelope(r.lists[egress_key][0])
    assert reply["payload"] == {"text": "boom"}


def test_add_ticket_never_touches_the_sandbox_client():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "AddTicket", {"title": "t", "description": "d"})
    fake_client, fake_sdk = _client()

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    assert fake_sdk.calls == []
    todo_key = prefix("acme", "hq", agent="backend", resource="tasks.todo")
    assert len(r.lists.get(todo_key, [])) == 1


def test_attachment_dead_letters_as_not_yet_implemented():
    r = FakeRespRedis()
    _setup(
        r, "acme", "hq", "backend", "alice", "Attachment",
        {"filename": "a.txt", "mime_type": "text/plain", "content_base64": "aGk="},
    )
    fake_client, fake_sdk = _client()

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    assert fake_sdk.calls == []
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1


def test_unknown_kind_dead_letters():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Bogus", {})
    fake_client, fake_sdk = _client()

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    assert fake_sdk.calls == []
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1


def test_long_agent_name_uses_shortened_sandbox_name():
    r = FakeRespRedis()
    long_agent = "a-very-long-agent-name-that-exceeds-nineteen-chars"
    _setup(r, "acme", "hq", long_agent, "alice", "Message", {"text": "hi"})
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="ok", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent=long_agent, client=fake_client)

    (get_call, _exec_call) = fake_sdk.calls
    assert get_call == ("get", "acme-hq", sandbox_name(long_agent))
    assert len(get_call[2]) <= 19


def test_default_cli_is_claude_when_launch_unset():
    r = FakeRespRedis()
    r.hset(prefix("acme", "hq", resource="roster"), "backend", "openshell")
    env = build_envelope(kind="Message", source="alice", destination="backend", payload={"text": "hi"}, pod="acme", tenant="hq")
    r.rpush(prefix("acme", "hq", "backend", "ingress"), encode(env))
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="ok", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    (_get_call, (_kind, _id, command, _stdin)) = fake_sdk.calls
    assert command[0] == "claude"


def test_workspace_name_derived_from_pod_and_tenant():
    assert workspace_name("acme", "hq") == "acme-hq"
