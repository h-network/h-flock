#!/usr/bin/env python3
"""analyse-verification — how often did `delivery_unverified` cry wolf?

    analyse-verification.py <custody.jsonl> [--max-refuted N] [--max-refuted-rate FLOAT]

`analyse-run.py` only knows the six custody stages and ignores verification
records entirely, which is why the 30-92% false-negative rates in `TODO.md` were
eyeballed from a terminal rather than computed. This computes them.

⚠ **The oracle is the agent's own later traffic.** If agent A was flagged
`delivery_unverified` for stream S at time T, and A emitted ANY custody record of
its own after T, then A was alive and working — so the flag was wrong. That is a
one-directional test and it is deliberately conservative:

- an agent that *was* wedged emits nothing, and is correctly counted as a true
  positive
- an agent that was alive but happened to stay silent for the rest of the run is
  counted as a true positive too, even though the flag may have been wrong

⚠ **STRUCTURAL LIMITATION: ONE-SIDED ORACLE**
This analyser measures only false alarms / wolf-cries (flags raised for agents
that were demonstrably alive). It structurally CANNOT detect false negatives
(agents that were wedged/silent but never flagged because no delivery was pending
or the verifier failed to run). It is a lower bound on verification error.

⚠ **Verdict Contract:**
  0    pass: refuted count <= max_refuted (default 0)
  1+   fail: count of refuted flags (wolf-cries) exceeding threshold
  100  incomplete: input file missing or empty (could not run)
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys
from datetime import datetime


def _ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Judge delivery_unverified false-alarm rate from a captured custody log."
    )
    parser.add_argument("custody_log", nargs="?", default=None, help="path to custody.jsonl log file")
    parser.add_argument(
        "--max-refuted",
        type=int,
        default=0,
        help="maximum number of refuted flags allowed before failing (default: 0)",
    )
    parser.add_argument(
        "--max-refuted-rate",
        type=float,
        default=None,
        help="maximum refuted fraction allowed (0.0 - 1.0)",
    )
    args = parser.parse_args()

    if not args.custody_log:
        print("RESULT analyse-verification incomplete reason=missing_argument", file=sys.stderr)
        return 100

    path = Path(args.custody_log)
    if not path.is_file():
        print(f"RESULT analyse-verification incomplete reason=file_not_found path={path}", file=sys.stderr)
        return 100

    flags: list[dict] = []
    alive_at: dict[str, list[float]] = collections.defaultdict(list)
    opened = unjudged = total_records = 0

    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw.startswith("{"):
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                total_records += 1
                event, when = rec.get("event"), _ts(rec.get("ts"))
                if event == "opened":
                    opened += 1
                elif event == "delivery_unjudged":
                    unjudged += 1
                elif event == "delivery_unverified":
                    flags.append(rec)

                # `sent` is the strong signal: the agent composed and sent
                # something, proving it was alive and not wedged.
                if event == "sent" and when is not None:
                    source = rec.get("source")
                    if source:
                        alive_at[source].append(when)
    except Exception as exc:
        print(f"RESULT analyse-verification incomplete reason=read_error error={exc}", file=sys.stderr)
        return 100

    if total_records == 0:
        print(f"RESULT analyse-verification incomplete reason=no_records path={path}", file=sys.stderr)
        return 100

    for times in alive_at.values():
        times.sort()

    refuted = 0
    per_agent: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for flag in flags:
        agent = flag.get("destination") or "?"
        when = _ts(flag.get("ts"))
        later = any(t > when for t in alive_at.get(agent, ())) if when else False
        per_agent[agent][0] += 1
        if later:
            refuted += 1
            per_agent[agent][1] += 1

    total = len(flags)
    rate = (refuted / total) if total else 0.0

    print(f"deliveries opened          {opened}")
    print(f"delivery_unjudged          {unjudged}")
    print(f"delivery_unverified        {total}")
    if opened:
        print(f"  as a share of opened     {total / opened:.1%}")
    print()
    if total:
        print(f"REFUTED (agent sent later) {refuted}")
        print(f"  false-negative rate      {rate:.1%}   ⚠ LOWER BOUND (wolf-cries only)")
        print(f"unrefuted                  {total - refuted}")
        print()
        print("per agent            flagged  refuted")
        for agent, (flagged, ref) in sorted(per_agent.items()):
            print(f"  {agent:<18} {flagged:>7}  {ref:>7}")
        print()
    else:
        print("no verification flags — 0 unverified events to judge")
        print()

    print(
        "NOTE: Oracle measures ONLY false alarms (flags refuted by subsequent agent traffic).\n"
        "It structurally CANNOT detect false negatives (silent wedged agents that were never flagged)."
    )

    failed = 0
    if refuted > args.max_refuted:
        failed = max(1, refuted - args.max_refuted)
    elif args.max_refuted_rate is not None and total and rate > args.max_refuted_rate:
        failed = max(1, refuted)

    if failed == 0:
        print(f"RESULT analyse-verification pass total_flags={total} refuted={refuted} rate={rate:.1%}")
        return 0
    else:
        extra = f" max_rate={args.max_refuted_rate:.1%}" if args.max_refuted_rate is not None else ""
        print(
            f"RESULT analyse-verification fail failed={failed} total_flags={total} "
            f"refuted={refuted} allowed={args.max_refuted} rate={rate:.1%}{extra}",
            file=sys.stderr,
        )
        return min(failed, 125)


if __name__ == "__main__":
    sys.exit(main())
