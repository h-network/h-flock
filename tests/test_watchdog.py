import json
from datetime import datetime, timezone

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
        return list(self.roster)

    def hget(self, key, field):
        return self.roster.get(field)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)
        self.writes.append(("hset", key, mapping))

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
    assert captures == ["hq:architect", "hq:sme-2"]

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
    _watchdog(r).poll(now=NOW)
    assert prefix("acme", "hq", resource="alerts") not in r.streams

    r.hashes[_key("sme-2", "presence")]["state"] = "working"
    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786283999\nsme-2\t1786283580", "")
        if args[0] == "list-windows"
        else (0, "", ""),
    )
    _watchdog(r).poll(now=NOW)
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


def test_blocked_scrapes_every_tmux_pane_without_delivery_evidence(monkeypatch):
    r = WatchRedis()
    captures = []

    def tmux(*args, socket=None):
        if args[0] == "list-windows":
            return 0, "architect\t1786284000\nsme-2\t1786284000", ""
        captures.append(args[-1])
        pane = "[message from architect] do the work" if args[-1].endswith(":sme-2") else "ready"
        return 0, pane, ""

    monkeypatch.setattr(service, "run_tmux", tmux)
    _watchdog(r).poll(now=NOW)

    assert captures == ["hq:architect", "hq:sme-2"]
    assert r.hashes[_key("sme-2", "blocked")] == {
        "since": "2026-08-09T14:00:00.000Z",
        "stream_id": "",
    }
    alerts = r.streams[prefix("acme", "hq", resource="alerts")]
    alert = json.loads(alerts[0][1]["alert"])
    assert alert["kind"] == "blocked"
    assert alert["unsubmitted"] == "[message from "
    assert not any("egress" in str(write) for write in r.writes)

    monkeypatch.setattr(
        service,
        "run_tmux",
        lambda *args, socket=None: (0, "architect\t1786284000\nsme-2\t1786284000", "")
        if args[0] == "list-windows"
        else (0, "consumed", ""),
    )
    _watchdog(r).poll(now=NOW)
    assert _key("sme-2", "blocked") not in r.hashes


def test_credentials_warn_on_claude_refresh_expiry_and_codex_is_unknown(tmp_path, capsys):
    r = WatchRedis()
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


def test_disabled_main_exits_without_connecting(monkeypatch):
    monkeypatch.setenv("WATCHDOG_ENABLED", "0")
    monkeypatch.setattr(service.redis.Redis, "from_url", lambda url: (_ for _ in ()).throw(AssertionError))
    service.main()
