"""Measure a run from its captured custody log. Nothing runs; nothing is polled."""
import json, statistics, sys, collections, datetime

STAGES = ["sent", "popped", "forwarded", "received", "opened"]

def t(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

paths = collections.defaultdict(dict)
opened = []
bad = 0
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        d = json.loads(line)
    except Exception:
        bad += 1
        continue
    ev, sid = d.get("event"), d.get("stream_id")
    if ev not in STAGES or not sid or sid == "unknown":
        continue
    key = (sid, d.get("destination") or "")
    paths[key].setdefault(ev, d["ts"])
    if ev == "opened":
        opened.append(t(d["ts"]))

print(f"parse failures: {bad}   joined paths: {len(paths):,}   opened: {len(opened):,}")

# steady state: middle 80% of the delivery window
opened.sort()
lo, hi = opened[len(opened)//10], opened[-max(1, len(opened)//10)]
mid = [x for x in opened if lo <= x <= hi]
print(f"\nsteady-state throughput (middle 80%): {len(mid)/(hi-lo):.2f}/s   window {hi-lo:.1f}s")
print(f"wall-clock over all opened      : {len(opened)/(opened[-1]-opened[0]):.2f}/s")

print("\nper-stage median latency, joined on (stream_id, recipient):")
for a, b in zip(STAGES, STAGES[1:]):
    d = [t(p[b]) - t(p[a]) for p in paths.values() if a in p and b in p]
    if d:
        d.sort()
        print(f"  {a:>9} -> {b:<9} n={len(d):>6}  p50 {statistics.median(d)*1000:8.2f} ms"
              f"  p95 {d[int(len(d)*0.95)]*1000:9.2f} ms")

e2e = sorted(t(p["opened"]) - t(p["sent"]) for p in paths.values() if "sent" in p and "opened" in p)
if e2e:
    print(f"\nend to end  n={len(e2e)}  p50 {statistics.median(e2e)*1000:.1f} ms"
          f"  p95 {e2e[int(len(e2e)*0.95)]*1000:.1f} ms  p99 {e2e[int(len(e2e)*0.99)]*1000:.1f} ms")
