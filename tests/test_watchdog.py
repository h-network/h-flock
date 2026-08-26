from conftest import FakeRedis as WatchRedis
import json
from datetime import datetime, timezone

import pytest

from flock.bus import parse, prefix
from flock.watchdog import service
from flock.watchdog.service import Watchdog


NOW = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)



def _key(agent, resource):
    return prefix("acme", "hq", agent, resource)


def _watchdog(r):
    return Watchdog(r, pod="acme", tenant="hq", session_name="hq")


def _stalled_agent(r, agent="sme-2", *, state="idle"):
    r.lists[_key(agent, "tasks.doing")] = [
        json.dumps(
            {
                "id": "ticket-1",
                "title": "review the auth change",
                "started_ts": "2026-08-09T13:46:00Z",
            }
        )
    ]
    r.hashes[_key(agent, "presence")] = {
        "state": state,
        "last_activity": "2026-08-09T13:51:00Z" if state != "unknown" else "",
    }


def test_stall_requires_old_ticket_nonworking_presence_and_silent_window(monkeypatch, capsys):
    r = WatchRedis()
    _stalled_agent(r)
    captures = []

    def tmux(*args, socket=None):
        if args[0] == "list-windows":
            return 0, "architect\t1786283999\nsme-2\t1786283580", ""
        captures.append(args[-1])
        return 0, "healthy pane", ""

    monkeypatch.setattr(service, "run_tmux", tmux)
    watchdog = _watchdog(r)
    watchdog.poll(now=NOW)

    alert = json.loads(r.streams[prefix("acme", "hq", resource="alerts")][0][1]["alert"])
    assert alert == {
        "v": 1,
        "ts": "2026-08-09T14:00:00.000Z",
        "kind": "stalled",
        "writer": "watchdog",
        "agent": "sme-2",
        "ticket": "review the auth change",
        "doing_age_s": 840,
        "no_activity_s": 540,
        "no_output_s": 420,
        "unchecked": [],
    }
    assert json.loads(capsys.readouterr().out) == alert
    assert captures == []

    watchdog.poll(now=NOW)
    assert len(r.streams[prefix("acme", "hq", resource="alerts")]) == 1


def test_printing_window_or_working_presence_suppresses_stall(monkeypatch):
    r = WatchRedis()
    _stalled_agent(r)
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999\nsme-2\t1786283990", "")
        if args[0] == "list-windows"
        else (0, "", ""),
    )
    watchdog = _watchdog(r)
    watchdog.poll(now=NOW)
    assert prefix("acme", "hq", resource="alerts") not in r.streams

    r.hashes[_key("sme-2", "presence")]["state"] = "working"
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999\nsme-2\t1786283580", "")
        if args[0] == "list-windows"
        else (0, "", ""),
    )
    watchdog.poll(now=NOW)
    assert prefix("acme", "hq", resource="alerts") not in r.streams


def test_unknown_activity_is_named_as_unchecked(monkeypatch):
    r = WatchRedis()
    _stalled_agent(r, state="unknown")
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999\nsme-2\t1786283580", "")
        if args[0] == "list-windows"
        else (0, "", ""),
    )
    _watchdog(r).poll(now=NOW)
    alert = json.loads(r.streams[prefix("acme", "hq", resource="alerts")][0][1]["alert"])
    assert alert["no_activity_s"] is None
    assert alert["unchecked"] == ["activity"]


def test_missing_window_is_reported_for_otherwise_stalled_agent(monkeypatch):
    r = WatchRedis()
    _stalled_agent(r)
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999", ""),
    )

    _watchdog(r).poll(now=NOW)

    alert = json.loads(r.streams[prefix("acme", "hq", resource="alerts")][0][1]["alert"])
    assert alert["kind"] == "stalled"
    assert alert["agent"] == "sme-2"
    assert alert["no_output_s"] is None
    assert alert["window_missing"] is True


