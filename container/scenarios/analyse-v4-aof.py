#!/usr/bin/env python3
"""Compare exact v4 frame bytes at egress and ingress in a captured Redis AOF.

⚠ **Verdict Contract:**
  0    pass: all egress frames matched byte-for-byte at ingress with valid headers
  1+   fail: count of wire integrity defects (body/counter/source/missing/corrupt)
  100  incomplete: directory missing or no .aof files found (could not run)
"""

import argparse
from collections import defaultdict
from pathlib import Path
import sys

HEADER_WIDTH = 256
SOURCE_START = 65
DESTINATION_START = 128
TTL_START = 191
HOPS_START = 194
RESERVED_START = 197


def commands(data: bytes):
    """Yield RESP arrays from an append-only command stream."""
    position = 0
    while position < len(data):
        if data[position : position + 1] != b"*":
            raise ValueError(f"expected RESP array at byte {position}")
        end = data.index(b"\r\n", position)
        count = int(data[position + 1 : end])
        position = end + 2
        row = []
        for _ in range(count):
            if data[position : position + 1] != b"$":
                raise ValueError(f"expected bulk string at byte {position}")
            end = data.index(b"\r\n", position)
            size = int(data[position + 1 : end])
            position = end + 2
            row.append(data[position : position + size])
            position += size
            if data[position : position + 2] != b"\r\n":
                raise ValueError(f"unterminated bulk string at byte {position}")
            position += 2
        yield row


def frame_fields(raw: bytes) -> tuple[str, str, str, int, int, bytes]:
    if len(raw) < HEADER_WIDTH or raw[:1] != b"4":
        raise ValueError("not a v4 frame")
    return (
        raw[1:33].decode("ascii"),
        raw[SOURCE_START:DESTINATION_START].rstrip().decode("ascii"),
        raw[DESTINATION_START:TTL_START].rstrip().decode("ascii"),
        int(raw[TTL_START:HOPS_START]),
        int(raw[HOPS_START:RESERVED_START]),
        raw[HEADER_WIDTH:],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify byte-exact frame integrity and header invariants across egress and ingress in Redis AOF."
    )
    parser.add_argument("aof_dir", nargs="?", default=None, help="directory containing captured .aof files")
    parser.add_argument(
        "--require-source-stamp",
        action="store_true",
        default=False,
        help="require at least one source-stamped frame control in capture",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        default=False,
        help="do not treat missing ingress deliveries as defects (e.g. partial capture)",
    )
    args = parser.parse_args()

    if not args.aof_dir:
        print("RESULT analyse-v4-aof incomplete reason=missing_argument", file=sys.stderr)
        return 100

    aof_dir = Path(args.aof_dir)
    if not aof_dir.is_dir():
        print(f"RESULT analyse-v4-aof incomplete reason=dir_not_found path={aof_dir}", file=sys.stderr)
        return 100

    aof_files = sorted(aof_dir.glob("*.aof"))
    if not aof_files:
        print(f"RESULT analyse-v4-aof incomplete reason=no_aof_files path={aof_dir}", file=sys.stderr)
        return 100

    egress = {}
    ingress = defaultdict(list)
    parse_failures = []
    total_commands = 0

    for path in aof_files:
        try:
            content = path.read_bytes()
        except Exception as exc:
            print(f"RESULT analyse-v4-aof incomplete reason=read_error file={path} error={exc}", file=sys.stderr)
            return 100

        try:
            for command in commands(content):
                total_commands += 1
                if len(command) < 3 or command[0].upper() != b"RPUSH":
                    continue
                key = command[1].decode("utf-8", "replace")
                for raw in command[2:]:
                    try:
                        sid, source, destination, ttl, hops, body = frame_fields(raw)
                    except (ValueError, UnicodeDecodeError) as exc:
                        parse_failures.append((key, str(exc)))
                        continue
                    row = (key, source, destination, ttl, hops, body, raw)
                    if key.endswith(":egress"):
                        egress[sid] = row
                    elif key.endswith(":ingress"):
                        ingress[sid].append(row)
        except Exception as exc:
            parse_failures.append((str(path), f"AOF decode error: {exc}"))

    if not egress:
        print(f"RESULT analyse-v4-aof incomplete reason=no_egress_frames commands={total_commands}", file=sys.stderr)
        return 100

    compared = body_mismatch = counter_mismatch = source_mismatch = missing = 0
    counterexamples = []
    stamped = []
    for sid, sent in egress.items():
        sender = sent[0].split(":")[-2]
        received = ingress.get(sid, [])
        if not received:
            missing += 1
            continue
        for arrived in received:
            compared += 1
            if sent[5] != arrived[5]:
                body_mismatch += 1
                counterexamples.append((sid, sent[5], arrived[5]))
            counter_mismatch += (arrived[3], arrived[4]) != (max(0, sent[3] - 1), sent[4] + 1)
            expected_source = sender
            source_mismatch += arrived[1] != expected_source
            if sent[1] != sender:
                stamped.append((sid, sent[1], sender, sent[5] == arrived[5]))

    print(
        f"V4_AOF egress={len(egress)} compared={compared} missing_ingress={missing} "
        f"body_mismatch={body_mismatch} counter_mismatch={counter_mismatch} "
        f"source_mismatch={source_mismatch} source_stamps={len(stamped)} "
        f"parse_failures={len(parse_failures)}"
    )
    for sid, claimed, stamped_source, body_ok in stamped:
        print(
            f"SOURCE_STAMP stream_id={sid} claimed={claimed} stamped={stamped_source} "
            f"body_identical={str(body_ok).lower()}"
        )
    for key, reason in parse_failures[:10]:
        print(f"PARSE_FAILURE key={key} reason={reason}")
    for sid, sent_body, arrived_body in counterexamples[:10]:
        print(
            f"BODY_MISMATCH stream_id={sid} sent={sent_body!r} "
            f"arrived={arrived_body!r}"
        )

    stamp_defect = 1 if (args.require_source_stamp and not stamped) else 0
    if stamp_defect:
        print("REFUSED: source-stamp control absent from the captured AOF")

    missing_defect = 0 if args.allow_missing else missing
    failed = (
        body_mismatch
        + counter_mismatch
        + source_mismatch
        + len(parse_failures)
        + missing_defect
        + stamp_defect
    )

    if failed == 0:
        print(f"RESULT analyse-v4-aof pass egress={len(egress)} compared={compared}")
        return 0
    else:
        print(
            f"RESULT analyse-v4-aof fail failed={failed} body_mismatches={body_mismatch} "
            f"counter_mismatches={counter_mismatch} source_mismatches={source_mismatch} "
            f"missing={missing_defect} parse_failures={len(parse_failures)} stamp_defects={stamp_defect}",
            file=sys.stderr,
        )
        return min(failed, 125)


if __name__ == "__main__":
    sys.exit(main())
