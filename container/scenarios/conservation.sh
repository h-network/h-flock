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
if [ "${RECONCILE_ONLY:-0}" != "1" ]; then
  : >"$WORK/injections.tsv"
  : >"$WORK/samples.tsv"
fi

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
  # Reconciliation reads docker logs, so every custody emitter must inherit
  # PID 1's stdout. A docker-exec session or a private file is not evidence.
  dx sh -c "env REDIS_URL='$REDIS_URL' POD='$POD' TENANT='$TENANT' ROSTER_POLL_SECONDS=1 ACTIVITY_POLL_SECONDS=60 python3 -m flock.switch >>/proc/1/fd/1 2>&1 & echo \$!" | tr -d '\r'
}

wait_for_queues() {
  local deadline=$((SECONDS + ${1:-2400})) depths
  while [ "$SECONDS" -lt "$deadline" ]; do
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
duplicates, dead_loss, stranded, attributed, unexplained = [], [], [], [], []
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
        cause = None
        times = event_times(sid)
        for start, end, kind, detail in windows:
            if start - 2 <= sent_ts <= end + 2 or any(start - 1 <= t <= end + 1 for t in times):
                cause = f"{kind}:{detail}"
                break
        if cause is None:
            cause = switch_kill_bracket(seq, sid, source)
        (attributed if cause else unexplained).append((seq, sid, cause or "none"))
print(f"RECONCILE sent={len(sent)} delivered_once={sum(opened[sid] == 1 for sid, _, _, _ in sent.values())} duplicates={len(duplicates)} dead={len(dead_loss)} stranded={len(stranded)} lost_attributed={len(attributed)} lost_unexplained={len(unexplained)}")
print(f"PARSE_FAILURES docker_json={log_parse_failures} dead_json={dead_parse_failures} ingress_json={ingress_parse_failures} event_ts={event_time_failures}")
print(f"INJECTION_COVERAGE seconds={coverage:.3f} fraction={coverage_fraction:.6f}")
for row in duplicates[:10]: print("DUPLICATE", *row)
for row in stranded[:10]: print("STRANDED", *row)
for row in attributed[:10]: print("LOSS_ATTRIBUTED", *row)
for row in unexplained[:10]: print("LOSS_UNEXPLAINED", *row)
sys.exit(4 if (log_parse_failures or dead_parse_failures or ingress_parse_failures or event_time_failures) else (2 if duplicates else (1 if unexplained else 0)))
PY
}

build67_redis() {
  dx python3 - "$POD" "$TENANT" "$@"
}