def test_blocked_alert_reads_router_verdict_without_scraping(monkeypatch):
    r = WatchRedis()
    r.hashes[_key("sme-2", "blocked")] = {
        "since": "2026-08-09T13:53:00Z",
        "stream_id": "delivery-1",
    }
    calls = []
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: calls.append(args) or (0, "architect\t1786284000\nsme-2\t1786284000", ""),
    )
    watchdog = _watchdog(r)
    watchdog.poll(now=NOW)

    assert all(call[0] == "list-windows" for call in calls)
    alerts = r.streams[prefix("acme", "hq", resource="alerts")]
    alert = json.loads(alerts[0][1]["alert"])
    assert alert == {
        "v": 1,
        "ts": "2026-08-09T14:00:00.000Z",
        "kind": "blocked",
        "writer": "watchdog",
        "agent": "sme-2",
        "since": "2026-08-09T13:53:00Z",
        "stream_id": "delivery-1",
        "unconsumed_s": 420,
    }
    assert not any("egress" in str(write) for write in r.writes)

    watchdog.poll(now=NOW)
    assert len(r.streams[prefix("acme", "hq", resource="alerts")]) == 1


def test_stall_alert_includes_blocked_verdict(monkeypatch):
    r = WatchRedis()
    _stalled_agent(r)
    r.hashes[_key("sme-2", "blocked")] = {
        "since": "2026-08-09T13:53:00Z",
        "stream_id": "delivery-1",
    }
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999\nsme-2\t1786283580", ""),
    )
    _watchdog(r).poll(now=NOW)
    alert = json.loads(r.streams[prefix("acme", "hq", resource="alerts")][0][1]["alert"])
    assert alert["kind"] == "stalled"
    assert alert["blocked"] == {
        "since": "2026-08-09T13:53:00Z",
        "stream_id": "delivery-1",
        "unconsumed_s": 420,
    }


def _quiet_windows(now=NOW):
    """A list-windows reply with fresh activity, so the 3-signal stall check
    (§2) never fires and doesn't contaminate a doing-duration assertion."""
    ts = int(now.timestamp())
    return lambda *args, socket=None: (
        (0, f"architect\t{ts}\nsme-2\t{ts}", "") if args[0] == "list-windows" else (0, "", "")
    )


def _doing_agent(r, agent="sme-2", *, started="2026-08-09T13:45:00Z", ticket_id="ticket-1", title="review the auth change"):
    r.lists[_key(agent, "tasks.doing")] = [
        json.dumps({"id": ticket_id, "title": title, "started_ts": started})
    ]


def _lead(r, name="architect"):
    r.values[prefix("acme", "hq", resource="lead")] = name


def test_doing_duration_messages_the_lead_directly_not_the_alerts_stream(monkeypatch):
    r = WatchRedis()
    _doing_agent(r)
    _lead(r)
    kicks = []
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))

    _watchdog(r).poll(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams
    ingress = r.lists[_key("architect", "ingress")]
    assert len(ingress) == 1
    envelope = parse(ingress[0])
    assert envelope["kind"] == "Message"
    assert envelope["l2"]["source"] == "watchdog"
    assert envelope["l2"]["destination"] == "architect"
    assert envelope["payload"]["text"] == (
        '[alert from watchdog] sme-2 has been working on '
        '"review the auth change" for 15 min, request an update'
    )
    assert kicks == [["flock.port", "architect"]]


def test_doing_duration_does_not_fire_before_fifteen_minutes(monkeypatch):
    r = WatchRedis()
    _doing_agent(r, started="2026-08-09T13:46:00Z")  # 840s old, under the 900s default
    _lead(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: (_ for _ in ()).throw(AssertionError("should not kick")))

    _watchdog(r).poll(now=NOW)

    assert _key("architect", "ingress") not in r.lists


def test_doing_duration_does_not_repeat_within_the_same_threshold_crossing(monkeypatch):
    r = WatchRedis()
    _doing_agent(r)
    _lead(r)
    kicks = []
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog = _watchdog(r)

    watchdog.poll(now=NOW)
    watchdog.poll(now=NOW)
    from datetime import timedelta
    watchdog.poll(now=NOW + timedelta(seconds=60))

    assert len(kicks) == 1
    assert len(r.lists[_key("architect", "ingress")]) == 1


def test_doing_duration_re_alerts_at_the_next_threshold_crossing(monkeypatch):
    from datetime import timedelta

    r = WatchRedis()
    _doing_agent(r)
    _lead(r)
    kicks = []
    watchdog = _watchdog(r)

    monkeypatch.setattr(service, "run_tmux", _quiet_windows(NOW))
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog.poll(now=NOW)
    assert len(kicks) == 1

    later = NOW + timedelta(seconds=900)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows(later))
    watchdog.poll(now=later)
    assert len(kicks) == 2
    envelope = parse(r.lists[_key("architect", "ingress")][-1])
    assert '30 min' in envelope["payload"]["text"]


