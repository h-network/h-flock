#!/usr/bin/env python3
"""Summarize one onboarding run's custody universe.

The universe begins after a caller-owned log line and contains only the named
source/destination pairs. Output is JSON for the manual integration driver; it
deliberately emits no acceptance verdict.
"""

import argparse
import json
from pathlib import Path


def summarize(
    path: Path,
    after_line: int,
    source: str,
    destinations: list[str],
    marked_destinations: list[str] | None = None,
    previously_observed: list[str] | None = None,
) -> dict:
    destination_set = set(destinations)
    marked_destination_set = set(marked_destinations or [])
    observed_destination_set = set(previously_observed or []) & destination_set
    records: list[dict] = []
    parse_failures = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if number <= after_line or not line.lstrip().startswith("{"):
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                parse_failures += 1
                continue
            if row.get("source") != source or row.get("destination") not in destination_set:
                continue
            stream_id = row.get("stream_id")
            if not stream_id or stream_id == "unknown":
                continue
            records.append(row)

    by_destination = {}
    all_stream_ids = set()
    dead_stream_ids = set()
    terminal_without_sent = set()
    for destination in destinations:
        selected = [row for row in records if row.get("destination") == destination]
        stream_ids = {row["stream_id"] for row in selected}
        sent = {row["stream_id"] for row in selected if row.get("event") == "sent"}
        opened_records = {row["stream_id"] for row in selected if row.get("event") == "opened"}
        dead_records = {row["stream_id"] for row in selected if row.get("event") == "dead_lettered"}
        terminal_without_sent.update((opened_records | dead_records) - sent)
        opened = opened_records & sent
        dead = dead_records & sent
        all_stream_ids.update(stream_ids)
        dead_stream_ids.update(dead)
        by_destination[destination] = {
            "stream_ids": sorted(stream_ids),
            "opened_stream_ids": sorted(opened),
            "dead_lettered_stream_ids": sorted(dead),
            "sent": len(sent),
            "opened": len(opened),
            "dead_lettered": len(dead),
        }

    observed_destination_set.update(
        destination for destination, result in by_destination.items()
        if result["opened_stream_ids"] and destination in marked_destination_set
    )
    observed_destinations = sorted(observed_destination_set)
    pane_disagreements = sorted(
        destination for destination, result in by_destination.items()
        if result["opened_stream_ids"] and destination not in observed_destination_set
    )
    return {
        "parse_failures": parse_failures,
        "stream_ids": sorted(all_stream_ids),
        "dead_stream_ids": sorted(dead_stream_ids),
        "terminal_without_sent": sorted(terminal_without_sent),
        "observed_destinations": observed_destinations,
        "pane_disagreements": pane_disagreements,
        "destinations": by_destination,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--after-line", type=int, default=0)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", action="append", required=True)
    parser.add_argument("--marked-destination", action="append", default=[])
    parser.add_argument("--previously-observed", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(summarize(
        args.log, args.after_line, args.source, args.destination,
        args.marked_destination, args.previously_observed
    ), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
