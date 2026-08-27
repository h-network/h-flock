from conftest import FakeRedis
import json
from datetime import datetime, timezone
from pathlib import Path

from flock.bus import prefix
from flock.watchdog.activity import ActivityTailer



def _events(r, agent="sme-2"):
    key = prefix("acme", "hq", agent, "activity")
    return [json.loads(entry["event"]) for entry in [entry[1] if isinstance(entry, (tuple, list)) else entry for entry in r.streams.get(key, [])]]


def _write_lines(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_claude_tailer_reads_only_new_bytes_and_never_emits_content(tmp_path):
    r = FakeRedis()
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
    assert json.loads(r.values[offset_key])["offsets"][str(session)] == session.stat().st_size
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
    r = FakeRedis()
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
    assert state == {
        "offsets": {
            str(old): old.stat().st_size,
            str(new): new.stat().st_size,
        }
    }


def test_switching_back_to_prior_session_resumes_its_saved_offset(tmp_path):
    r = FakeRedis()
    directory = tmp_path / ".claude" / "projects" / "-workdir-sme-2"
    old = directory / "old.jsonl"
    new = directory / "new.jsonl"
    _write_lines(old, [{"type": "user", "timestamp": "old-first"}])
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    _write_lines(new, [{"type": "assistant", "timestamp": "new", "message": {"content": "answer"}}])
    tailer.poll()

    with old.open("a") as output:
        output.write(json.dumps({"type": "user", "timestamp": "old-second"}) + "\n")
    old.touch()
    tailer.poll()

    assert [event["ts"] for event in _events(r)] == ["old-first", "new", "old-second"]


def test_activity_offset_migrates_original_single_path_shape(tmp_path):
    r = FakeRedis()
    session = tmp_path / ".claude" / "projects" / "-workdir-sme-2" / "one.jsonl"
    first = json.dumps({"type": "user", "timestamp": "already-read"}) + "\n"
    second = json.dumps({"type": "user", "timestamp": "new"}) + "\n"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(first + second)
    r.values[prefix("acme", "hq", "sme-2", "activity.offset")] = json.dumps(
        {"path": str(session), "offset": len(first.encode())}
    )

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()

    assert [event["ts"] for event in _events(r)] == ["new"]
    state = json.loads(r.values[prefix("acme", "hq", "sme-2", "activity.offset")])
    assert state == {"offsets": {str(session): session.stat().st_size}}


def test_codex_profile_session_reduces_messages_and_tool_calls(tmp_path):
    r = FakeRedis()
    r.values[prefix("acme", "hq", "sme-2", "profile")] = "work"
    session = tmp_path / ".codex-work" / "sessions" / "2026" / "08" / "rollout-one.jsonl"
    _write_lines(
        session,
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/sme-2"}},
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


def test_codex_shared_account_attributes_each_session_by_workspace(tmp_path):
    r = FakeRedis(agents=("frontend", "backend"))
    shared = tmp_path / ".codex" / "sessions" / "2026" / "08"
    _write_lines(
        shared / "rollout-frontend.jsonl",
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/frontend"}},
            {"type": "event_msg", "timestamp": "front", "payload": {"type": "user_message"}},
        ],
    )
    _write_lines(
        shared / "rollout-backend.jsonl",
        [
            {"type": "session_meta", "payload": {"cwd": "/workdir/backend"}},
            {"type": "event_msg", "timestamp": "back", "payload": {"type": "agent_message"}},
        ],
    )
    r.values[prefix("acme", "hq", "frontend", "launch")] = "codex"
    r.values[prefix("acme", "hq", "backend", "launch")] = "codex"

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()

    assert _events(r, "frontend") == [
        {"v": 1, "agent": "frontend", "ts": "front", "kind": "input"}
    ]
    assert _events(r, "backend") == [
        {"v": 1, "agent": "backend", "ts": "back", "kind": "output"}
    ]


def test_agy_agent_has_empty_stream_even_when_an_old_claude_session_exists(tmp_path):
    r = FakeRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    stale = tmp_path / ".claude" / "projects" / "-workdir-sme-2" / "stale.jsonl"
    _write_lines(stale, [{"type": "user", "message": "must not appear"}])
    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()
    assert _events(r) == []
    assert prefix("acme", "hq", "sme-2", "activity.offset") not in r.values


def _history_path(tmp_path: Path) -> Path:
    return tmp_path / ".gemini" / "antigravity-cli" / "history.jsonl"


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_agy_reads_history_jsonl_filtered_by_workspace(tmp_path):
    """One shared file, two agy agents — each sees only its own lines."""
    r = FakeRedis(agents=("frontend", "backend"))
    r.values[prefix("acme", "hq", "frontend", "launch")] = "agy"
    r.values[prefix("acme", "hq", "backend", "launch")] = "agy"
    _write_lines(
        _history_path(tmp_path),
        [
            {"display": "hi", "timestamp": _ms("2026-08-09T10:00:00"), "workspace": "/workdir/frontend", "conversationId": "a"},
            {"display": "hi", "timestamp": _ms("2026-08-09T10:00:01"), "workspace": "/workdir/backend", "conversationId": "b"},
            {"display": "/model", "timestamp": _ms("2026-08-09T10:00:02"), "workspace": "/workdir/frontend", "type": "slash_command"},
            {"display": "not ours", "timestamp": _ms("2026-08-09T10:00:03"), "workspace": "/workdir/someone-else"},
        ],
    )

    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()

    assert _events(r, "frontend") == [
        {"v": 1, "agent": "frontend", "ts": "2026-08-09T10:00:00.000Z", "kind": "input"},
        {"v": 1, "agent": "frontend", "ts": "2026-08-09T10:00:02.000Z", "kind": "input"},
    ]
    assert _events(r, "backend") == [
        {"v": 1, "agent": "backend", "ts": "2026-08-09T10:00:01.000Z", "kind": "input"}
    ]
    # Privacy: the submitted text itself never rides into the reduced stream.
    assert "hi" not in json.dumps(r.streams)
    assert "not ours" not in json.dumps(r.streams)


def test_agy_emits_no_usage_records(tmp_path):
    """No token/cost source exists for agy — history.jsonl carries none."""
    r = FakeRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    _write_lines(
        _history_path(tmp_path),
        [{"display": "hi", "timestamp": _ms("2026-08-09T10:00:00"), "workspace": "/workdir/sme-2"}],
    )
    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()
    assert prefix("acme", "hq", resource="usage") not in r.streams


def test_agy_shared_file_keeps_independent_offsets_per_agent(tmp_path):
    r = FakeRedis(agents=("frontend", "backend"))
    r.values[prefix("acme", "hq", "frontend", "launch")] = "agy"
    r.values[prefix("acme", "hq", "backend", "launch")] = "agy"
    history = _history_path(tmp_path)
    _write_lines(
        history,
        [{"display": "hi", "timestamp": _ms("2026-08-09T10:00:00"), "workspace": "/workdir/frontend"}],
    )
    tailer = ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path)
    tailer.poll()

    with history.open("a") as output:
        output.write(json.dumps({"display": "hi again", "timestamp": _ms("2026-08-09T10:00:05"), "workspace": "/workdir/backend"}) + "\n")
    tailer.poll()

    assert len(_events(r, "frontend")) == 1
    assert len(_events(r, "backend")) == 1
    frontend_offset = json.loads(r.values[prefix("acme", "hq", "frontend", "activity.offset")])["offsets"][str(history)]
    backend_offset = json.loads(r.values[prefix("acme", "hq", "backend", "activity.offset")])["offsets"][str(history)]
    assert frontend_offset == backend_offset == history.stat().st_size


def test_agy_ignores_a_line_with_no_matching_workspace(tmp_path):
    r = FakeRedis()
    r.values[prefix("acme", "hq", "sme-2", "launch")] = "agy"
    _write_lines(
        _history_path(tmp_path),
        [
            {"display": "welcome", "timestamp": _ms("2026-08-09T10:00:00")},  # no workspace at all yet
            {"display": "hi", "timestamp": _ms("2026-08-09T10:00:01"), "workspace": "/workdir/sme-2"},
        ],
    )
    ActivityTailer(r, pod="acme", tenant="hq", home_root=tmp_path).poll()
    assert _events(r) == [
        {"v": 1, "agent": "sme-2", "ts": "2026-08-09T10:00:01.000Z", "kind": "input"}
    ]
