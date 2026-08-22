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
PAYLOAD_BYTES="${PAYLOAD_BYTES:-default}"
OUT="${OUT:-/tmp/switch-bench-$(date +%s).log}"

dx() { docker exec "$CONTAINER" "$@"; }
T=$(dx printenv API_TOKEN)
A="http://127.0.0.1:8080"
EXPECT=$(( STATIONS * ROUNDS ))
# bench-port writes exactly the received and opened custody stages. Keep the
# meaning beside the count: adding another synthetic-port stage must change
# this declaration or the exact writer census will refuse the run loudly.
BENCH_PORT_STAGES=2

echo "switch-bench: $STATIONS x $ROUNDS = $EXPECT envelopes, payload=$PAYLOAD_BYTES -> $OUT"

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
ROSTER=$(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:roster" | tr -d '\r')
echo "  roster: $ROSTER"

# ⚠ ENROLMENT GOES THROUGH THE REST API DOOR, WHICH IS OPT-IN SINCE BUILD 76.
# Against a tenant with API_ENABLED=0 every curl above posts into a closed door,
# returns nothing, and this script used to print "roster: 4" against STATIONS=100
# and carry on — submitting 2000 envelopes addressed to stations that do not
# exist, which the switch correctly refuses to forward, then hanging in the drain
# loop forever waiting for deliveries that can never happen. Measured 2026-08-22.
# The contradiction was already in its own output; nothing read it.
if [ "${ROSTER:-0}" -lt "$STATIONS" ]; then
  echo "switch-bench: enrolled $ROSTER of $STATIONS stations." >&2
  echo "  The REST API door is how stations enrol and it is opt-in. Check" >&2
  echo "  API_ENABLED=1 in container/.env, then recreate the tenant." >&2
  exit 1
fi

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
docker cp "$(dirname "$0")/bench-send.py" "$CONTAINER:/tmp/bench-send.py" >/dev/null
PAYLOAD_ARG=""
[ "$PAYLOAD_BYTES" = default ] || PAYLOAD_ARG="--payload-bytes $PAYLOAD_BYTES"
dx sh -c "python3 /tmp/bench-send.py --pod '$POD' --tenant '$TENANT' \
  --prefix bench- --count '$STATIONS' --rounds '$ROUNDS' $PAYLOAD_ARG >>/proc/1/fd/1"

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
echo "  captured $(wc -l < "$OUT") lines"

echo
echo "== analysis =="
python3 "$(dirname "$0")/analyse-run.py" "$OUT" --expect "$EXPECT" --source-prefix bench- \
  --expect-writer "bench-send=$EXPECT" \
  --expect-writer "bench-port=$((EXPECT * BENCH_PORT_STAGES))"
ANALYSIS_STATUS=$?

echo
echo "== teardown =="
dx pkill -f bench-port.py >/dev/null 2>&1 || true
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"bench-$i\"}}" "$A/agents/host/envelopes"
done
echo "  retired $STATIONS stations"
exit "$ANALYSIS_STATUS"