build67_state() {
  build67_redis "$1" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import prefix
pod, tenant, action = sys.argv[1:4]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
roster = prefix(pod, tenant, resource="roster")
names = ("stress-src", "stress-paused", "stress-clean", "stress-api", "host")
if action == "seed":
    r.hset(roster, mapping={"stress-src": "api", "stress-paused": "api", "stress-clean": "api", "stress-api": "api", "host": "control"})
elif action == "clear":
    keys = []
    for name in names:
        keys.extend(r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:{name}:*"))
    keys.append(prefix(pod, tenant, resource="delivering"))
    if keys: r.delete(*set(keys))
PY
}

build67_push() {
  local destination="$1" count="$2" label="$3"
  build67_redis "$destination" "$count" "$label" <<'PY'
import json, os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, prefix
pod, tenant, destination, count, label = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
key = prefix(pod, tenant, "stress-src", "egress")
started = time.time()
for sequence in range(count):
    frame = build("Message", "stress-src", destination, {"sequence": sequence, "fault": label}, pod=pod, tenant=tenant)
    r.rpush(key, json.dumps(frame, separators=(",", ":")))
print(f"PUSH label={label} count={count} elapsed_s={time.time()-started:.6f}")
PY
}

build67_metrics() {
  build67_redis "$1" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import prefix
pod, tenant, destination = sys.argv[1:4]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
info = r.info("memory")
print(f"METRIC destination={destination} ingress={r.llen(prefix(pod, tenant, destination, 'ingress'))} egress={r.llen(prefix(pod, tenant, 'stress-src', 'egress'))} used_memory={info['used_memory']} delivering={r.hget(prefix(pod, tenant, resource='delivering'), destination)!r}")
PY
}

run_build67() {
  local count="${BUILD67_COUNT:-500}" deadline before after elapsed processes holder marker
  echo "build67 container=$CONTAINER work=$WORK count=$count"
  build67_state clear && build67_state seed || { echo "BUILD67 SETUP RED: initial state failed"; return 3; }
  tmux_switch="$(dx pgrep -f 'python3 -m flock.switch' | head -1 | tr -d '\r')"

  echo "== A control: consumable destination stays clear =="
  build67_push stress-clean 25 A-control
  wait_for_queues 120 || { echo "A CONTROL RED: clean destination did not drain"; return 3; }
  build67_metrics stress-clean
  echo "A CONTROL CLEAN"

  echo "== A injected: enrolled permitted paused destination accumulates =="
  dx redis-cli SET "pod:$POD:tenant:$TENANT:agent:stress-paused:paused" 1 >/dev/null
  before="$(build67_redis <<'PY'
import os, sys, redis
r=redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")); print(r.info("memory")["used_memory"])
PY
)"
  start="$(date +%s.%N)"; build67_push stress-paused "$count" A-injected
  deadline=$((SECONDS + 300))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(dx redis-cli LLEN "pod:$POD:tenant:$TENANT:agent:stress-src:egress" | tr -d '\r')" = 0 ] && break
    sleep 1
  done
  end="$(date +%s.%N)"; elapsed="$(python3 -c "print(float('$end')-float('$start'))")"
  after="$(build67_redis <<'PY'
import os, sys, redis
r=redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")); print(r.info("memory")["used_memory"])
PY
)"
  build67_metrics stress-paused
  python3 - "$count" "$before" "$after" "$elapsed" <<'PY'
import sys
n, before, after, elapsed = int(sys.argv[1]), *map(float, sys.argv[2:])
growth=max(0, after-before); per=growth/n if n else 0; rate=n/elapsed if elapsed else 0
ceiling=int((1024**3)/per) if per else 0
seconds=ceiling/rate if rate else 0
print(f"A_CEILING threshold_bytes={1024**3} measured_growth_bytes={growth:.0f} bytes_per_frame={per:.3f} forwarded_per_s={rate:.3f} frames={ceiling} seconds_at_measured_rate={seconds:.1f}")
PY
  [ "$(dx redis-cli LLEN "pod:$POD:tenant:$TENANT:agent:stress-paused:ingress" | tr -d '\r')" = "$count" ] || { echo "A GATE RED: injected queue did not retain every frame"; return 3; }
  echo "A INJECTED DETECTED"

  echo "== B control: absent tag leaves no waiting ports =="
  build67_state clear && build67_state seed || { echo "BUILD67 SETUP RED: B state failed"; return 3; }
  build67_push stress-clean 10 B-control; wait_for_queues 120 || return 3
  processes="$(dx sh -c "ps -eo args= | grep -c '[f]lock.port stress-clean' || true" | tr -d '\r')"
  echo "B_CONTROL waiting_processes=$processes"; [ "$processes" = 0 ] || return 3

  echo "== B injected: kill real run_port holder after HSETNX =="
  holder="$(dx sh -c "python3 -c 'import time; import flock.port.deliver as d; d.deliver_one=lambda *a,**k: time.sleep(600); d.run_port(\"stress-clean\", pod=\"$POD\", tenant=\"$TENANT\")' >/dev/null 2>&1 & echo \$!" | tr -d '\r')"
  deadline=$((SECONDS + 30))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ -n "$(dx redis-cli HGET "pod:$POD:tenant:$TENANT:delivering" stress-clean | tr -d '\r')" ] && break
    sleep 0.05
  done
  dx kill -9 "$holder" >/dev/null
  build67_push stress-clean 25 B-injected
  sleep 5
  processes="$(dx sh -c "ps -eo args= | grep -c '[f]lock.port stress-clean' || true" | tr -d '\r')"
  build67_metrics stress-clean
  echo "B_INJECTED waiting_processes=$processes kicks=25"
  [ "$processes" -ge 20 ] || { echo "B GATE RED: stale tag did not accumulate waiting ports"; return 3; }
  echo "B INJECTED DETECTED"

  echo "== C control: kicked api/control queues clear =="
  dx pkill -9 -f 'flock.port stress-clean' >/dev/null 2>&1 || true
  build67_state clear && build67_state seed || { echo "BUILD67 SETUP RED: C state failed"; return 3; }
  build67_push stress-api 1 C-api-control; build67_push host 1 C-control-control
  wait_for_queues 120 || { echo "C CONTROL RED: kicked participant did not clear"; return 3; }
  echo "C CONTROL CLEAN"

  echo "== C injected: un-kicked api/control frames strand and watchdog omits both =="
  build67_redis <<'PY'
