import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
BROADCAST = ROOT / "container" / "scenarios" / "reconcile-broadcast.py"


def _record(stream_id, event, *, destination="all"):
    return json.dumps(
        {
            "ts": "2026-08-23T00:00:00.000Z",
            "event": event,
            "stream_id": stream_id,
            "destination": destination,
        }
    )


def _run(tmp_path, records):
    ledger = tmp_path / "ledger.tsv"
    log = tmp_path / "custody.log"
    ledger.write_text("sid\tbob\nsid\tcarol\n")
    log.write_text("\n".join(records) + "\n")
    return subprocess.run(
        [sys.executable, str(BROADCAST), str(ledger), str(log)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_partial_broadcast_unknown_is_not_reported_as_known_loss(tmp_path):
    result = _run(
        tmp_path,
        [
            _record("sid", "forward_unknown"),
            _record("sid", "opened", destination="bob"),
        ],
    )

    assert result.returncode == 5
    assert "delivered_once=1" in result.stdout
    assert "lost=0 indeterminate=1" in result.stdout
    assert "BROADCAST_INDETERMINATE_FORWARD sid carol" in result.stdout
    assert "BROADCAST_LOST" not in result.stdout


def test_broadcast_reconciliation_refuses_legacy_attempt_record(tmp_path):
    result = _run(tmp_path, [_record("sid", "forward_failed")])

    assert result.returncode == 4
    assert "legacy_attempts=1" in result.stdout
    assert "REFUSED: legacy *_failed attempt records" in result.stdout