def test_doing_duration_different_ticket_resets_and_re_alerts(monkeypatch):
    r = WatchRedis()
    _doing_agent(r)
    _lead(r)
    kicks = []
    watchdog = _watchdog(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog.poll(now=NOW)
    assert len(kicks) == 1

    _doing_agent(r, started="2026-08-09T13:45:00Z", ticket_id="ticket-2", title="fix the flaky test")
    watchdog.poll(now=NOW)
    assert len(kicks) == 2


def test_doing_duration_does_nothing_without_a_configured_lead(monkeypatch):
    r = WatchRedis()
    _doing_agent(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: (_ for _ in ()).throw(AssertionError("should not kick")))

    _watchdog(r).poll(now=NOW)

    assert _key("architect", "ingress") not in r.lists


def _todo_agent(r, agent="sme-2", *, created="2026-08-09T13:55:00Z", ticket_id="ticket-1", title="pick up the auth review", append=False):
    entry = json.dumps({"id": ticket_id, "title": title, "created_ts": created})
    key = _key(agent, "tasks.todo")
    if append:
        r.lists.setdefault(key, []).append(entry)
    else:
        r.lists[key] = [entry]


def test_todo_duration_messages_the_lead_directly_not_the_alerts_stream(monkeypatch):
    r = WatchRedis()
    _todo_agent(r)
    _lead(r)
    kicks = []
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))

    _watchdog(r).poll(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams
    ingress = r.lists[_key("architect", "ingress")]
    assert len(ingress) == 1
    envelope = parse(ingress[0])
    assert envelope["l2"]["source"] == "watchdog"
    assert envelope["l2"]["destination"] == "architect"
    assert envelope["payload"]["text"] == (
        '[alert from watchdog] sme-2 has an unpicked ticket '
        '"pick up the auth review" waiting 5 min'
    )
    assert kicks == [["flock.port", "architect"]]


def test_todo_duration_does_not_fire_before_five_minutes(monkeypatch):
    r = WatchRedis()
    _todo_agent(r, created="2026-08-09T13:56:00Z")  # 240s old, under the 300s default
    _lead(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: (_ for _ in ()).throw(AssertionError("should not kick")))

    _watchdog(r).poll(now=NOW)

    assert _key("architect", "ingress") not in r.lists


def test_todo_duration_does_not_repeat_within_the_same_threshold_crossing(monkeypatch):
    r = WatchRedis()
    _todo_agent(r)
    _lead(r)
    kicks = []
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog = _watchdog(r)

    watchdog.poll(now=NOW)
    watchdog.poll(now=NOW)
    from datetime import timedelta
    watchdog.poll(now=NOW + timedelta(seconds=60))

    assert len(kicks) == 1
    assert len(r.lists[_key("architect", "ingress")]) == 1


def test_todo_duration_re_alerts_at_the_next_threshold_crossing(monkeypatch):
    from datetime import timedelta

    r = WatchRedis()
    _todo_agent(r)
    _lead(r)
    kicks = []
    watchdog = _watchdog(r)

    monkeypatch.setattr(service, "run_tmux", _quiet_windows(NOW))
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog.poll(now=NOW)
    assert len(kicks) == 1

    later = NOW + timedelta(seconds=300)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows(later))
    watchdog.poll(now=later)
    assert len(kicks) == 2
    envelope = parse(r.lists[_key("architect", "ingress")][-1])
    assert "10 min" in envelope["payload"]["text"]


