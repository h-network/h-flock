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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
    -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"bench-$i\",\"port_type\":\"api\"}}" \
    "$A/agents/host/envelopes"
done
sleep 5
ENROLLED=$(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:roster" | tr -d '\r')
echo "  roster now holds $ENROLLED participants"

BEFORE_MEM=$(dx redis-cli INFO memory | awk -F: '/^used_memory:/{printf "%d", $2/1024}')
EXPECT=$(( STATIONS * ROUNDS ))
LOG_SINCE="$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)"
SEND_LOG=$(mktemp)
RUN_LOG="${RUN_LOG:-$(pwd)/fabric-bench.docker.log}"
trap 'rm -f "$SEND_LOG"' EXIT
BEFORE_INBOX=$(dx python3 - "$POD" "$TENANT" "$STATIONS" <<'PY'
import os, sys, redis
pod, tenant, stations = sys.argv[1], sys.argv[2], int(sys.argv[3])
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
pipe = r.pipeline(transaction=False)
for i in range(1, stations + 1):
    pipe.xlen(f"pod:{pod}:tenant:{tenant}:agent:bench-{i}:inbox")
print(sum(pipe.execute()))
PY
)

echo
echo "== sending =="
START=$(date +%s%N)
# ⚠ `-i` is load-bearing: without it docker exec attaches no stdin, python reads
# an empty program, and the run reports zero sends with no error anywhere.
docker exec -i "$CONTAINER" python3 - <<PY >"$SEND_LOG"
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
        send(r, pod=pod, tenant=tenant, source=f"bench-{i}", destination=dst,
             kind="Message", payload={"text": f"r{rnd}"})
        sent += 1
dt = time.time() - t0
print(f"  submitted {sent} packets in {dt:.1f}s  =  {sent/dt:,.0f}/s at the sender")
PY
grep '^  submitted ' "$SEND_LOG"
SUBMIT_NS=$(( $(date +%s%N) - START ))

echo
echo "== draining =="
# ⚠ Submission is not delivery. Wait for the switch and the adapters to catch
# up, and report how long that took — that number is the fabric's, not the
# sender's.
# One long-lived process polls only delivery state. Each poll is one Redis
# pipeline round trip containing STATIONS constant-time XLEN operations; it
# never reads the custody log or starts another host process.
if ! dx python3 - "$POD" "$TENANT" "$STATIONS" "$BEFORE_INBOX" "$EXPECT" <<'PY'
import os, sys, time, redis
pod, tenant = sys.argv[1], sys.argv[2]
stations, before, expected = map(int, sys.argv[3:])
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
deadline = time.monotonic() + expected / 2 + 120
while time.monotonic() < deadline:
    pipe = r.pipeline(transaction=False)
    for i in range(1, stations + 1):
        pipe.xlen(f"pod:{pod}:tenant:{tenant}:agent:bench-{i}:inbox")
    delivered = sum(pipe.execute()) - before
    if delivered >= expected:
        print(f"  completion poll: inbox streams hold {delivered}/{expected} new entries")
        raise SystemExit(0)
    time.sleep(1)
print(f"completion poll timed out before {expected} deliveries", file=sys.stderr)
raise SystemExit(1)
PY
then
  echo "fabric-bench: completion poll failed" >&2
  exit 1
fi
TOTAL_NS=$(( $(date +%s%N) - START ))
AFTER_MEM=$(dx redis-cli INFO memory | awk -F: '/^used_memory:/{printf "%d", $2/1024}')
# Capture one immutable artifact after completion. `send` ran through
# docker-exec rather than PID 1, so append its records to the container snapshot
# to keep sent-to-popped and end-to-end paths joinable during later analysis.
docker logs --since "$LOG_SINCE" "$CONTAINER" >"$RUN_LOG" 2>&1
grep '^{' "$SEND_LOG" >>"$RUN_LOG"

echo "  expected $EXPECT, delivered $EXPECT"
awk -v d="$EXPECT" -v ns="$TOTAL_NS" 'BEGIN{ if (ns>0) printf "  end to end: %.1fs  =  %.2f delivered/s\n", ns/1e9, d/(ns/1e9) }'
echo "  redis memory: ${BEFORE_MEM} KiB -> ${AFTER_MEM} KiB"

echo "  captured log: $RUN_LOG"

echo
echo "== record integrity =="
python3 /tmp/fromlog.py <"$RUN_LOG" 2>/dev/null | head -8 || \
  echo "  (fromlog.py not present on this host — copy it to /tmp to get the full audit)"

echo
echo "== teardown =="
for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"bench-$i\"}}" "$A/agents/host/envelopes"
done
echo "  retired $STATIONS stations"
echo
echo "Analyse the static artifact separately:"
echo "  python3 $SCRIPT_DIR/analyse-run.py $RUN_LOG --expected $EXPECT --source-prefix bench-"
