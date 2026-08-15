#!/usr/bin/env bash
# switch-bench — THE default benchmark for forwarding. Run this one.
#
#   CONTAINER=… POD=acme TENANT=… STATIONS=100 ROUNDS=20 bash switch-bench.sh
#
# It answers two questions and nothing else:
#   1. how fast does the switch forward
#   2. is every step logged
#
# ⚠ **It is NOT a delivery test.** `accept.sh` and `base-run-tmux.sh` cover
# whether a message reaches an agent. Do not quote these figures as delivery
# throughput — we spent two days doing exactly that with api-client numbers.
#
# ## Why it is built the way it is
#
# **Synthetic port.** A real delivery is ~98% process spawn — 659–911 ms in
# situ against 7–13 ms of switch work. Measuring forwarding through it is
# measuring `fork`+`exec`+interpreter with a switch attached. `bench-port.py`
# is long-lived and pops in a loop.
#
# ⚠ **The kick shim is load-bearing.** The switch kicks `flock.port` on EVERY
# forward, unconditionally, for any roster member. Without a shim those real
# ports spawn anyway, find an empty queue because `bench-port` already popped,
# and exit — burning the exact CPU this benchmark exists to exclude. The shim is
# a `flock.port` earlier on PATH that exits immediately, so a kick costs
# fork/exec (~2 ms) instead of an interpreter start. **No production code is
# changed; the shim exists only inside the bench container.**
#
# **Capture then analyse.** Nothing reads the log while it is being written.
# `fabric-bench` ran `docker logs | grep -c` every second — megabytes re-read
# 200+ times per run, on the same CPU as delivery, heavier as the run got
# busier. It baked its own load into everything it reported.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
STATIONS="${STATIONS:-100}"
ROUNDS="${ROUNDS:-20}"
OUT="${OUT:-/tmp/switch-bench-$(date +%s).log}"
SEND_LOG=$(mktemp)
trap 'rm -f "$SEND_LOG"' EXIT

dx() { docker exec "$CONTAINER" "$@"; }
T=$(dx printenv API_TOKEN)
A="http://127.0.0.1:8080"
EXPECT=$(( STATIONS * ROUNDS ))

echo "switch-bench: $STATIONS x $ROUNDS = $EXPECT envelopes -> $OUT"

echo "== kick shim =="
dx bash -lc 'mkdir -p /tmp/shim && printf "#!/bin/sh\nexit 0\n" > /tmp/shim/flock.port && chmod +x /tmp/shim/flock.port'
dx bash -lc 'ls -l /tmp/shim/flock.port' >/dev/null && echo "  installed (kick costs fork+exec, not an interpreter)"

echo "== enrol =="
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"bench-$i\",\"port_type\":\"api\"}}" \
    "$A/agents/host/envelopes"
done
sleep 5
echo "  roster: $(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:roster" | tr -d '\r')"

echo "== synthetic port =="
# ⚠ The image contains /app/src only — `container/scenarios/` is NOT baked in.
# Copy the port in rather than assuming a path that does not exist. (Caught on
# the first run of this script, before it could report anything.)
docker cp "$(dirname "$0")/bench-port.py" "$CONTAINER:/tmp/bench-port.py" >/dev/null
dx bash -lc "PATH=/tmp/shim:\$PATH nohup python3 /tmp/bench-port.py \
  --pod '$POD' --tenant '$TENANT' --prefix bench- --count $STATIONS \
  >>/proc/1/fd/1 2>&1 & echo started" >/dev/null 2>&1
sleep 3
dx pgrep -f bench-port.py >/dev/null 2>&1 \
  && echo "  synthetic port running" \
  || { echo "  ⚠ synthetic port DID NOT START — aborting rather than measuring a real-port run" >&2; exit 3; }

echo "== send =="
docker exec -i "$CONTAINER" python3 - <<PY >"$SEND_LOG"
import os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus.doors import send
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
n, rounds = $STATIONS, $ROUNDS
t0 = time.time()
for rnd in range(rounds):
    for i in range(1, n + 1):
        send(r, pod="$POD", tenant="$TENANT", source=f"bench-{i}",
             destination=f"bench-{(i % n) + 1}", kind="Message",
             payload={"text": f"r{rnd}"})
print(f"  submitted {n*rounds} in {time.time()-t0:.1f}s")
PY
grep '^  submitted ' "$SEND_LOG"

echo "== drain (LLEN, constant cost per poll) =="
for _ in $(seq 1 1800); do
  DEPTH=$(dx python3 -c "
import os,sys; sys.path.insert(0,'/app/src')
import redis
r=redis.Redis.from_url(os.environ.get('REDIS_URL','redis://127.0.0.1:6379/0'))
print(sum(r.llen(k) for k in r.scan_iter(match='pod:$POD:tenant:$TENANT:agent:*:ingress')) +
      sum(r.llen(k) for k in r.scan_iter(match='pod:$POD:tenant:$TENANT:agent:*:egress')))" 2>/dev/null | tr -d '\r')
  [ "${DEPTH:-1}" = "0" ] && break
  sleep 2
done
sleep 3

docker logs "$CONTAINER" > "$OUT" 2>&1
grep '^{' "$SEND_LOG" >> "$OUT"
echo "  captured $(wc -l < "$OUT") lines"

echo
echo "== analysis =="
python3 "$(dirname "$0")/analyse-run.py" "$OUT" --expect "$EXPECT" --source-prefix bench-

echo
echo "== teardown =="
dx pkill -f bench-port.py >/dev/null 2>&1 || true
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"bench-$i\"}}" "$A/agents/host/envelopes"
done
echo "  retired $STATIONS stations"