def test_todo_duration_different_ticket_resets_and_re_alerts(monkeypatch):
    r = WatchRedis()
    _todo_agent(r)
    _lead(r)
    kicks = []
    watchdog = _watchdog(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))
    watchdog.poll(now=NOW)
    assert len(kicks) == 1

    _todo_agent(r, created="2026-08-09T13:55:00Z", ticket_id="ticket-2", title="fix the flaky test")
    watchdog.poll(now=NOW)
    assert len(kicks) == 2


def test_todo_duration_tracks_each_queued_ticket_independently(monkeypatch):
    r = WatchRedis()
    _todo_agent(r, created="2026-08-09T13:55:00Z", ticket_id="ticket-1", title="old enough")
    _todo_agent(r, created="2026-08-09T13:58:00Z", ticket_id="ticket-2", title="too new", append=True)
    _lead(r)
    kicks = []
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: kicks.append(args))

    _watchdog(r).poll(now=NOW)

    assert len(kicks) == 1
    envelope = parse(r.lists[_key("architect", "ingress")][-1])
    assert "old enough" in envelope["payload"]["text"]


def test_todo_duration_drops_state_for_a_ticket_no_longer_in_todo(monkeypatch):
    r = WatchRedis()
    _todo_agent(r)
    _lead(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: None)
    watchdog = _watchdog(r)
    watchdog.poll(now=NOW)
    assert r.hashes[_key("sme-2", "todo.alerted")] == {"ticket-1": "1"}

    r.lists[_key("sme-2", "tasks.todo")] = []  # taken, cancelled, or deleted
    watchdog.poll(now=NOW)
    assert r.hashes[_key("sme-2", "todo.alerted")] == {}


def test_todo_duration_does_nothing_without_a_configured_lead(monkeypatch):
    r = WatchRedis()
    _todo_agent(r)
    monkeypatch.setattr(service, "run_tmux", _quiet_windows())
    monkeypatch.setattr(service.subprocess, "Popen", lambda args: (_ for _ in ()).throw(AssertionError("should not kick")))

    _watchdog(r).poll(now=NOW)

    assert _key("architect", "ingress") not in r.lists


def test_credentials_warn_on_claude_refresh_expiry_and_codex_is_unknown(tmp_path, capsys):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("sme-2", "launch")] = "codex"
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-08-12T14:00:00Z"}})
    )
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "auth.json").write_text("{}")

    watchdog = Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path)
    watchdog.check_credentials(now=NOW)

    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[prefix("acme", "hq", resource="alerts")]]
    assert [(alert["cli"], alert["status"]) for alert in alerts] == [
        ("claude", "expiring"),
        ("codex", "unknown"),
    ]
    assert all(alert["account"] == "default" for alert in alerts)
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_profile_codex_is_unknown_even_without_an_auth_file(tmp_path, capsys):
    r = WatchRedis()
    r.values[_key("sme-2", "launch")] = "codex"
    r.values[_key("sme-2", "profile")] = "work"
    (tmp_path / ".codex-work").mkdir()
    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[prefix("acme", "hq", resource="alerts")]]
    assert any(
        alert["account"] == "work" and alert["cli"] == "codex" and alert["status"] == "absent"
        for alert in alerts
    )
    capsys.readouterr()


def test_claude_profile_token_is_authenticated_without_credentials_file(
    tmp_path, monkeypatch, capsys
):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("architect", "profile")] = "work"
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_WORK", "token-authenticated")

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams
    assert r.hashes.get(prefix("acme", "hq", resource="credential.alerted"), {}) == {}
    assert capsys.readouterr().out == ""