import json, os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, prefix
from flock.watchdog.service import Watchdog
pod, tenant=sys.argv[1:3]; r=redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
for dst in ("stress-api", "host"):
    frame=build("Message", "stress-src", dst, {"fault":"C-injected"}, pod=pod, tenant=tenant)
    r.rpush(prefix(pod, tenant, dst, "ingress"), json.dumps(frame, separators=(",", ":")))
w=Watchdog(r,pod=pod,tenant=tenant,session_name=tenant)
observed=w._agents()
print(f"C_INJECTED api_depth={r.llen(prefix(pod,tenant,'stress-api','ingress'))} control_depth={r.llen(prefix(pod,tenant,'host','ingress'))} watchdog_agents={observed}")
assert "stress-api" not in observed and "host" not in observed
PY
  echo "C INJECTED DETECTED"

  echo "== D control: same-source FIFO trio all produce custody =="
  build67_state clear && build67_state seed || { echo "BUILD67 SETUP RED: D control state failed"; return 3; }
  : >"$WORK/d-control.tsv"
  build67_redis >"$WORK/d-control.tsv" <<'PY'
import json, os, sys, time
sys.path.insert(0,"/app/src"); import redis
from flock.bus import build,prefix
pod,tenant=sys.argv[1:3]; r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0"))
for seq in range(3):
 f=build("Message","stress-src","stress-clean",{"sequence":seq,"fault":"D-control"},pod=pod,tenant=tenant); print(f"{seq}\t{f['stream_id']}\tstress-src\tstress-clean\t{time.time()}",flush=True); r.rpush(prefix(pod,tenant,"stress-src","egress"),json.dumps(f,separators=(",",":")))
PY
  wait_for_queues 120 || return 3
  : >"$WORK/injections.tsv"
  reconcile "$WORK/d-control.tsv" d-control | tee "$WORK/d-control.result" || return 3
  echo "D CONTROL CLEAN"

  echo "== D injected: kill after BLPOP before first emit, FIFO bracket =="
  build67_state clear && build67_state seed || { echo "BUILD67 SETUP RED: D injected state failed"; return 3; }
  : >"$WORK/d-injected.tsv"; : >"$WORK/injections.tsv"
  # Deliver the FIFO predecessor normally.
  build67_redis >"$WORK/d-injected.tsv" <<'PY'
