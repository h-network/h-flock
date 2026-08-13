#!/usr/bin/env bash
# fabric-bench — measure the bus, not the models.
#
#   CONTAINER=h-flock-bench-tenant-1 POD=acme TENANT=bench \
#   STATIONS=100 ROUNDS=100 bash container/scenarios/fabric-bench.sh
#
# ⚠ **The four-agent run measured Nemotron, not the fabric.** Both GPUs sat at
# 99% while the KV cache used 1% and Redis used 1.6 MB — the bus was idle
# throughout, so quoting 34 envelopes/minute as a transport figure was measuring
# inference and calling it throughput.
#
# This uses **api clients** as stations: enrolled names with mailboxes and no
# window, so nothing runs a CLI and nothing costs a token. The path exercised is
# the real one — send → egress → switch pop → forward → ingress → adapter kick →
# mailbox — minus only the terminal paste.
#
# ⚠ Prints measurements, not verdicts. Record integrity is the number that
# matters; throughput on one container is a floor, not a limit.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
STATIONS="${STATIONS:-20}"
ROUNDS="${ROUNDS:-50}"

dx() { docker exec "$CONTAINER" "$@"; }
T=$(dx printenv API_TOKEN)
A="http://127.0.0.1:8080"

echo "fabric-bench: $STATIONS stations x $ROUNDS rounds on $CONTAINER"
echo

echo "== enrolling stations =="
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"bench-$i\",\"vab\":\"api\"}}" \
    "$A/agents/host/envelopes"
done
sleep 5
ENROLLED=$(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:roster" | tr -d '\r')
echo "  roster now holds $ENROLLED participants"

BEFORE_OPENED=$(docker logs "$CONTAINER" 2>&1 | grep -c '"event":"opened"')
BEFORE_MEM=$(dx redis-cli INFO memory | awk -F: '/^used_memory:/{printf "%d", $2/1024}')

echo
echo "== sending =="
START=$(date +%s%N)
dx python3 - <<PY
import os, sys, time, json
sys.path.insert(0, "/app/src")
import redis
from flock.bus.doors import send
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
pod, tenant, n, rounds = "$POD", "$TENANT", $STATIONS, $ROUNDS
t0 = time.time()
sent = 0
for rnd in range(rounds):
    for i in range(1, n + 1):
        dst = f"bench-{(i % n) + 1}"
        send(r, pod=pod, tenant=tenant, producer=f"bench-{i}", recipient=dst,
             kind="Message", payload={"text": f"r{rnd}"})
        sent += 1
dt = time.time() - t0
print(f"  submitted {sent} packets in {dt:.1f}s  =  {sent/dt:,.0f}/s at the sender")
PY
SUBMIT_NS=$(( $(date +%s%N) - START ))

echo
echo "== draining =="
# ⚠ Submission is not delivery. Wait for the switch and the adapters to catch
# up, and report how long that took — that number is the fabric's, not the
# sender's.
EXPECT=$(( STATIONS * ROUNDS ))
for _ in $(seq 1 240); do
  NOW=$(docker logs "$CONTAINER" 2>&1 | grep -c '"event":"opened"')
  [ $(( NOW - BEFORE_OPENED )) -ge "$EXPECT" ] && break
  sleep 1
done
TOTAL_NS=$(( $(date +%s%N) - START ))
AFTER_OPENED=$(docker logs "$CONTAINER" 2>&1 | grep -c '"event":"opened"')
AFTER_MEM=$(dx redis-cli INFO memory | awk -F: '/^used_memory:/{printf "%d", $2/1024}')

DELIVERED=$(( AFTER_OPENED - BEFORE_OPENED ))
echo "  expected $EXPECT, delivered $DELIVERED"
awk -v d="$DELIVERED" -v ns="$TOTAL_NS" 'BEGIN{ if (ns>0) printf "  end to end: %.1fs  =  %.0f delivered/s\n", ns/1e9, d/(ns/1e9) }'
echo "  redis memory: ${BEFORE_MEM} KiB -> ${AFTER_MEM} KiB"

echo
echo "== record integrity =="
docker logs "$CONTAINER" 2>&1 | python3 /tmp/fromlog.py 2>/dev/null | head -8 || \
  echo "  (fromlog.py not present on this host — copy it to /tmp to get the full audit)"

echo
echo "== teardown =="
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"bench-$i\"}}" "$A/agents/host/envelopes"
done
echo "  retired $STATIONS stations"