def test_claude_without_token_or_credentials_still_alerts_absent(tmp_path, monkeypatch, capsys):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    monkeypatch.delenv("CLAUDE_OAUTH_TOKEN_DEFAULT", raising=False)

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    alert = json.loads(r.streams[prefix("acme", "hq", resource="alerts")][0][1]["alert"])
    assert alert["status"] == "absent"
    capsys.readouterr()


def test_provider_agent_needs_no_vendor_credential_and_clears_stale_status(tmp_path):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("architect", "provider")] = "local-vllm"
    alerted_key = prefix("acme", "hq", resource="credential.alerted")
    r.hashes[alerted_key] = {"default:claude": "absent"}

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams
    assert r.hashes[alerted_key] == {}


def test_credential_alert_retracted_when_credential_recovers(tmp_path, monkeypatch, capsys):
    """Build 105 §1: when a credential recovers, watchdog emits status=present and clears alerted hash."""
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    monkeypatch.delenv("CLAUDE_OAUTH_TOKEN_DEFAULT", raising=False)

    watchdog = Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path)
    alerted_key = prefix("acme", "hq", resource="credential.alerted")
    alerts_key = prefix("acme", "hq", resource="alerts")

    # Pass 1: Absent credential -> alerts absent
    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert len(alerts) == 1
    assert alerts[0]["status"] == "absent"
    assert alerts[0]["cli"] == "claude"
    assert alerts[0]["account"] == "default"
    assert r.hashes[alerted_key] == {"default:claude": "absent"}

    # Pass 2: Login completes -> valid credentials file created with healthy refresh expiry
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-09-12T14:00:00Z"}})
    )

    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert len(alerts) == 2
    assert alerts[1]["status"] == "present"
    assert alerts[1]["cli"] == "claude"
    assert alerts[1]["account"] == "default"
    assert alerts[1]["expires_ts"] == "2026-09-12T14:00:00.000Z"
    assert r.hashes.get(alerted_key, {}) == {}

    # Pass 3: Steady state -> no further alerts emitted
    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert len(alerts) == 2
    assert r.hashes.get(alerted_key, {}) == {}


def test_credential_alert_retracted_from_expiring_when_token_refreshed(tmp_path, capsys):
    """Build 105 §1: when an expiring credential is refreshed, watchdog emits status=present."""
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-08-12T14:00:00Z"}})
    )

    watchdog = Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path)
    alerted_key = prefix("acme", "hq", resource="credential.alerted")
    alerts_key = prefix("acme", "hq", resource="alerts")

    # Pass 1: Expiring (3 days from NOW) -> alerts expiring
    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert len(alerts) == 1
    assert alerts[0]["status"] == "expiring"
    assert r.hashes[alerted_key] == {"default:claude": "expiring"}

    # Pass 2: Refreshed -> healthy expiry 30 days away
    (claude / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-09-09T14:00:00Z"}})
    )
    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert len(alerts) == 2
    assert alerts[1]["status"] == "present"
    assert alerts[1]["expires_ts"] == "2026-09-09T14:00:00.000Z"
    assert r.hashes.get(alerted_key, {}) == {}

    # Pass 3: Steady state -> no further alerts
    watchdog.check_credentials(now=NOW)
    assert len(r.streams[alerts_key]) == 2


def test_stall_failure_does_not_disable_blocked_check(monkeypatch, capsys):
    r = WatchRedis()
    r.hashes[_key("sme-2", "blocked")] = {
        "since": "2026-08-09T13:53:00Z",
        "stream_id": "delivery-1",
    }
    watchdog = _watchdog(r)
    monkeypatch.setattr(watchdog, "_window_activity", lambda: {})
    monkeypatch.setattr(watchdog, "_check_stalls", lambda *args: (_ for _ in ()).throw(RuntimeError("bad board")))

    watchdog.poll(now=NOW)

    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0] == {
        "module": "watchdog",
        "event": "error",
        "writer": "watchdog",
        "job": "stalls",
        "reason": "RuntimeError: bad board",
    }
    assert any(record.get("kind") == "blocked" for record in output)


