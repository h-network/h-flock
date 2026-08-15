#!/usr/bin/env bash
# base-run — produce a log, and nothing else.
#
#   CONTAINER=… POD=acme TENANT=… STATIONS=100 ROUNDS=20 bash base-run.sh OUT.log
#
# ⚠ **This does not measure anything.** It runs a workload, waits for the queues
# to empty, and captures the container log once. Every figure comes afterwards
# from `analyse-run.py` over that file.
#
# ⚠ **Why not `fabric-bench`:** its completion check runs
# `docker logs | grep -c` every second — megabytes re-read 200+ times per run, on
# the same CPU as delivery, getting heavier as the run gets busier. It bakes its
# own load into whatever it reports. Here completion is `LLEN` on the queues:
# one cheap Redis call per poll, constant cost, no log reads at all.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
STATIONS="${STATIONS:-100}"
ROUNDS="${ROUNDS:-20}"
OUT="${1:?usage: base-run.sh OUTPUT.log}"

dx() { docker exec "$CONTAINER" "$@"; }
T=$(dx printenv API_TOKEN)
A="http://127.0.0.1:8080"

echo "base-run: $STATIONS x $ROUNDS on $CONTAINER -> $OUT"

for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"bench-$i\",\"port_type\":\"api\"}}" \
    "$A/agents/host/envelopes"
done
sleep 5
echo "  enrolled: $(dx redis-cli HLEN "pod:$POD:tenant:$TENANT:roster" | tr -d '\r')"

docker cp "$(dirname "$0")/bench-send.py" "$CONTAINER:/tmp/bench-send.py" >/dev/null
dx sh -c "python3 /tmp/bench-send.py --pod '$POD' --tenant '$TENANT' \
  --prefix bench- --count '$STATIONS' --rounds '$ROUNDS' >>/proc/1/fd/1"

# Completion by queue depth: one Redis call per poll, constant cost.
echo "  draining"
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
echo "  captured $(wc -l < "$OUT") lines to $OUT"

for i in $(seq 1 "$STATIONS"); do
  dx curl -s -o /dev/null -H "Authorization: Bearer $T" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"bench-$i\"}}" "$A/agents/host/envelopes"
done
echo "  retired $STATIONS stations"
