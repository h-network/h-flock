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
        # For scenarios needing more than one exec() call with different
        # results (e.g. attachment delivery: write, then headless notice)
        # -- consumed in order; falls back to exec_result/exec_exc once
        # exhausted (or if never set).
        self.exec_results = []
        # Parallel to `calls`, but only for "exec" entries -- the env=
        # dict passed to each exec() call, in order. Separate from `calls`
        # itself so existing tests that unpack `("exec", id, command, stdin)`
        # tuples don't need to change shape.
        self.exec_env_by_call = []

    def get(self, name, *, workspace):
        self.calls.append(("get", workspace, name))
        if self.get_exc:
            raise self.get_exc
        return self.get_result

    def exec(self, sandbox_id, command, *, env=None, stdin=None, timeout_seconds=None, stream_output=False, workdir=None):
        self.calls.append(("exec", sandbox_id, list(command), stdin))
        self.exec_env_by_call.append(env)
        if self.exec_results:
            outcome = self.exec_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
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


def test_attachment_writes_file_then_execs_notice_and_replies():
    r = FakeRespRedis()
    env = _setup(
        r, "acme", "hq", "backend", "alice", "Attachment",
        {"filename": "a.txt", "mime_type": "text/plain", "content_base64": "aGk="},
    )
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [
        ExecResult(exit_code=0, stdout="", stderr=""),  # the write
        ExecResult(exit_code=0, stdout="got it", stderr=""),  # the notice exec
    ]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    dead_key = prefix("acme", "hq", "backend", "dead")
    assert r.lists.get(dead_key, []) == []

    exec_calls = [call for call in fake_sdk.calls if call[0] == "exec"]
    (write_call, notice_call) = exec_calls
    _write_kind, _sandbox_id, write_command, write_stdin = write_call
    assert write_command[:3] == ["/bin/sh", "-c", 'mkdir -p "$1" && base64 -d > "$2" && mv -f "$2" "$3"']
    target_dir, _temp_path, final_path = write_command[4], write_command[5], write_command[6]
    assert target_dir == f"/sandbox/attachments/{env['stream_id']}"
    assert final_path == f"/sandbox/attachments/{env['stream_id']}/a.txt"
    import base64 as _b64
    assert _b64.b64decode(write_stdin) == b"hi"

    _notice_kind, _sandbox_id2, _notice_command, notice_stdin = notice_call
    assert final_path.encode() in notice_stdin
    assert b"[attachment from alice]" in notice_stdin

    egress_key = prefix("acme", "hq", "backend", "egress")
    reply = parse_envelope(r.lists[egress_key][0])
    assert reply["payload"] == {"text": "got it"}


def test_attachment_write_failure_dead_letters_without_notice_exec():
    r = FakeRespRedis()
    _setup(
        r, "acme", "hq", "backend", "alice", "Attachment",
        {"filename": "a.txt", "mime_type": "text/plain", "content_base64": "aGk="},
    )
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [ExecResult(exit_code=1, stdout="", stderr="disk full")]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [call for call in fake_sdk.calls if call[0] == "exec"]
    assert len(exec_calls) == 1  # only the write attempt, no notice exec
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1


def test_attachment_rejects_path_separator_in_filename():
    r = FakeRespRedis()
    _setup(
        r, "acme", "hq", "backend", "alice", "Attachment",
        {"filename": "../etc/passwd", "mime_type": "text/plain", "content_base64": "aGk="},
    )
    fake_client, fake_sdk = _client()

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    assert fake_sdk.calls == []
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1


def test_attachment_rejects_oversized_decoded_content():
    r = FakeRespRedis()
    import base64 as _b64
    huge = _b64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    _setup(
        r, "acme", "hq", "backend", "alice", "Attachment",
        {"filename": "a.bin", "mime_type": "application/octet-stream", "content_base64": huge},
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


# -- Per-CLI credential transfer (docs/openshell-credential-transfer-design.md) --

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_credential_env(monkeypatch):
    # None of these tests should ever depend on -- or leak into -- whatever
    # real credential env vars this office's own shell happens to carry.
    for name in list(os.environ):
        if name.startswith(("CLAUDE_OAUTH_TOKEN_", "CODEX_AUTH_JSON_", "AGY_AUTH_JSON_")):
            monkeypatch.delenv(name, raising=False)


def test_claude_passes_token_as_env_not_file(monkeypatch):
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_DEFAULT", "fake-token-for-this-test-only")
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="claude")
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="ok", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    assert len(exec_calls) == 1  # no separate write/wipe calls for claude
    assert fake_sdk.exec_env_by_call[0] == {"CLAUDE_CODE_OAUTH_TOKEN": "fake-token-for-this-test-only"}