def test_observation_failure_does_not_disable_due_credential_check(monkeypatch, capsys):
    calls = []

    class FailingWatchdog:
        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            calls.append("poll")
            raise RuntimeError("bad observations")

        def check_credentials(self):
            calls.append("credentials")

        def _agents(self):
            # The observers moved here from the switch and are polled with the
            # roster; a double standing in for Watchdog needs this too.
            return set()

        _error = staticmethod(Watchdog._error)

    monkeypatch.delenv("WATCHDOG_ENABLED", raising=False)
    monkeypatch.setenv("WATCHDOG_INTERVAL", "0")
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setattr(service, "Watchdog", FailingWatchdog)
    monkeypatch.setattr(service.redis.Redis, "from_url", lambda url: object())
    monkeypatch.setattr(service.time, "monotonic", lambda: 0)
    monkeypatch.setattr(service.time, "sleep", lambda interval: (_ for _ in ()).throw(StopIteration))

    with pytest.raises(StopIteration):
        service.main()

    assert calls == ["poll", "credentials"]
    error = json.loads(capsys.readouterr().out)
    assert error["job"] == "observations"
    assert error["reason"] == "RuntimeError: bad observations"


def test_disabled_alerting_still_connects_because_observers_need_redis(monkeypatch):
    """⚠ This asserted the OPPOSITE until 2026-08-19.

    It pinned "WATCHDOG_ENABLED=0 means main() exits without connecting", which
    was correct while the flag only governed alerts. The observers now live in
    this process and read Redis, so exiting early silences telemetry rather than
    alerts. The connection is now the evidence that they still run.
    """
    connected = []
    monkeypatch.setenv("WATCHDOG_ENABLED", "0")
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setattr(service.redis.Redis, "from_url",
                        lambda url: connected.append(url) or object())
    monkeypatch.setattr(service.time, "sleep",
                        lambda s: (_ for _ in ()).throw(StopIteration))
    monkeypatch.setattr(service.time, "monotonic", lambda: 0)
    with pytest.raises(StopIteration):
        service.main()
    assert connected, "observers need Redis even with alerting off"


def test_agy_is_unknown_because_its_expiry_is_an_access_token(tmp_path, capsys):
    """Only claude records a refresh-token expiry.

    ⚠ agy's `token.expiry` tracks its ACCESS token. Measured: the same file read
    hours apart showed the value moved forward while the login stayed valid — the
    CLI refreshes it itself. Alerting on it fires constantly and correctly, which
    is the cry-wolf failure the credential check exists to avoid.

    It produced a real alert on the lab tenant saying "expiring" about a token
    that had already passed and an account that was working fine.
    """
    agy = tmp_path / ".gemini" / "antigravity-cli"
    agy.mkdir(parents=True)
    (agy / "antigravity-oauth-token").write_text(
        json.dumps({"token": {"access_token": "x", "refresh_token": "y",
                              "expiry": "2020-01-01T00:00:00Z"}})
    )

    r = WatchRedis()
    r.values[_key("architect", "launch")] = "agy"
    Watchdog(r, pod="acme", tenant="hq", session_name="hq",
             home_root=tmp_path).check_credentials(now=NOW)

    alerts = [json.loads(f["alert"]) for _, f in r.streams.get(prefix("acme", "hq", resource="alerts"), [])]
    agy_alerts = [a for a in alerts if a.get("cli") == "agy"]
    assert agy_alerts, "agy should still be reported"
    assert agy_alerts[0]["status"] == "unknown", "never 'expiring' from an access token"


