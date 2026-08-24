import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "container/scenarios/packet-switching.sh"


def _fixture(tmp_path, opened):
    log = tmp_path / "custody.log"
    sent = {
        "event": "sent", "stream_id": "s1", "source": "a", "destination": "b",
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
        log.write(json.dumps({"event": "opened", "stream_id": "stray", "ts": "2026-01-01T00:00:00.000Z"}) + "\n")
    result = subprocess.run(["bash", str(HARNESS), "--reconcile-only", str(fixture)], capture_output=True, text=True)
    assert result.returncode == 3
    assert "PACKET_RESULT rc=3 reason=stray" in result.stdout
