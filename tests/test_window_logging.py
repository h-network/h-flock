import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from flock.bus import log_record, prefix, receive, send
from flock.router.service import Router
from flock.router.windowlog import WindowLogTailer


class LogRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}
        self.hashes = {prefix("acme", "hq", resource="roster"): {"sender": "tmux", "receiver": "tmux"}}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

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

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


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
            producer="sender",
            recipient="receiver",
            payload={"text": "hello"},
            module="adapter",
        )
    assert json.loads(pane.getvalue())["event"] == "sent"

    monkeypatch.delenv("FLOCK_LOG_FILE")
    central = io.StringIO()
    with patch("flock.router.service.subprocess.Popen"), redirect_stdout(central):
        WindowLogTailer(r, pod="acme", tenant="hq", path=path).poll()
        assert Router(r, pod="acme", tenant="hq").step(timeout=0)
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
    assert [record["event"] for record in joined] == ["sent", "popped", "forwarded", "received", "opened"]
    assert [record["module"] for record in joined] == ["adapter", "router", "router", "adapter", "adapter"]


def test_unwritable_window_log_never_breaks_send(monkeypatch, tmp_path, capsys):
    r = LogRedis()
    monkeypatch.setenv("FLOCK_LOG_FILE", str(tmp_path))
    stream_id = send(
        r,
        pod="acme",
        tenant="hq",
        producer="sender",
        recipient="receiver",
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
