"""Tests for port_type: openshell's start_agent/stop_agent branches.

Exercise control/openers.py's real acknowledged/unknown accounting against
an injected fake OpenShell client -- these do NOT verify gateway
connectivity. See docs/LLD-port-openshell.md.
"""

from unittest.mock import patch

import pytest

from conftest import FakeRedis as RecordingRedis

from flock.bus import prefix
from flock.control import start_agent, stop_agent
from flock.openshell.client import OpenShellClient, OpenShellUnavailable
from flock.openshell.naming import sandbox_name, workspace_name


class FakeSandboxClient:
    def __init__(self):
        self.calls = []
        self.create_exc = None
        self.delete_exc = None

    def create(self, *, workspace, spec, name, labels):
        self.calls.append(("create", workspace, name))
        if self.create_exc:
            raise self.create_exc

    def wait_ready(self, name, *, workspace, timeout_seconds):
        self.calls.append(("wait_ready", workspace, name))
        return None

    def delete(self, name, *, workspace):
        self.calls.append(("delete", workspace, name))
        if self.delete_exc:
            raise self.delete_exc
        return True

    def close(self):
        pass


class FakeWorkspaceClient:
    def get(self, name):
        return object()

    def create(self, name):
        return object()


def _client(create_exc=None, delete_exc=None):
    fake = FakeSandboxClient()
    fake.create_exc = create_exc
    fake.delete_exc = delete_exc
    return OpenShellClient("acme-hq", sandbox_client=fake, workspace_client=FakeWorkspaceClient()), fake


def test_start_agent_openshell_publishes_state_and_creates_sandbox():
    events = []
    r = RecordingRedis(events)
    wrapped, fake_sdk = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        start_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "cli": "codex", "port_type": "openshell"}},
            replace_window=lambda agent: pytest.fail("openshell must never call replace_window"),
        )

    assert ("set", prefix("acme", "hq", "dave", "launch"), "codex") in events
    assert ("hset", prefix("acme", "hq", resource="roster"), "dave", "openshell") in events
    assert ("create", workspace_name("acme", "hq"), sandbox_name("dave")) in fake_sdk.calls


def test_start_agent_openshell_defaults_cli_to_claude():
    events = []
    r = RecordingRedis(events)
    wrapped, _ = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        start_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "port_type": "openshell"}},
            replace_window=lambda agent: None,
        )

    assert ("set", prefix("acme", "hq", "dave", "launch"), "claude") in events


def test_start_agent_openshell_sandbox_failure_is_incomplete_not_silent(capsys):
    events = []
    r = RecordingRedis(events)
    wrapped, _ = _client(create_exc=OpenShellUnavailable("gateway down"))

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        with pytest.raises(OpenShellUnavailable):
            start_agent(
                r,
                pod="acme",
                tenant="hq",
                envelope={"payload": {"agent": "dave", "port_type": "openshell"}},
                replace_window=lambda agent: None,
            )
    # Roster/launch were already published before the sandbox create was
    # attempted -- the logged reason must say so, not swallow it like the
    # prior attempt's bare `except Exception: pass` did for teardown.
    logged = capsys.readouterr().out
    assert "creating the sandbox" in logged
    assert "acknowledged: launch published, roster row published" in logged
    assert ("hset", prefix("acme", "hq", resource="roster"), "dave", "openshell") in events


def test_stop_agent_openshell_deletes_sandbox_not_window():
    events = []
    r = RecordingRedis(events, roster_port_type="openshell")
    wrapped, fake_sdk = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        stop_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave"}},
            kill_window=lambda agent: pytest.fail("openshell must never call kill_window"),
        )

    assert ("delete", workspace_name("acme", "hq"), sandbox_name("dave")) in fake_sdk.calls
    assert ("hdel", prefix("acme", "hq", resource="roster"), "dave") in events


def test_stop_agent_openshell_delete_failure_is_reported_not_swallowed(capsys):
    events = []
    r = RecordingRedis(events, roster_port_type="openshell")
    wrapped, _ = _client(delete_exc=OpenShellUnavailable("gateway down"))

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        with pytest.raises(OpenShellUnavailable):
            stop_agent(
                r,
                pod="acme",
                tenant="hq",
                envelope={"payload": {"agent": "dave"}},
                kill_window=lambda agent: None,
            )

    # The prior attempt on this ticket used a bare `except Exception: pass`
    # here, silently reporting a failed teardown as clean. This must not.
    logged = capsys.readouterr().out
    assert "deleting the sandbox" in logged


# -- Profile support (ticket f6b9f6fe) ---------------------------------------

def test_start_agent_openshell_publishes_profile_when_supplied():
    events = []
    r = RecordingRedis(events)
    wrapped, _ = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        start_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "port_type": "openshell", "profile": "work"}},
            replace_window=lambda agent: None,
        )

    assert ("set", prefix("acme", "hq", "dave", "profile"), "work") in events


def test_start_agent_openshell_omits_profile_when_not_supplied():
    events = []
    r = RecordingRedis(events)
    wrapped, _ = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        start_agent(
            r,
            pod="acme",
            tenant="hq",
            envelope={"payload": {"agent": "dave", "port_type": "openshell"}},
            replace_window=lambda agent: None,
        )

    profile_events = [e for e in events if e[0] == "set" and e[1] == prefix("acme", "hq", "dave", "profile")]
    assert profile_events == []


def test_start_agent_openshell_rejects_unknown_profile():
    events = []
    r = RecordingRedis(events)
    r.sadd(prefix("acme", "hq", resource="accounts"), "default", "work")
    wrapped, _ = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        with pytest.raises(ValueError, match="unknown account"):
            start_agent(
                r,
                pod="acme",
                tenant="hq",
                envelope={"payload": {"agent": "dave", "port_type": "openshell", "profile": "nope"}},
                replace_window=lambda agent: None,
            )


def test_start_agent_openshell_rejects_invalid_profile_type():
    # Same shape as the pre-existing (tmux) validation this mirrors: a
    # truthy non-string value fails inside prefix()'s own segment check
    # with KeyError, before ever reaching the "must be a segment string"
    # ValueError branch (which only fires for a falsy-but-not-None/""
    # value). Testing the real behavior, not an assumed one.
    events = []
    r = RecordingRedis(events)
    wrapped, _ = _client()

    with patch("flock.openshell.OpenShellClient", return_value=wrapped):
        with pytest.raises(KeyError):
            start_agent(
                r,
                pod="acme",
                tenant="hq",
                envelope={"payload": {"agent": "dave", "port_type": "openshell", "profile": 123}},
                replace_window=lambda agent: None,
            )
