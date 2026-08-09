import json
from pathlib import Path

from flock.bus import prefix
from flock.router.activity import ActivityTailer


class ActivityRedis:
    def __init__(self, agents=("sme-2",)):
        self.values = {}
        self.streams = {}
        self.agents = agents

    def hkeys(self, key):
        return self.agents

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def xadd(self, key, fields, *, maxlen, approximate):
        assert maxlen == 1000
        assert approximate is True
        self.streams.setdefault(key, []).append(fields)


def _events(r, agent="sme-2"):
    key = prefix("acme", "hq", agent, "activity")
    return [json.loads(entry["event"]) for entry in r.streams.get(key, [])]


def _write_lines(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_claude_tailer_reads_only_new_bytes_and_never_emits_content(tmp_path):
    r = ActivityRedis()
    session = tmp_path / ".claude" / "projects" / "-workdir-sme-2" / "one.jsonl"
    _write_lines(
        session,
        [
            {"type": "user", "timestamp": "2026-08-09T10:00:00Z", "message": "private prompt"},
            {
                "type": "assistant",
                "timestamp": "2026-08-09T10:00:01Z",
                "message": {
                    "content": [
                        {"type": "text", "text": "private response"},
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cat /workdir/sme-2/secrets.env"},
                        },
                    ]
                },
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": "private tool output"}]},
            },
        ],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)

    tailer.poll()
    assert _events(r) == [
        {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:00Z", "kind": "input"},
        {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:01Z", "kind": "output"},
        {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:01Z", "kind": "tool", "tool": "Bash"},
    ]
    serialized = json.dumps(r.streams)
    for secret in ("private prompt", "private response", "private tool output", "cat ", "secrets.env", "/workdir"):
        assert secret not in serialized

    offset_key = prefix("acme", "hq", "sme-2", "activity.offset")
    assert json.loads(r.values[offset_key])["offset"] == session.stat().st_size
    tailer.poll()
    assert len(_events(r)) == 3

    with session.open("a") as output:
        output.write('{"type":"assistant","message":{"content":[{"type":"tool_use",')
    tailer.poll()
    assert len(_events(r)) == 3

    with session.open("a") as output:
        output.write('"name":"Read","input":{"file_path":"/private"}}]}}\n')
    tailer.poll()
    assert _events(r)[-1]["kind"] == "tool"
    assert _events(r)[-1]["tool"] == "Read"
    assert "/private" not in json.dumps(r.streams)


def test_newest_session_starts_at_zero_instead_of_reusing_old_offset(tmp_path):
    r = ActivityRedis()
    directory = tmp_path / ".claude" / "projects" / "-workdir-sme-2"
    old = directory / "old.jsonl"
    new = directory / "new.jsonl"
    _write_lines(old, [{"type": "user", "timestamp": "old"}])
    old.touch()
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    _write_lines(new, [{"type": "assistant", "timestamp": "new", "message": {"content": "answer"}}])
    new.touch()
    tailer.poll()

    assert [event["kind"] for event in _events(r)] == ["input", "output"]
    state = json.loads(r.values[prefix("acme", "hq", "sme-2", "activity.offset")])
    assert state == {"path": str(new), "offset": new.stat().st_size}


def test_codex_profile_session_reduces_messages_and_tool_calls(tmp_path):
    r = ActivityRedis()
    r.values[prefix("acme", "hq", "sme-2", "profile")] = "work"
    session = tmp_path / ".codex-work" / "sessions" / "2026" / "08" / "rollout-one.jsonl"
    _write_lines(
        session,
        [
            {"type": "event_msg", "timestamp": "one", "payload": {"type": "user_message", "message": "secret"}},
            {"type": "event_msg", "timestamp": "two", "payload": {"type": "agent_message", "message": "secret"}},
            {
                "type": "response_item",
                "timestamp": "three",
                "payload": {"type": "function_call", "name": "exec_command", "arguments": "private args"},
            },
        ],
    )

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()

    assert [event["kind"] for event in _events(r)] == ["input", "output", "tool"]
    assert _events(r)[-1]["tool"] == "exec_command"
    assert "secret" not in json.dumps(r.streams)
    assert "private args" not in json.dumps(r.streams)


def test_agy_agent_has_empty_stream_even_when_an_old_claude_session_exists(tmp_path):
    r = ActivityRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    stale = tmp_path / ".claude" / "projects" / "-workdir-sme-2" / "stale.jsonl"
    _write_lines(stale, [{"type": "user", "message": "must not appear"}])
    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()
    assert _events(r) == []
    assert prefix("acme", "hq", "sme-2", "activity.offset") not in r.values