def test_missing_credentials_alert_once_per_account_in_use_and_clear_on_reseed(tmp_path):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("architect", "profile")] = "work"
    r.values[_key("sme-2", "launch")] = "claude"
    r.values[_key("sme-2", "profile")] = "work"
    watchdog = Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path)

    watchdog.check_credentials(now=NOW)
    watchdog.check_credentials(now=NOW)
    alerts_key = prefix("acme", "hq", resource="alerts")
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert [(alert["account"], alert["cli"], alert["status"]) for alert in alerts] == [
        ("work", "claude", "absent")
    ]

    credentials = tmp_path / ".claude-work" / ".credentials.json"
    credentials.parent.mkdir()
    credentials.write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-09-12T14:00:00Z"}})
    )
    watchdog.check_credentials(now=NOW)
    watchdog.check_credentials(now=NOW)
    alerts = [json.loads(fields["alert"]) for _, fields in r.streams[alerts_key]]
    assert [(alert["account"], alert["cli"], alert["status"]) for alert in alerts] == [
        ("work", "claude", "absent"),
        ("work", "claude", "present"),
    ]
    assert r.hashes[prefix("acme", "hq", resource="credential.alerted")] == {}


def test_missing_credentials_alert_for_each_cli_account_in_use(tmp_path):
    r = WatchRedis()
    r.roster["sme-3"] = "tmux"
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("sme-2", "launch")] = "codex"
    r.values[_key("sme-3", "launch")] = "agy"

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    alerts = [
        json.loads(fields["alert"])
        for _, fields in r.streams[prefix("acme", "hq", resource="alerts")]
    ]
    assert {(alert["cli"], alert["status"]) for alert in alerts} == {
        ("agy", "absent"),
        ("claude", "absent"),
        ("codex", "absent"),
    }


def test_unused_profile_directory_does_not_alert(tmp_path):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    default = tmp_path / ".claude"
    default.mkdir()
    (default / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": "2026-09-12T14:00:00Z"}})
    )
    (tmp_path / ".claude-unused").mkdir()

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams


def test_alerting_disabled_still_runs_the_observers(monkeypatch, capsys):
    """⚠ WATCHDOG_ENABLED silences ALERTS, not telemetry.

    Until the observers moved into this process the flag only quietened stall
    and blocked alerts. Returning early would now also stop ActivityTailer,
    PresenceSampler and DeliveryVerifier — presence reads `unknown` forever, the
    activity stream stays empty, and clients/telegram/bot.py loses its progress
    indicator. Found by api reviewing build 77.
    """
    polled = []

    class Observer:
        def __init__(self, name):
            self.name = name

        def poll(self, agents):
            polled.append(self.name)
            raise StopIteration        # one pass, then out of the loop

    class QuietWatchdog:
        def __init__(self, *a, **kw):
            pass

        def poll(self):
            polled.append("ALERT")     # must never appear

        def check_credentials(self):
            polled.append("CREDENTIALS")

        def _agents(self):
            return {"sme-2"}

        _error = staticmethod(Watchdog._error)

    monkeypatch.setenv("WATCHDOG_ENABLED", "0")
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setattr(service, "Watchdog", QuietWatchdog)
    monkeypatch.setattr(service.redis.Redis, "from_url", lambda url: object())
    monkeypatch.setattr(service, "ActivityTailer", lambda *a, **kw: Observer("activity"))
    monkeypatch.setattr(service, "PresenceSampler", lambda *a, **kw: Observer("presence"))
    monkeypatch.setattr(service, "DeliveryVerifier", lambda *a, **kw: Observer("verify"))
    monkeypatch.setattr(service.time, "monotonic", lambda: 0)
    monkeypatch.setattr(service.time, "sleep",
                        lambda s: (_ for _ in ()).throw(StopIteration))

    with pytest.raises(StopIteration):
        service.main()

    assert "activity" in polled, "observers must run with alerting off"
    assert "ALERT" not in polled, "alerting must be silent"
    assert "CREDENTIALS" not in polled
    assert '"event":"alerting_disabled"' in capsys.readouterr().out
