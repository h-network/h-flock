import json
from datetime import datetime, timezone

import pytest

from flock.bus import prefix
from flock.watchdog import service
from flock.watchdog.service import Watchdog


NOW = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)


class WatchRedis:
    def __init__(self):
        self.roster = {"architect": "tmux", "sme-2": "tmux", "api": "api", "host": "control"}
        self.values = {}
        self.hashes = {}
        self.lists = {}
        self.streams = {}
        self.writes = []

    def hkeys(self, key):
        if key in self.hashes:
            return list(self.hashes[key])
        return list(self.roster)

    def hget(self, key, field):
        if key in self.hashes:
            return self.hashes[key].get(field)
        return self.roster.get(field)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, key, field=None, value=None, mapping=None):
        if mapping is not None:
            self.hashes.setdefault(key, {}).update(mapping)
            written = mapping
        else:
            self.hashes.setdefault(key, {})[field] = value
            written = {field: value}
        self.writes.append(("hset", key, written))

    def hdel(self, key, *fields):
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)
        self.writes.append(("hdel", key, fields))

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.writes.append(("set", key, value, ex))

    def delete(self, key):
        self.hashes.pop(key, None)
        self.writes.append(("delete", key))

    def lindex(self, key, index):
        values = self.lists.get(key, [])
        return values[index] if values else None

    def xrange(self, key, min="-", max="+"):
        return self.streams.get(key, [])

    def xadd(self, key, fields, maxlen=None, approximate=None):
        cursor = f"{len(self.streams.get(key, [])) + 1}-0"
        self.streams.setdefault(key, []).append((cursor, dict(fields)))
        self.writes.append(("xadd", key, fields))
        return cursor


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


def test_provider_agent_needs_no_vendor_credential_and_clears_stale_status(tmp_path):
    r = WatchRedis()
    r.values[_key("architect", "launch")] = "claude"
    r.values[_key("architect", "provider")] = "local-vllm"
    alerted_key = prefix("acme", "hq", resource="credential.alerted")
    r.hashes[alerted_key] = {"default:claude": "absent"}

    Watchdog(r, pod="acme", tenant="hq", session_name="hq", home_root=tmp_path).check_credentials(now=NOW)

    assert prefix("acme", "hq", resource="alerts") not in r.streams
    assert r.hashes[alerted_key] == {}


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


def test_disabled_main_exits_without_connecting(monkeypatch):
    monkeypatch.setenv("WATCHDOG_ENABLED", "0")
    monkeypatch.setattr(service.redis.Redis, "from_url", lambda url: (_ for _ in ()).throw(AssertionError))
    service.main()


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
    assert len(r.streams[alerts_key]) == 1
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
