#!/usr/bin/env python3
"""Reconcile one unicast ledger against static custody and queue captures."""

import collections, datetime, json, sys
ledger_path, log_path, dead_path, ingress_path, injection_path = sys.argv[1:]
sent = {}
with open(ledger_path) as f:
    for line in f:
        if not line.strip(): continue
        fields = line.rstrip().split("\t")
        if len(fields) == 5:
            seq, sid, source, dst, ts = fields
        else:
            # Evidence predating source capture remains readable, but cannot
            # use same-source FIFO bracketing for an otherwise silent loss.
            seq, sid, dst, ts = fields
            source = None
        sent[seq] = (sid, source, dst, float(ts))
opened = collections.Counter()
events = collections.defaultdict(list)
log_parse_failures = 0
legacy_attempts = 0
with open(log_path, errors="replace") as f:
    for line in f:
        if not line.lstrip().startswith("{"):
            continue
        try: rec = json.loads(line)
        except Exception:
            log_parse_failures += 1
            continue
        sid = rec.get("stream_id")
        if not sid: continue
        if rec.get("event") in {"send_failed", "forward_failed", "kick_failed"}:
            legacy_attempts += 1
        events[sid].append(rec)
        if rec.get("event") == "opened": opened[sid] += 1
dead = set()
dead_parse_failures = 0
with open(dead_path) as f:
    for line in f:
        if not line.strip():
            continue
        try: dead.add(json.loads(line).get("stream_id"))
        except Exception:
            dead_parse_failures += 1
ingress = set()
ingress_parse_failures = 0
with open(ingress_path) as f:
    for line in f:
        if not line.strip():
            continue
        try: ingress.add(json.loads(line).get("stream_id"))
        except Exception:
            ingress_parse_failures += 1
windows = []
with open(injection_path) as f:
    for line in f:
        if line.strip():
            start, end, kind, detail = line.rstrip().split("\t", 3)
            windows.append((float(start), float(end), kind, detail))
coverage = 0.0
coverage_fraction = 0.0
if sent and windows:
    run_start = min(value[3] for value in sent.values())
    run_end = max(value[3] for value in sent.values())
    intervals = []
    merged = []
    for start, end, _, _ in windows:
        left, right = max(run_start, start - 2), min(run_end, end + 2)
        if right > left:
            intervals.append((left, right))
    for left, right in sorted(intervals):
        if not merged or left > merged[-1][1]:
            merged.append([left, right])
        else:
            merged[-1][1] = max(merged[-1][1], right)
    coverage = sum(right - left for left, right in merged)
    duration = max(0.0, run_end - run_start)
    coverage_fraction = coverage / duration if duration else 0.0
duplicates, dead_loss, stranded, indeterminate, attributed, unexplained = [], [], [], [], [], []
event_time_failures = 0
def event_times(sid, wanted=None):
    global event_time_failures
    result = []
    for rec in events.get(sid, []):
        if wanted is not None and rec.get("event") != wanted:
            continue
        try: result.append(datetime.datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp())
        except Exception: event_time_failures += 1
    return result

source_order = collections.defaultdict(list)
for seq, (sid, source, _, _) in sent.items():
    if source is not None:
        source_order[source].append((int(seq), sid))
for rows in source_order.values():
    rows.sort()

def switch_kill_bracket(seq, sid, source):
    """Attribute only when FIFO neighbours prove a kill crossed this pop."""
    if source is None or event_times(sid, "popped"):
        return None
    rows = source_order[source]
    position = next((i for i, row in enumerate(rows) if row[0] == int(seq)), None)
    if position is None:
        return None
    before = next(
        (event_times(other_sid, "popped")[-1] for _, other_sid in reversed(rows[:position])
         if event_times(other_sid, "popped")),
        None,
    )
    after = next(
        (event_times(other_sid, "popped")[0] for _, other_sid in rows[position + 1:]
         if event_times(other_sid, "popped")),
        None,
    )
    if before is None or after is None:
        return None
    for start, end, kind, detail in windows:
        if kind == "switch-kill" and before <= start <= end <= after:
            return f"{kind}:{detail}:fifo-bracket={before:.6f}..{after:.6f}"
    return None

for seq, (sid, source, dst, sent_ts) in sent.items():
    count = opened[sid]
    if count > 1:
        duplicates.append((seq, sid, count))
    elif count == 0:
        if sid in dead:
            dead_loss.append((seq, sid))
            continue
        if sid in ingress:
            stranded.append((seq, sid))
            continue
        # A later opened/dead/ingress observation settles an unanswered write.
        # With none of those, forward_unknown is neither a forward nor a loss:
        # folding it into either side would manufacture evidence the switch did
        # not observe, and treating it as loss could provoke a duplicate retry.
        if any(rec.get("event") == "forward_unknown" for rec in events.get(sid, [])):
            indeterminate.append((seq, sid))
            continue
        # A recordless switch loss is strongest when same-source FIFO
        # neighbours bracket the kill. Prefer that direct ordering evidence to
        # the deliberately padded timestamp-window fallback.
        cause = switch_kill_bracket(seq, sid, source)
        times = event_times(sid)
        if cause is None:
            for start, end, kind, detail in windows:
                if start - 2 <= sent_ts <= end + 2 or any(start - 1 <= t <= end + 1 for t in times):
                    cause = f"{kind}:{detail}"
                    break
        (attributed if cause else unexplained).append((seq, sid, cause or "none"))
print(f"RECONCILE sent={len(sent)} delivered_once={sum(opened[sid] == 1 for sid, _, _, _ in sent.values())} duplicates={len(duplicates)} dead={len(dead_loss)} stranded={len(stranded)} indeterminate={len(indeterminate)} lost_attributed={len(attributed)} lost_unexplained={len(unexplained)}")
print(f"PARSE_FAILURES docker_json={log_parse_failures} dead_json={dead_parse_failures} ingress_json={ingress_parse_failures} event_ts={event_time_failures} legacy_attempts={legacy_attempts}")
print(f"INJECTION_COVERAGE seconds={coverage:.3f} fraction={coverage_fraction:.6f}")
for row in duplicates[:10]: print("DUPLICATE", *row)
for row in stranded[:10]: print("STRANDED", *row)
for row in indeterminate[:10]: print("INDETERMINATE_FORWARD", *row)
for row in attributed[:10]: print("LOSS_ATTRIBUTED", *row)
for row in unexplained[:10]: print("LOSS_UNEXPLAINED", *row)
if legacy_attempts:
    print("REFUSED: legacy *_failed attempt records require a version-specific analyser")
sys.exit(4 if (log_parse_failures or dead_parse_failures or ingress_parse_failures or event_time_failures or legacy_attempts) else (2 if duplicates else (5 if indeterminate else (1 if unexplained else 0))))
