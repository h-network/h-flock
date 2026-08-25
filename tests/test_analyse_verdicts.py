import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
VERIF_SCRIPT = ROOT / "container/scenarios/analyse-verification.py"
AOF_SCRIPT = ROOT / "container/scenarios/analyse-v4-aof.py"


# --- analyse-verification tests ---

def test_analyse_verification_missing_arg_exits_100():
    res = subprocess.run([sys.executable, str(VERIF_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-verification incomplete reason=missing_argument" in res.stderr


def test_analyse_verification_missing_file_exits_100(tmp_path):
    missing = tmp_path / "nonexistent.jsonl"
    res = subprocess.run([sys.executable, str(VERIF_SCRIPT), str(missing)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-verification incomplete reason=file_not_found" in res.stderr


def test_analyse_verification_empty_file_exits_100(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    res = subprocess.run([sys.executable, str(VERIF_SCRIPT), str(empty)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-verification incomplete reason=no_records" in res.stderr


def test_analyse_verification_clean_run_passes(tmp_path):
    log = tmp_path / "custody.jsonl"
    records = [
        {"event": "sent", "ts": "2026-08-25T01:00:00.000Z", "source": "alice", "destination": "bob"},
        {"event": "opened", "ts": "2026-08-25T01:00:01.000Z", "source": "alice", "destination": "bob"},
        {"event": "sent", "ts": "2026-08-25T01:00:02.000Z", "source": "bob", "destination": "alice"},
        {"event": "opened", "ts": "2026-08-25T01:00:03.000Z", "source": "bob", "destination": "alice"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    res = subprocess.run([sys.executable, str(VERIF_SCRIPT), str(log)], capture_output=True, text=True)
    assert res.returncode == 0
    assert "RESULT analyse-verification pass" in res.stdout
    assert "total_flags=0 refuted=0" in res.stdout


def test_analyse_verification_true_positive_unverified_passes(tmp_path):
    """When an agent was flagged delivery_unverified and never sent traffic afterwards,
    it was a true positive stall; refuted is 0 and the check passes."""
    log = tmp_path / "custody.jsonl"
    records = [
        {"event": "sent", "ts": "2026-08-25T01:00:00.000Z", "source": "alice", "destination": "bob"},
        {"event": "opened", "ts": "2026-08-25T01:00:01.000Z", "source": "alice", "destination": "bob"},
        {"event": "delivery_unverified", "ts": "2026-08-25T01:00:05.000Z", "destination": "bob"},
        # Bob never sends any traffic after 01:00:05
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    res = subprocess.run([sys.executable, str(VERIF_SCRIPT), str(log)], capture_output=True, text=True)
    assert res.returncode == 0
    assert "RESULT analyse-verification pass" in res.stdout
    assert "total_flags=1 refuted=0" in res.stdout


def test_analyse_verification_refuted_unverified_wolf_cry_fails(tmp_path):
    """When an agent was flagged delivery_unverified but demonstrably sent traffic afterwards,
    the flag was proven false (wolf cry); the analyser fails with exit code = count of refuted flags."""
    log = tmp_path / "custody.jsonl"
    records = [
        {"event": "sent", "ts": "2026-08-25T01:00:00.000Z", "source": "alice", "destination": "bob"},
        {"event": "opened", "ts": "2026-08-25T01:00:01.000Z", "source": "alice", "destination": "bob"},
        {"event": "delivery_unverified", "ts": "2026-08-25T01:00:05.000Z", "destination": "bob"},
        # Bob demonstrably sent traffic after being flagged:
        {"event": "sent", "ts": "2026-08-25T01:00:10.000Z", "source": "bob", "destination": "alice"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    res = subprocess.run([sys.executable, str(VERIF_SCRIPT), str(log)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "RESULT analyse-verification fail failed=1" in res.stderr
    assert "refuted=1" in res.stderr


def test_analyse_verification_threshold_override(tmp_path):
    """Threshold options allow configuring tolerance."""
    log = tmp_path / "custody.jsonl"
    records = [
        {"event": "delivery_unverified", "ts": "2026-08-25T01:00:05.000Z", "destination": "bob"},
        {"event": "sent", "ts": "2026-08-25T01:00:10.000Z", "source": "bob", "destination": "alice"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    # With max-refuted=1, 1 refuted flag is allowed -> pass
    res_pass = subprocess.run(
        [sys.executable, str(VERIF_SCRIPT), str(log), "--max-refuted", "1"],
        capture_output=True, text=True,
    )
    assert res_pass.returncode == 0
    assert "RESULT analyse-verification pass" in res_pass.stdout


# --- analyse-v4-aof tests ---

def make_resp_aof(commands_list):
    """Encode a list of redis commands into RESP append-only bytes."""
    out = bytearray()
    for cmd in commands_list:
        out.extend(f"*{len(cmd)}\r\n".encode())
        for arg in cmd:
            b_arg = arg.encode("latin1") if isinstance(arg, str) else bytes(arg)
            out.extend(f"${len(b_arg)}\r\n".encode())
            out.extend(b_arg)
            out.extend(b"\r\n")
    return bytes(out)


def test_analyse_v4_aof_missing_arg_exits_100():
    res = subprocess.run([sys.executable, str(AOF_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-v4-aof incomplete reason=missing_argument" in res.stderr


def test_analyse_v4_aof_missing_dir_exits_100(tmp_path):
    missing = tmp_path / "nodir"
    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(missing)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-v4-aof incomplete reason=dir_not_found" in res.stderr


def test_analyse_v4_aof_empty_dir_exits_100(tmp_path):
    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 100
    assert "RESULT analyse-v4-aof incomplete reason=no_aof_files" in res.stderr


def test_analyse_v4_aof_clean_wire_integrity_passes(tmp_path):
    sys.path.insert(0, str(ROOT / "src"))
    from flock.bus import build, encode

    frame = build("Message", "alice", "bob", {"text": "hello"}, pod="acme", tenant="hq")
    egress_raw = encode(frame)
    if isinstance(egress_raw, str):
        egress_raw = egress_raw.encode("latin1")

    # Ingress frame has TTL decremented by 1, hops incremented by 1, body identical
    sent_ttl = 16
    arrived_ttl = 15
    sent_hops = 0
    arrived_hops = 1

    header_prefix = egress_raw[:191] # up to TTL
    reserved_and_body = egress_raw[197:] # from reserved to end
    ingress_raw = header_prefix + f"{arrived_ttl:>3}{arrived_hops:>3}".encode("ascii") + reserved_and_body

    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", egress_raw],
        [b"RPUSH", b"pod:acme:tenant:hq:agent:bob:ingress", ingress_raw],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 0
    assert "RESULT analyse-v4-aof pass" in res.stdout
    assert "egress=1 compared=1" in res.stdout


def test_analyse_v4_aof_body_mismatch_fails(tmp_path):
    sys.path.insert(0, str(ROOT / "src"))
    from flock.bus import build, encode

    frame = build("Message", "alice", "bob", {"text": "hello"}, pod="acme", tenant="hq")
    egress_raw = encode(frame)
    if isinstance(egress_raw, str):
        egress_raw = egress_raw.encode("latin1")

    # Corrupt body on ingress
    ingress_raw = egress_raw[:191] + b" 15  1" + egress_raw[197:-1] + b"X"

    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", egress_raw],
        [b"RPUSH", b"pod:acme:tenant:hq:agent:bob:ingress", ingress_raw],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "RESULT analyse-v4-aof fail failed=1" in res.stderr
    assert "body_mismatches=1" in res.stderr


def test_analyse_v4_aof_counter_mismatch_fails(tmp_path):
    sys.path.insert(0, str(ROOT / "src"))
    from flock.bus import build, encode

    frame = build("Message", "alice", "bob", {"text": "hello"}, pod="acme", tenant="hq")
    egress_raw = encode(frame)
    if isinstance(egress_raw, str):
        egress_raw = egress_raw.encode("latin1")

    # Ingress with un-decremented TTL (16 instead of 15)
    ingress_raw = egress_raw[:191] + b" 16  1" + egress_raw[197:]

    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", egress_raw],
        [b"RPUSH", b"pod:acme:tenant:hq:agent:bob:ingress", ingress_raw],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "RESULT analyse-v4-aof fail failed=1" in res.stderr
    assert "counter_mismatches=1" in res.stderr


def test_analyse_v4_aof_missing_ingress_fails(tmp_path):
    sys.path.insert(0, str(ROOT / "src"))
    from flock.bus import build, encode

    frame = build("Message", "alice", "bob", {"text": "hello"}, pod="acme", tenant="hq")
    egress_raw = encode(frame)
    if isinstance(egress_raw, str):
        egress_raw = egress_raw.encode("latin1")

    # Only egress, missing ingress
    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", egress_raw],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "RESULT analyse-v4-aof fail failed=1" in res.stderr
    assert "missing=1" in res.stderr


def test_analyse_verification_documents_one_sided_limitation():
    """Verify that docstring and console output explicitly document the one-sided oracle limitation."""
    doc = VERIF_SCRIPT.read_text(encoding="utf-8")
    assert "STRUCTURAL LIMITATION: ONE-SIDED ORACLE" in doc
    assert "wolf-cries" in doc.lower() or "false alarms" in doc.lower()


def test_analyse_v4_aof_parse_failure_fails(tmp_path):
    # An invalid frame that fails v4 parsing (less than 256 bytes)
    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", b"too_short"],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 100 # len(egress) is 0 because of parse failure
    assert "incomplete reason=no_egress_frames" in res.stderr


def test_analyse_v4_aof_source_mismatch_fails(tmp_path):
    sys.path.insert(0, str(ROOT / "src"))
    from flock.bus import build, encode

    frame = build("Message", "alice", "bob", {"text": "hello"}, pod="acme", tenant="hq")
    egress_raw = encode(frame)
    if isinstance(egress_raw, str):
        egress_raw = egress_raw.encode("latin1")

    # Ingress with forged/mismatched source (eve instead of alice)
    header_prefix = egress_raw[:65] # up to source
    forged_source = f"{'eve':<63}".encode("ascii")
    destination = egress_raw[128:191]
    ttl_hops = b" 15  1"
    rest = egress_raw[197:]
    ingress_raw = header_prefix + forged_source + destination + ttl_hops + rest

    aof_bytes = make_resp_aof([
        [b"RPUSH", b"pod:acme:tenant:hq:agent:alice:egress", egress_raw],
        [b"RPUSH", b"pod:acme:tenant:hq:agent:bob:ingress", ingress_raw],
    ])

    (tmp_path / "appendonly.aof").write_bytes(aof_bytes)

    res = subprocess.run([sys.executable, str(AOF_SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "RESULT analyse-v4-aof fail failed=1" in res.stderr
    assert "source_mismatches=1" in res.stderr