import json, os, sys, time
sys.path.insert(0,"/app/src"); import redis
from flock.bus import build,prefix
pod,tenant=sys.argv[1:3]; r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0")); key=prefix(pod,tenant,"stress-src","egress")
f=build("Message","stress-src","stress-clean",{"sequence":0,"fault":"D-injected"},pod=pod,tenant=tenant); print(f"0\t{f['stream_id']}\tstress-src\tstress-clean\t{time.time()}",flush=True); r.rpush(key,json.dumps(f,separators=(",",":")))
while r.llen(key): time.sleep(.01)
time.sleep(1)
PY
  # Stop production before the target exists, then enqueue target and successor.
  dx kill -STOP "$tmux_switch"
  build67_redis >>"$WORK/d-injected.tsv" <<'PY'
import json, os, sys, time
sys.path.insert(0,"/app/src"); import redis
from flock.bus import build,prefix
pod,tenant=sys.argv[1:3]; r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0")); key=prefix(pod,tenant,"stress-src","egress")
for seq in (1,2):
 f=build("Message","stress-src","stress-clean",{"sequence":seq,"fault":"D-injected"},pod=pod,tenant=tenant); print(f"{seq}\t{f['stream_id']}\tstress-src\tstress-clean\t{time.time()}",flush=True); r.rpush(key,json.dumps(f,separators=(",",":")))
PY
  # Make a controlled switch expose the exact BLPOP-before-emit gap.
  marker="pod:$POD:tenant:$TENANT:build67:blpop-gap"; dx redis-cli DEL "$marker" >/dev/null
  test_switch="$(dx sh -c "env POD='$POD' TENANT='$TENANT' REDIS_URL='$REDIS_URL' python3 -c 'import os,time,redis; from flock.switch.service import Switch; r=redis.Redis.from_url(os.environ[\"REDIS_URL\"]); real=r.blpop; r.blpop=lambda *a,**k: (lambda x:(r.set(\"$marker\",1),time.sleep(600),x)[2])(real(*a,**k)); Switch(r,pod=os.environ[\"POD\"],tenant=os.environ[\"TENANT\"]).step()' >>/proc/1/fd/1 2>&1 & echo \$!" | tr -d '\r')"
  deadline=$((SECONDS + 30)); while [ "$SECONDS" -lt "$deadline" ]; do [ "$(dx redis-cli GET "$marker" | tr -d '\r')" = 1 ] && break; sleep .05; done
  start="$(date +%s.%N)"; dx kill -9 "$test_switch"; end="$(date +%s.%N)"; test_switch=""
  printf '%s\t%s\tswitch-kill\tblpop-before-emit\n' "$start" "$end" >"$WORK/injections.tsv"
  dx kill -CONT "$tmux_switch"; tmux_switch=""
  wait_for_queues 120 || return 3
  reconcile "$WORK/d-injected.tsv" d-injected | tee "$WORK/d-injected.result"
  rc=${PIPESTATUS[0]}; [ "$rc" = 0 ] || { echo "D GATE RED: injected silent loss was not FIFO-attributed rc=$rc"; return 3; }
  grep -q 'lost_attributed=1 lost_unexplained=0' "$WORK/d-injected.result" || { echo "D GATE RED: expected one attributed loss"; return 3; }
  echo "D INJECTED DETECTED"

  echo "WATCHDOG_OBSERVATION A=per-participant ingress depth and growth rate, correlated with successful kicks and absence of pop/open progress"
  echo "WATCHDOG_OBSERVATION B=delivering owner identity/lease age plus ingress depth and count of kicks losing ownership; depth alone cannot distinguish this wedge"
  echo "WATCHDOG_OBSERVATION C=roster-wide ingress depth for every port_type, not Watchdog._agents tmux subset"
  echo "WATCHDOG_OBSERVATION D=durable custody sequence around each source FIFO: sent/preceding-popped/following-popped plus switch-process generation; no frame-local record exists"
}

if [ "${BUILD67:-0}" = "1" ]; then
  run_build67
  exit $?
fi

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
        print(f"{seq}\t{frame['stream_id']}\tcons-{i}\t{dst}\t{time.time()}", flush=True)
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
