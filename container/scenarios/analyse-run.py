#!/usr/bin/env python3
"""Measure a captured run from its custody log. Nothing runs; nothing is polled.

    analyse-run.py RUN.log [--expect N] [--source-prefix bench-]

Two questions:
  1. how fast, per stage
  2. **is every step logged** — coverage, not averages

⚠ **A stage whose sample does not cover the run is REFUSED, not averaged.** The
first version of this script reported `sent → popped` from n=100 of 2,000 and I
quoted the figure; it described enrolment traffic, not the run. `bus` caught it
by using the output. Partial coverage is a finding about the LOG, and averaging
it hides exactly what we are trying to see.

⚠ **Control traffic is not workload.** Enrolment produces real deliveries with
real records. `--source-prefix` keeps them out of the numbers.
"""
import argparse
import collections
import datetime
import json
import math
import statistics
import sys

# ⚠ Every handover the system logs, in order. `kick_started` (build 65) splits
# the largest gap in the path: `forwarded -> kick_started` is the switch issuing
# the spawn, `kick_started -> received` is the process actually starting and
# popping. Without it the two are one 669 ms number and indistinguishable.
STAGES = ["sent", "popped", "forwarded", "kick_started", "received", "opened"]
LEGACY_ATTEMPT_EVENTS = {"send_failed", "forward_failed", "kick_failed"}


