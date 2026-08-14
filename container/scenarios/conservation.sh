#!/usr/bin/env bash
# Conservation under injected switch and port death.
# Run on the Docker host and redirect stdout/stderr to a host-local file.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
STATIONS="${STATIONS:-100}"
ROUNDS="${ROUNDS:-100}"
SEND_DELAY="${SEND_DELAY:-0.01}"
WORK="${WORK:-/tmp/conservation-${TENANT}}"
REDIS_URL="redis://127.0.0.1:6379/0"
mkdir -p "$WORK"
: >"$WORK/injections.tsv"
: >"$WORK/samples.tsv"

dx() { docker exec -i "$CONTAINER" "$@"; }
tmux_switch=""
test_switch=""
sampler=""

cleanup() {
  [ -n "$sampler" ] && kill "$sampler" 2>/dev/null || true
  if [ -n "$test_switch" ]; then
    dx kill -9 "$test_switch" >/dev/null 2>&1 || true
  fi
  if [ -n "$tmux_switch" ]; then
    dx kill -CONT "$tmux_switch" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

seed_stations() {
  dx python3 - "$POD" "$TENANT" "$STATIONS" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import prefix
pod, tenant, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
r.hset(prefix(pod, tenant, resource="roster"), mapping={f"cons-{i}": "api" for i in range(count)})
PY
}

clear_station_state() {
  dx python3 - "$POD" "$TENANT" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import prefix
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
keys = list(r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:cons-*"))
if keys:
    r.delete(*keys)
PY
}

start_test_switch() {
  dx sh -c "env REDIS_URL='$REDIS_URL' POD='$POD' TENANT='$TENANT' ROSTER_POLL_SECONDS=1 ACTIVITY_POLL_SECONDS=60 python3 -m flock.switch >/tmp/conservation-switch.log 2>&1 & echo \$!" | tr -d '\r'
}

wait_for_queues() {
  local limit="${1:-2400}" depths
  for _ in $(seq 1 "$limit"); do
    depths="$(dx python3 - "$POD" "$TENANT" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
total = 0
for pattern in (f"pod:{pod}:tenant:{tenant}:agent:*:egress", f"pod:{pod}:tenant:{tenant}:agent:*:ingress"):
    for key in r.scan_iter(match=pattern):
        total += r.llen(key)
print(total)
PY
)"
    [ "$depths" = "0" ] && [ "$(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:delivering" | tr -d '\r')" = "0" ] && return 0
    sleep 1
  done
  echo "queue drain timeout remaining=$depths"
  return 1
}

snapshot() {
  local elapsed="$1"
  dx python3 - "$POD" "$TENANT" "$elapsed" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
pod, tenant, elapsed = sys.argv[1:4]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
info = r.info("memory")
q = 0
for suffix in ("egress", "ingress", "dead"):
    for key in r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:*:{suffix}"):
        q += r.llen(key)
rss = 0
try:
    with open("/proc/1/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
except OSError:
    pass
print(f"{elapsed}\t{info['used_memory']}\t{q}\t{rss}")
PY
}

reconcile() {
  local ledger="$1" label="$2"
  docker logs "$CONTAINER" >"$WORK/${label}.docker.log" 2>&1
  dx python3 - "$POD" "$TENANT" >"$WORK/${label}.dead.jsonl" <<'PY'
import json, os, sys
sys.path.insert(0, "/app/src")
import redis
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
for key in r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:*:dead"):
    for raw in r.lrange(key, 0, -1):
        try: print(json.dumps(json.loads(raw)))
        except Exception: print("__CONSERVATION_DEAD_JSON_PARSE_FAILURE__")
PY
  dx python3 - "$POD" "$TENANT" >"$WORK/${label}.ingress.jsonl" <<'PY'
import json, os, sys
sys.path.insert(0, "/app/src")
import redis
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
for key in r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:*:ingress"):
    for raw in r.lrange(key, 0, -1):
        try: print(json.dumps(json.loads(raw)))
        except Exception: print("__CONSERVATION_INGRESS_JSON_PARSE_FAILURE__")
PY
  python3 - "$ledger" "$WORK/${label}.docker.log" "$WORK/${label}.dead.jsonl" "$WORK/${label}.ingress.jsonl" "$WORK/injections.tsv" <<'PY'
import collections, datetime, json, sys
ledger_path, log_path, dead_path, ingress_path, injection_path = sys.argv[1:]
sent = {}
with open(ledger_path) as f:
    for line in f:
        if not line.strip(): continue
        seq, sid, dst, ts = line.rstrip().split("\t")
        sent[seq] = (sid, dst, float(ts))
opened = collections.Counter()
events = collections.defaultdict(list)
log_parse_failures = 0
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
    run_start = min(value[2] for value in sent.values())
    run_end = max(value[2] for value in sent.values())
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
duplicates, dead_loss, stranded, attributed, unexplained = [], [], [], [], []
event_time_failures = 0
for seq, (sid, dst, sent_ts) in sent.items():
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
        cause = None
        ev = events.get(sid, [])
        event_times = []
        for rec in ev:
            try: event_times.append(datetime.datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp())
            except Exception: event_time_failures += 1
        for start, end, kind, detail in windows:
            if start - 2 <= sent_ts <= end + 2 or any(start - 1 <= t <= end + 1 for t in event_times):
                cause = f"{kind}:{detail}"
                break
        (attributed if cause else unexplained).append((seq, sid, cause or "none"))
print(f"RECONCILE sent={len(sent)} delivered_once={sum(opened[sid] == 1 for sid, _, _ in sent.values())} duplicates={len(duplicates)} dead={len(dead_loss)} stranded={len(stranded)} lost_attributed={len(attributed)} lost_unexplained={len(unexplained)}")
print(f"PARSE_FAILURES docker_json={log_parse_failures} dead_json={dead_parse_failures} ingress_json={ingress_parse_failures} event_ts={event_time_failures}")
print(f"INJECTION_COVERAGE seconds={coverage:.3f} fraction={coverage_fraction:.6f}")
for row in duplicates[:10]: print("DUPLICATE", *row)
for row in stranded[:10]: print("STRANDED", *row)
for row in attributed[:10]: print("LOSS_ATTRIBUTED", *row)
for row in unexplained[:10]: print("LOSS_UNEXPLAINED", *row)
sys.exit(4 if (log_parse_failures or dead_parse_failures or ingress_parse_failures or event_time_failures) else (2 if duplicates else (1 if unexplained else 0)))
PY
}

if [ "${RECONCILE_ONLY:-0}" = "1" ]; then
  reconcile "${LEDGER:?set LEDGER}" "${LABEL:-clean}"
  exit $?
fi

echo "conservation container=$CONTAINER stations=$STATIONS rounds=$ROUNDS work=$WORK"
seed_stations
clear_station_state
seed_stations

echo "== negative control: duplicate =="
: >"$WORK/negative-duplicate.tsv"
dx python3 - "$POD" "$TENANT" >"$WORK/negative-duplicate.tsv" <<'PY'
import json, os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, prefix
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
frame = build("Message", "cons-0", "cons-1", {"sequence": "negative-duplicate"}, pod=pod, tenant=tenant)
raw = json.dumps(frame, separators=(",", ":"))
print(f"negative-duplicate\t{frame['stream_id']}\tcons-1\t{time.time()}")
r.rpush(prefix(pod, tenant, "cons-0", "egress"), raw, raw)
PY
wait_for_queues
if reconcile "$WORK/negative-duplicate.tsv" negative-duplicate >"$WORK/negative-duplicate.result"; then
  cat "$WORK/negative-duplicate.result"
  echo "HARNESS DEFECT: intentional duplicate passed silently"
  exit 3
else
  rc=$?; cat "$WORK/negative-duplicate.result"
  [ "$rc" = "2" ] || { echo "HARNESS DEFECT: duplicate control failed for wrong reason rc=$rc"; exit 3; }
fi

echo "== negative control: loss =="
clear_station_state; seed_stations
tmux_switch="$(dx pgrep -f 'python3 -m flock.switch' | head -1 | tr -d '\r')"
dx kill -STOP "$tmux_switch"
: >"$WORK/negative-loss.tsv"
dx python3 - "$POD" "$TENANT" >"$WORK/negative-loss.tsv" <<'PY'
import json, os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, prefix
pod, tenant = sys.argv[1:3]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
frame = build("Message", "cons-0", "cons-1", {"sequence": "negative-loss"}, pod=pod, tenant=tenant)
print(f"negative-loss\t{frame['stream_id']}\tcons-1\t{time.time()}")
r.rpush(prefix(pod, tenant, "cons-0", "egress"), json.dumps(frame, separators=(",", ":")))
r.lpop(prefix(pod, tenant, "cons-0", "egress"))
PY
if reconcile "$WORK/negative-loss.tsv" negative-loss >"$WORK/negative-loss.result"; then
  cat "$WORK/negative-loss.result"
  echo "HARNESS DEFECT: intentional loss passed silently"
  exit 3
else
  rc=$?; cat "$WORK/negative-loss.result"
  [ "$rc" = "1" ] || { echo "HARNESS DEFECT: loss control failed for wrong reason rc=$rc"; exit 3; }
fi

echo "== clean stressed run =="
clear_station_state; seed_stations
: >"$WORK/ledger.tsv"; : >"$WORK/injections.tsv"; : >"$WORK/samples.tsv"
test_switch="$(start_test_switch)"
run_start="$(date +%s)"
(
  while true; do
    now="$(date +%s)"
    snapshot "$((now-run_start))" >>"$WORK/samples.tsv" 2>/dev/null || true
    sleep 60
  done
) & sampler=$!

docker exec -i "$CONTAINER" python3 -u - "$POD" "$TENANT" "$STATIONS" "$ROUNDS" "$SEND_DELAY" >"$WORK/ledger.tsv" <<'PY' &
import json, os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, prefix
pod, tenant, stations, rounds, delay = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
for rnd in range(rounds):
    for i in range(stations):
        seq = rnd * stations + i
        dst = f"cons-{(i + 1) % stations}"
        frame = build("Message", f"cons-{i}", dst, {"sequence": seq}, pod=pod, tenant=tenant)
        print(f"{seq}\t{frame['stream_id']}\t{dst}\t{time.time()}", flush=True)
        r.rpush(prefix(pod, tenant, f"cons-{i}", "egress"), json.dumps(frame, separators=(",", ":")))
        if delay: time.sleep(delay)
PY
producer=$!

for target in 1000 2200 3400 4600 5800 7000 8200 9400; do
  while [ "$(wc -l <"$WORK/ledger.tsv")" -lt "$target" ] && kill -0 "$producer" 2>/dev/null; do sleep 0.1; done
  start="$(date +%s.%N)"
  if [ $((target / 100)) -eq 22 ] || [ $((target / 100)) -eq 58 ] || [ $((target / 100)) -eq 94 ]; then
    old="$test_switch"
    dx kill -9 "$old" 2>/dev/null || true
    sleep 0.2
    test_switch="$(start_test_switch)"
    end="$(date +%s.%N)"
    printf '%s\t%s\tswitch-kill\told=%s,new=%s,target=%s\n' "$start" "$end" "$old" "$test_switch" "$target" | tee -a "$WORK/injections.tsv"
  else
    killed=""
    until [ -n "$killed" ]; do
      killed="$(dx sh -c "ps -eo pid=,args= | awk '/flock.port cons-/ && !/awk/ {print \$1; exit}'" | tr -d '\r')"
      [ -n "$killed" ] || sleep 0.02
    done
    dx kill -9 "$killed" 2>/dev/null || true
    end="$(date +%s.%N)"
    printf '%s\t%s\tport-kill\tpid=%s,target=%s\n' "$start" "$end" "$killed" "$target" | tee -a "$WORK/injections.tsv"
  fi
done
wait "$producer"
wait_for_queues
kill "$sampler" 2>/dev/null || true; sampler=""
snapshot "$(( $(date +%s) - run_start ))" >>"$WORK/samples.tsv" 2>/dev/null || true
dx kill -9 "$test_switch" 2>/dev/null || true; test_switch=""
dx kill -CONT "$tmux_switch"; tmux_switch=""

echo "== growth samples: elapsed_s used_memory_bytes queue_depth pid1_rss_kib =="
cat "$WORK/samples.tsv"
echo "== reconciliation =="
reconcile "$WORK/ledger.tsv" clean
