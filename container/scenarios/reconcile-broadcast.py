#!/usr/bin/env python3
"""Reconcile one broadcast ledger against a static custody log."""

import collections
import json
import sys


LEGACY_ATTEMPT_EVENTS = {"send_failed", "forward_failed", "kick_failed"}


def main() -> int:
    ledger_path, log_path = sys.argv[1:]
    expected = set()
    with open(ledger_path) as handle:
        for line in handle:
            if line.strip():
                stream_id, recipient = line.rstrip().split("\t")
                expected.add((stream_id, recipient))

    opened = collections.Counter()
    indeterminate_sids = set()
    parse_failures = 0
    legacy_attempts = 0
    with open(log_path, errors="replace") as handle:
        for line in handle:
            if not line.lstrip().startswith("{"):
                continue
            try:
                record = json.loads(line)
            except Exception:
                parse_failures += 1
                continue
            event = record.get("event")
            if event in LEGACY_ATTEMPT_EVENTS:
                legacy_attempts += 1
            if event == "forward_unknown":
                indeterminate_sids.add(record.get("stream_id"))
            if event == "opened":
                opened[(record.get("stream_id"), record.get("destination"))] += 1

    duplicates = [(key, count) for key, count in opened.items() if key in expected and count > 1]
    unresolved = [
        key for key in expected
        if opened[key] == 0 and key[0] in indeterminate_sids
    ]
    lost = [
        key for key in expected
        if opened[key] == 0 and key[0] not in indeterminate_sids
    ]
    expected_sids = {sid for sid, _ in expected}
    unexpected = [
        (key, count) for key, count in opened.items()
        if key not in expected and key[0] in expected_sids
    ]
    delivered = sum(opened[key] == 1 for key in expected)
    print(
        f"BROADCAST_RECONCILE expected={len(expected)} delivered_once={delivered} "
        f"duplicates={len(duplicates)} lost={len(lost)} "
        f"indeterminate={len(unresolved)} unexpected_recipient={len(unexpected)} "
        f"parse_failures={parse_failures} legacy_attempts={legacy_attempts}"
    )
    for key, count in duplicates[:10]:
        print("BROADCAST_DUPLICATE", key[0], key[1], count)
    for key in lost[:10]:
        print("BROADCAST_LOST", key[0], key[1])
    for key in unresolved[:10]:
        print("BROADCAST_INDETERMINATE_FORWARD", key[0], key[1])
    for key, count in unexpected[:10]:
        print("BROADCAST_UNEXPECTED_RECIPIENT", key[0], key[1], count)
    if legacy_attempts:
        print("REFUSED: legacy *_failed attempt records require a version-specific analyser")
    if parse_failures or legacy_attempts:
        return 4
    if duplicates or unexpected:
        return 2
    if unresolved:
        return 5
    if lost:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