def ts(value: str) -> float:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--expect", type=int, default=None,
                    help="envelopes the workload should have produced")
    ap.add_argument("--source-prefix", default=None,
                    help="only count envelopes whose source starts with this")
    ap.add_argument("--writer", action="append", default=[],
                    help="only count records from this writer; repeatable")
    ap.add_argument("--exclude-writer", action="append", default=[],
                    help="exclude records from this writer; repeatable")
    ap.add_argument("--expect-writer", action="append", default=[], metavar="NAME=COUNT",
                    help="accept a synthetic writer only at this exact count; repeatable")
    ap.add_argument("--coverage", type=float, default=0.99,
                    help="a stage below this fraction of expect is REFUSED")
    args = ap.parse_args()

    paths: dict[tuple, dict] = collections.defaultdict(dict)
    parse_failures = 0
    dead = 0
    indeterminate_forwards = set()
    legacy_attempts = 0
    writers = collections.Counter()
    selected_writers = set(args.writer)
    excluded_writers = set(args.exclude_writer)
    expected_writers = {}
    for value in args.expect_writer:
        try:
            name, count = value.rsplit("=", 1)
            if not name or int(count) < 0:
                raise ValueError
            expected_writers[name] = int(count)
        except ValueError:
            ap.error(f"--expect-writer requires NAME=COUNT, got {value!r}")

    for line in open(args.log, errors="replace"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except Exception:
            parse_failures += 1
            continue
        writer = str(rec.get("writer") or rec.get("module") or "unknown")
        if selected_writers and writer not in selected_writers:
            continue
        if writer in excluded_writers:
            continue
        writers[writer] += 1
        event = rec.get("event")
        if event in LEGACY_ATTEMPT_EVENTS:
            legacy_attempts += 1
        if event == "dead_lettered":
            dead += 1
        if event == "forward_unknown":
            sid = rec.get("stream_id")
            if sid and sid != "unknown" and (
                not args.source_prefix
                or str(rec.get("source", "")).startswith(args.source_prefix)
            ):
                indeterminate_forwards.add(sid)
        if event not in STAGES:
            continue
        sid = rec.get("stream_id")
        if not sid or sid == "unknown":
            continue
        if args.source_prefix and not str(rec.get("source", "")).startswith(args.source_prefix):
            continue
        paths[(sid, rec.get("destination") or "")].setdefault(event, rec["ts"])

    # ⚠ Parse failures invalidate everything downstream: a dropped record becomes
    # a phantom missing stage. Refuse before interpreting anything.
    if parse_failures:
        print(f"REFUSED: {parse_failures} unparseable JSON lines — the log is not trustworthy")
        print(f"RESULT analyse-run fail failed={parse_failures}")
        return min(parse_failures, 125)
    if legacy_attempts:
        print(
            f"REFUSED: {legacy_attempts} legacy *_failed attempt records — "
            "use a version-specific analyser"
        )
        print(f"RESULT analyse-run fail failed={legacy_attempts}")
        return 4

    n = len(paths)
    expect = args.expect or n
    print(
        f"envelopes {n:,}   expected {expect:,}   dead-lettered {dead}   "
        f"indeterminate forwards {len(indeterminate_forwards)}   parse failures 0"
    )
    census = "  ".join(f"{writer}={count}" for writer, count in sorted(writers.items())) or "none"
    bench_writers = sorted({"bench-send", "bench-port"}.intersection(writers))
    writer_errors = []
    for writer in bench_writers:
        expected_count = expected_writers.get(writer)
        if expected_count is None:
            writer_errors.append(f"{writer} was not explicitly expected")
        elif writers[writer] != expected_count:
            writer_errors.append(
                f"{writer} count {writers[writer]} != expected {expected_count}"
            )
    for writer, expected_count in sorted(expected_writers.items()):
        if writer not in writers:
            writer_errors.append(f"{writer} count 0 != expected {expected_count}")
    writer_refused = bool(writer_errors)
    suffix = ""
    if writer_refused:
        suffix = "  ⚠ REFUSED — " + "; ".join(writer_errors)
    print(f"writers: {census}{suffix}")

    print("\n== every step logged? ==")
    incomplete = bool(indeterminate_forwards)
    missing_expectation = any("not explicitly expected" in error for error in writer_errors)
    failed = sum("not explicitly expected" not in error for error in writer_errors)
    if indeterminate_forwards:
        print(
            f"  forward_unknown {len(indeterminate_forwards):>7,}  ⚠ REFUSED — "
            "write outcome is neither forwarded nor lost"
        )
    for stage in STAGES:
        have = sum(1 for p in paths.values() if stage in p)
        frac = have / expect if expect else 0
        if frac < args.coverage:
            print(f"  {stage:<12} {have:>7,} / {expect:,}  {frac:7.1%}  ⚠ REFUSED — does not cover the run")
            incomplete = True
        elif frac > 1.01:
            # ⚠ MORE records than expected is not success. It means the log holds
            # traffic this run did not produce — a stale tenant, a leftover
            # process, or the wrong filter — and every figure below is mixed.
            print(f"  {stage:<12} {have:>7,} / {expect:,}  {frac:7.1%}  ⚠ REFUSED — log holds traffic this run did not produce")
            incomplete = True
        else:
            print(f"  {stage:<12} {have:>7,} / {expect:,}  {frac:7.1%}  ok")

    print("\n== per-stage latency (median, p95) ==")
    for a, b in zip(STAGES, STAGES[1:]):
        d = sorted(ts(p[b]) - ts(p[a]) for p in paths.values() if a in p and b in p)
        if len(d) < expect * args.coverage:
            needed = math.ceil(expect * args.coverage)
            print(f"  {a:>9} -> {b:<10} REFUSED (n={len(d):,}, needs {needed:,})")
            continue
        print(f"  {a:>9} -> {b:<10} n={len(d):>7,}  p50 {statistics.median(d)*1000:8.2f} ms"
              f"  p95 {d[int(len(d)*0.95)]*1000:9.2f} ms")

    opened = sorted(ts(p["opened"]) for p in paths.values() if "opened" in p)
    if len(opened) > 20:
        # ⚠ Steady state, not wall clock. Wall clock keeps counting through a
        # drain in which nothing arrives — 21% apart on the same run.
        lo, hi = opened[len(opened) // 10], opened[-max(1, len(opened) // 10)]
        mid = [x for x in opened if lo <= x <= hi]
        print(f"\nsteady-state (middle 80%) {len(mid)/(hi-lo):8.2f}/s over {hi-lo:.1f}s")
        print(f"wall-clock, all opened     {len(opened)/(opened[-1]-opened[0]):8.2f}/s")

    if missing_expectation:
        print("RESULT analyse-run incomplete reason=writer_expectation_required")
        return 100
    if failed:
        print(f"RESULT analyse-run fail failed={failed}")
        return min(failed, 125)
    if incomplete:
        print("\n⚠ AT LEAST ONE STEP IS NOT FULLY LOGGED. Latency figures for refused"
              "\n  stages are withheld; the rest describe only the envelopes that have them.")
        print("RESULT analyse-run incomplete reason=partial_coverage")
        return 100
    print("RESULT analyse-run pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
