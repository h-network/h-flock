import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "container/scenarios/packet-switching.sh"


def _fixture(tmp_path, opened):
    log = tmp_path / "custody.log"
    sent = {
        "event": "sent", "stream_id": "s1", "source": "bench-1", "destination": "bench-2",
        "ts": "2026-01-01T00:00:00.000Z",
    }
    records = [sent]
    records.extend({**sent, "event": "opened"} for _ in range(opened))
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return tmp_path


def test_packet_harness_loss_is_rc1(tmp_path):
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(_fixture(tmp_path, 0))], capture_output=True, text=True)
    assert result.returncode == 1
    assert "PACKET_RESULT rc=1" in result.stdout


def test_packet_harness_clean_is_rc0(tmp_path):
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(_fixture(tmp_path, 1))], capture_output=True, text=True)
    assert result.returncode == 0
    assert "PACKET_RESULT rc=0 reason=clean" in result.stdout
    assert "PACKET_STAGES sent=1 popped=0 forwarded=0 received=0 opened=1" in result.stdout


def test_packet_harness_duplicate_is_rc2(tmp_path):
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(_fixture(tmp_path, 2))], capture_output=True, text=True)
    assert result.returncode == 2
    assert "PACKET_RESULT rc=2" in result.stdout


def test_packet_harness_stray_is_rc3(tmp_path):
    fixture = _fixture(tmp_path, 1)
    with (fixture / "custody.log").open("a") as log:
        log.write(json.dumps({"event": "opened", "stream_id": "stray", "source": "bench-9", "destination": "bench-1", "ts": "2026-01-01T00:00:00.000Z"}) + "\n")
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(fixture)], capture_output=True, text=True)
    assert result.returncode == 3
    assert "PACKET_RESULT rc=3 reason=stray" in result.stdout


def test_packet_harness_ignores_unrelated_traffic(tmp_path):
    fixture = _fixture(tmp_path, 1)
    with (fixture / "custody.log").open("a") as log:
        log.write(json.dumps({"event": "opened", "stream_id": "office", "source": "architect", "destination": "telegram", "ts": "2026-01-01T00:00:00.000Z"}) + "\n")
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(fixture)], capture_output=True, text=True)
    assert result.returncode == 0
    assert "PACKET_SCOPE source_or_destination_prefix=bench- ignored_out_of_scope=1" in result.stdout


def _staged(tmp_path, ids):
    """One custody log with all five stages recorded for each id given."""
    records = [
        {"event": ev, "stream_id": sid, "source": "bench-1", "destination": "bench-2",
         "ts": "2026-01-01T00:00:00.000Z"}
        for sid in ids
        for ev in ("sent", "popped", "forwarded", "received", "opened")
    ]
    (tmp_path / "custody.log").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return tmp_path


def _judge(work, expected):
    """Run the harness's judge the way a live run does, with a harness-side count."""
    body = HARNESS.read_text().split("judge() {\n", 1)[1].split("\nPY\n", 1)[0]
    script = body.split("<<'PY'\n", 1)[1]
    return subprocess.run(["python3", "-c", script, str(work), str(expected)],
                          capture_output=True, text=True, cwd=ROOT)


def test_an_envelope_that_logged_nothing_is_invisible_without_a_harness_count(tmp_path):
    """Control: every count in the judge is read from the log, so a lost RECORD
    lowers both sides of the comparison and the books still balance. This is what
    the check could not see, and it is why the harness count exists."""
    work = _staged(tmp_path, ["s1", "s2"])          # 2 logged, but 3 were sent
    assert _judge(work, 0).returncode == 0, "with no harness count this reads as clean"


def test_the_log_is_held_to_what_the_harness_actually_submitted(tmp_path):
    """The one non-circular check: 3 submitted, 2 in the log, every stage short."""
    work = _staged(tmp_path, ["s1", "s2"])
    result = _judge(work, 3)
    assert result.returncode == 6, result.stdout
    assert "reason=log_disagrees_with_harness" in result.stdout
    assert "expected=3" in result.stdout
    assert "sent=2" in result.stdout, "the short stages are named so a reader knows where"