def test_claude_passes_no_env_when_token_unset():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="claude")
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="ok", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    assert fake_sdk.exec_env_by_call[0] is None


def test_codex_writes_credential_file_then_execs_then_wipes(monkeypatch):
    monkeypatch.setenv("CODEX_AUTH_JSON_DEFAULT", '{"tokens": {"access_token": "fake-for-this-test"}}')
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="codex")
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [
        ExecResult(exit_code=0, stdout="", stderr=""),  # write
        ExecResult(exit_code=0, stdout="ok", stderr=""),  # the actual exec
        ExecResult(exit_code=0, stdout="", stderr=""),  # wipe
    ]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    assert len(exec_calls) == 3
    write_command, write_stdin = exec_calls[0][2], exec_calls[0][3]
    assert write_command[:2] == ["/bin/sh", "-c"]
    assert "auth.json" in " ".join(write_command)
    import base64 as _b64
    assert _b64.b64decode(write_stdin) == b'{"tokens": {"access_token": "fake-for-this-test"}}'

    main_command = exec_calls[1][2]
    assert main_command[0] == "codex"

    wipe_command = exec_calls[2][2]
    assert "shred" in " ".join(wipe_command)
    assert "auth.json" in " ".join(wipe_command)


def test_codex_wipes_credential_file_even_when_exec_fails(monkeypatch):
    monkeypatch.setenv("CODEX_AUTH_JSON_DEFAULT", '{"tokens": {}}')
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="codex")
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [
        ExecResult(exit_code=0, stdout="", stderr=""),  # write succeeds
        ExecResult(exit_code=1, stdout="", stderr="boom"),  # the actual exec fails
        ExecResult(exit_code=0, stdout="", stderr=""),  # wipe must still run
    ]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    assert len(exec_calls) == 3  # write, exec (failed), wipe -- wipe still ran
    assert "shred" in " ".join(exec_calls[2][2])


def test_codex_write_failure_dead_letters_without_exec_or_wipe(monkeypatch):
    monkeypatch.setenv("CODEX_AUTH_JSON_DEFAULT", '{"tokens": {}}')
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="codex")
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [ExecResult(exit_code=1, stdout="", stderr="disk full")]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    assert len(exec_calls) == 1  # only the failed write -- no exec, no wipe attempt
    dead_key = prefix("acme", "hq", "backend", "dead")
    assert len(r.lists.get(dead_key, [])) == 1


def test_codex_skips_file_transfer_entirely_when_no_credential_configured():
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="codex")
    fake_client, fake_sdk = _client(exec_result=ExecResult(exit_code=0, stdout="ok", stderr=""))

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    assert len(exec_calls) == 1  # no write, no wipe -- nothing configured to transfer


def test_agy_uses_its_own_file_path_and_env_var(monkeypatch):
    monkeypatch.setenv("AGY_AUTH_JSON_DEFAULT", '{"token": {"access_token": "fake-for-this-test"}}')
    r = FakeRespRedis()
    _setup(r, "acme", "hq", "backend", "alice", "Message", {"text": "hi"}, cli="agy")
    fake_client, fake_sdk = _client()
    fake_sdk.exec_results = [
        ExecResult(exit_code=0, stdout="", stderr=""),
        ExecResult(exit_code=0, stdout="ok", stderr=""),
        ExecResult(exit_code=0, stdout="", stderr=""),
    ]

    deliver_openshell(r, pod="acme", tenant="hq", agent="backend", client=fake_client)

    exec_calls = [c for c in fake_sdk.calls if c[0] == "exec"]
    write_command = exec_calls[0][2]
    assert "antigravity-oauth-token" in " ".join(write_command)
