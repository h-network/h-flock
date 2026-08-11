#!/usr/bin/env bash
set -euo pipefail

C="${CONTAINER:-h-flock-bus-lab-tenant-1}"
POD="${POD:-acme}"
TENANT="${TENANT:-bus-lab}"
N="${COUNT:-50}"
PREFIX="pod:$POD:tenant:$TENANT"
ROSTER="$PREFIX:roster"
PROBES=(bus-probe-1 bus-probe-2 bus-probe-3 bus-probe-4 bus-probe-5)
RUN="broadcast-$(date +%s)-$$"

dx() { docker exec "$C" "$@"; }
cleanup() {
  for probe in "${PROBES[@]}"; do
    dx redis-cli HDEL "$ROSTER" "$probe" >/dev/null 2>&1 || true
    for resource in ingress egress inbox dead tasks.todo tasks.doing tasks.hold tasks.done; do
      dx redis-cli DEL "$PREFIX:agent:$probe:$resource" >/dev/null 2>&1 || true
    done
  done
}
trap cleanup EXIT

echo "container=$C tenant=$TENANT run=$RUN broadcasts=$N"
for probe in "${PROBES[@]}"; do
  dx redis-cli HSET "$ROSTER" "$probe" api >/dev/null
  dx redis-cli DEL "$PREFIX:agent:$probe:inbox" >/dev/null
done
echo "roster=$(dx redis-cli HKEYS "$ROSTER" | sort | tr '\n' ',')"

for sequence in $(seq 1 "$N"); do
  identifier=$(printf '%016x%016x' "$$" "$sequence")
  envelope="{\"v\":1,\"kind\":\"Message\",\"stream_id\":\"$identifier\",\"correlation_id\":\"$identifier\",\"ts\":\"2026-08-11T00:00:00.000Z\",\"producer\":\"architect\",\"recipient\":\"all\",\"payload\":{\"text\":\"$RUN-$sequence\"}}"
  dx redis-cli RPUSH "$PREFIX:agent:architect:egress" "$envelope" >/dev/null
done
echo "queued=$N source_egress=$(dx redis-cli LLEN "$PREFIX:agent:architect:egress")"

for _ in $(seq 1 100); do
  minimum="$N"
  for probe in "${PROBES[@]}"; do
    count=$(dx redis-cli XLEN "$PREFIX:agent:$probe:inbox")
    [ "$count" -lt "$minimum" ] && minimum="$count"
  done
  [ "$minimum" -ge "$N" ] && break
  sleep 0.1
done

for probe in "${PROBES[@]}"; do
  echo "$probe inbox=$(dx redis-cli XLEN "$PREFIX:agent:$probe:inbox") matching=$(dx redis-cli XRANGE "$PREFIX:agent:$probe:inbox" - + | grep -c "$RUN" || true)"
done
echo "source_egress_after=$(dx redis-cli LLEN "$PREFIX:agent:architect:egress")"
echo "payload_log_records=$(docker logs "$C" 2>&1 | grep -c "$RUN" || true)"
