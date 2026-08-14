import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from flock.bus import log_record, prefix, receive, send
from flock.switch.service import Switch
from flock.switch.windowlog import WindowLogTailer


class LogRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}
        self.hashes = {prefix("acme", "hq", resource="roster"): {"sender": "tmux", "receiver": "tmux"}}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def blpop(self, keys, timeout=0):
        keys = [keys] if isinstance(keys, str) else keys
        for key in keys:
            if self.lists.get(key):
                return key, self.lists[key].pop(0)
        return None

    def hkeys(self, key):
        return self.hashes.get(key, {}).keys()

    def hexists(self, key, field):
        return field in self.hashes.get(key, {})

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


class WriteCountingStdout(io.StringIO):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.flushes = 0

    def write(self, value):
        self.writes.append(value)
        return super().write(value)

    def flush(self):
        self.flushes += 1
        return super().flush()


def test_stdout_record_and_newline_are_one_write(monkeypatch):
    output = WriteCountingStdout()
    monkeypatch.setattr("sys.stdout", output)

    log_record("switch", "forwarded", stream_id="abc")

    assert len(output.writes) == 1
    assert output.writes[0].endswith("\n")
    assert output.flushes == 1
    assert json.loads(output.writes[0])["event"] == "forwarded"


def test_agent_sent_envelope_is_observed_end_to_end_in_central_log(monkeypatch, tmp_path):
    r = LogRedis()
    path = tmp_path / "window.jsonl"
    monkeypatch.setenv("AGENT_NAME", "sender")
    monkeypatch.setenv("FLOCK_LOG_FILE", str(path))

    pane = io.StringIO()
    with redirect_stdout(pane):
        stream_id = send(
            r,
            pod="acme",
            tenant="hq",
            source="sender",
            destination="receiver",
            payload={"text": "hello"},
            module="port",
        )
    assert json.loads(pane.getvalue())["event"] == "sent"

    monkeypatch.delenv("FLOCK_LOG_FILE")
    central = io.StringIO()
    with patch("flock.switch.service.subprocess.Popen"), redirect_stdout(central):
        WindowLogTailer(r, pod="acme", tenant="hq", path=path).poll()
        assert Switch(r, pod="acme", tenant="hq").step(timeout=0)
        receive(
            r,
            pod="acme",
            tenant="hq",
            agent="receiver",
            openers={"Message": lambda envelope: None},
            timeout=0,
        )

    records = [json.loads(line) for line in central.getvalue().splitlines()]
    joined = [record for record in records if record.get("stream_id") == stream_id]
    assert [record["event"] for record in joined] == [
        "sent", "popped", "forwarded", "kick_started", "received", "opened"
    ]
    assert [record["module"] for record in joined] == [
        "port", "switch", "switch", "switch", "port", "port"
    ]


def test_unwritable_window_log_never_breaks_send(monkeypatch, tmp_path, capsys):
    r = LogRedis()
    monkeypatch.setenv("FLOCK_LOG_FILE", str(tmp_path))
    stream_id = send(
        r,
        pod="acme",
        tenant="hq",
        source="sender",
        destination="receiver",
        payload={},
    )
    assert stream_id
    assert json.loads(capsys.readouterr().out)["event"] == "sent"


def test_agent_only_file_setting_excludes_central_process_records(monkeypatch, tmp_path, capsys):
    path = tmp_path / "window.jsonl"
    monkeypatch.setenv("FLOCK_LOG_FILE", str(path))
    monkeypatch.setenv("FLOCK_LOG_FILE_AGENT_ONLY", "1")
    monkeypatch.delenv("AGENT_NAME", raising=False)
    log_record("tmuxhost", "started")
    assert json.loads(capsys.readouterr().out)["event"] == "started"
    assert not path.exists()


def test_window_log_tailer_uses_byte_offset_and_waits_for_complete_line(tmp_path, capsys):
    r = LogRedis()
    path = tmp_path / "window.jsonl"
    path.write_bytes(b'{"event":"one"}\n{"event":"two')
    tailer = WindowLogTailer(r, pod="acme", tenant="hq", path=path)
    tailer.poll()
    assert capsys.readouterr().out.splitlines() == ['{"event":"one"}']

    with path.open("ab") as output:
        output.write(b'"}\n')
    tailer.poll()
    assert capsys.readouterr().out.splitlines() == ['{"event":"two"}']


def test_window_log_truncates_only_at_consumed_end_and_later_record_still_arrives(tmp_path, capsys):
    r = LogRedis()
    path = tmp_path / "window.jsonl"
    initial = b'{"event":"first"}\n{"event":"second"}\n'
    path.write_bytes(initial)
    tailer = WindowLogTailer(r, pod="acme", tenant="hq", path=path, max_bytes=25)

    tailer.poll()
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ['{"event":"first"}', '{"event":"second"}']
    truncation = json.loads(lines[2])
    assert truncation["module"] == "switch"
    assert truncation["event"] == "window_log_truncated"
    assert truncation["bytes"] == len(initial)
    assert path.read_bytes() == b""
    assert r.values[tailer.offset_key] == 0

    with path.open("ab") as output:
        output.write(b'{"event":"after"}\n')
    tailer.poll()
    assert capsys.readouterr().out.splitlines() == ['{"event":"after"}']


def test_window_log_over_cap_is_not_truncated_before_partial_tail_is_consumed(tmp_path, capsys):
    r = LogRedis()
    path = tmp_path / "window.jsonl"
    partial = b'{"event":"an-unconsumed-record"}'
    path.write_bytes(partial)
    tailer = WindowLogTailer(r, pod="acme", tenant="hq", path=path, max_bytes=10)

    tailer.poll()

    assert capsys.readouterr().out == ""
    assert path.read_bytes() == partial
    assert r.values[tailer.offset_key] == 0


def test_window_log_skips_complete_invalid_utf8_line_and_keeps_progressing(tmp_path, capsys):
    r = LogRedis()
    path = tmp_path / "window.jsonl"
    path.write_bytes(b'{"event":"before"}\ninvalid:\xff\n{"event":"after"}\n')
    tailer = WindowLogTailer(r, pod="acme", tenant="hq", path=path)

    tailer.poll()

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == '{"event":"before"}'
    error = json.loads(lines[1])
    assert error["event"] == "window_log_decode_error"
    assert error["reason"] == "invalid UTF-8 at byte 27"
    assert error["bytes"] == len(b"invalid:\xff\n")
    assert lines[2] == '{"event":"after"}'
    assert r.values[tailer.offset_key] == path.stat().st_size

    tailer.poll()
    assert capsys.readouterr().out == ""
