import json, subprocess, sys
from pathlib import Path

JUDGE = Path('container/scenarios/payload-ack-judge.py')

def run(records, expected, reason=None, submitted=None):
    import tempfile
    with tempfile.NamedTemporaryFile('w', delete=False) as f:
        for r in records: f.write(json.dumps(r)+'\n')
        p=f.name
    argv=[sys.executable, str(JUDGE), p] + ([str(submitted)] if submitted else [])
    out=subprocess.run(argv, text=True, capture_output=True)
    assert p and out.returncode == expected
    assert f'rc={expected}' in out.stdout
    if reason: assert f'reason={reason}' in out.stdout
    return out.stdout
    return out.stdout

def base():
    return [
      {'event':'sent','stream_id':'p1','source':'payload-a','destination':'payload-b'},
      {'event':'opened','stream_id':'p1','source':'payload-a','destination':'payload-b'},
      {'event':'payload_verified','stream_id':'p1','source':'payload-a','destination':'payload-b'},
    ]

def test_payload_ack_reds_and_scope():
    assert 'rc=1' in run([{'event':'sent','stream_id':'p1','source':'payload-a','destination':'payload-b'}], 1, 'payload_never_landed')
    assert 'rc=2' in run(base(), 2, 'payload_landed_ack_not_sent')
    assert 'rc=3' in run(base()+[{'event':'ack_sent','stream_id':'a1','correlation_id':'x','source':'payload-b','destination':'payload-a'}], 3, 'ack_for_unsent')
    assert 'rc=3' in run(base()+[{'event':'ack_sent','stream_id':'a1','source':'payload-b','destination':'payload-a'}], 3, 'ack_missing_correlation')
    assert 'rc=4' in run(base()+[{'event':'payload_invalid','stream_id':'p1','source':'payload-a','destination':'payload-b'}], 4, 'payload_corrupt')
    assert 'rc=5' in run(base()+[{'event':'ack_sent','stream_id':'a1','correlation_id':'p1','source':'payload-b','destination':'payload-a'}], 5, 'ack_leg_unknown')
    clean=base()+[{'event':'sent','stream_id':'a1','source':'payload-b','destination':'payload-a'},{'event':'ack_sent','stream_id':'a1','correlation_id':'p1','source':'payload-b','destination':'payload-a'},{'event':'ack_opened','stream_id':'a1','correlation_id':'p1','source':'payload-a','destination':'payload-b'},{'event':'started','source':'foreign','destination':'foreign'}]
    out=run(clean, 0)
    assert 'ignored_out_of_scope=1' in out


def test_the_log_is_held_to_what_the_harness_actually_submitted():
    """Every count in the judge is read from the log, so a round trip that logged
    NOTHING lowers both sides and the books balance. The harness knows what it
    submitted without asking the log; that comparison is what makes it visible."""
    complete = base() + [
        {'event': 'sent', 'stream_id': 'a1', 'source': 'payload-b', 'destination': 'payload-a'},
        {'event': 'ack_sent', 'stream_id': 'a1', 'correlation_id': 'p1', 'source': 'payload-b', 'destination': 'payload-a'},
        {'event': 'ack_opened', 'stream_id': 'a1', 'correlation_id': 'p1', 'source': 'payload-a', 'destination': 'payload-b'},
    ]
    run(complete, 0)                       # no count given: one logged trip reads clean
    out = run(complete, 6, reason='log_disagrees_with_harness', submitted=2)
    assert 'expected=2' in out and 'PAYLOAD_EXPECTED' in out, out
