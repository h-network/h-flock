#!/usr/bin/env python3
"""analyse-verification — how often did `delivery_unverified` cry wolf?

    analyse-verification.py custody.jsonl

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

**So the false-negative rate this reports is a LOWER BOUND.** The real rate can
only be higher. A lower bound is the honest thing to quote when the alternative
is watching panes and estimating.

⚠ **Reads the durable custody file** (`FLOCK_CUSTODY_FILE`, build 79), not
`docker logs` — a teardown between the run and the analysis used to destroy the
input to this script.
"""
from __future__ import annotations

import collections
import json
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
    if len(sys.argv) != 2:
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        print("usage: analyse-verification.py <custody.jsonl>", file=sys.stderr)
        return 2

    flags: list[dict] = []
    # agent -> sorted timestamps at which that agent demonstrably did something
    alive_at: dict[str, list[float]] = collections.defaultdict(list)
    opened = unjudged = 0

    with open(sys.argv[1], encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event, when = rec.get("event"), _ts(rec.get("ts"))
            if event == "opened":
                opened += 1
            elif event == "delivery_unjudged":
                unjudged += 1
            elif event == "delivery_unverified":
                flags.append(rec)

            # ⚠ `sent` is the strong signal: the agent composed and sent
            # something, which a wedged process or a login prompt cannot do.
            # `opened` alone is the PORT's work, not the agent's, so it proves
            # nothing about whether the agent is alive — do not count it here.
            if event == "sent" and when is not None:
                source = rec.get("source")
                if source:
                    alive_at[source].append(when)

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
    print(f"deliveries opened          {opened}")
    print(f"delivery_unjudged          {unjudged}")
    print(f"delivery_unverified        {total}")
    if opened:
        print(f"  as a share of opened     {total / opened:.1%}")
    print()
    if not total:
        print("no verification flags — nothing to judge")
        return 0

    print(f"REFUTED (agent sent later) {refuted}")
    print(f"  false-negative rate      {refuted / total:.1%}   ⚠ LOWER BOUND")
    print(f"unrefuted                  {total - refuted}")
    print()
    print("per agent            flagged  refuted")
    for agent, (flagged, ref) in sorted(per_agent.items()):
        print(f"  {agent:<18} {flagged:>7}  {ref:>7}")

    # ⚠ Deliberately not a threshold or an exit code. This script reports a
    # number; deciding whether it is acceptable is a person's job, and a script
    # that returns non-zero on a bad rate would get wrapped in `|| true` inside
    # a week.
    return 0


if __name__ == "__main__":
    sys.exit(main())
