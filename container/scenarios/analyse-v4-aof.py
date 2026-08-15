#!/usr/bin/env python3
"""Compare exact v4 frame bytes at egress and ingress in a captured Redis AOF."""

import argparse
from collections import defaultdict
from pathlib import Path

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
    parser = argparse.ArgumentParser()
    parser.add_argument("aof_dir")
    args = parser.parse_args()

    egress = {}
    ingress = defaultdict(list)
    parse_failures = []
    for path in sorted(Path(args.aof_dir).glob("*.aof")):
        for command in commands(path.read_bytes()):
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
    if not stamped:
        print("REFUSED: source-stamp control absent from the captured AOF")
    return 1 if (body_mismatch or counter_mismatch or source_mismatch or parse_failures or not stamped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
