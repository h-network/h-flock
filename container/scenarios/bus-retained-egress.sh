#!/usr/bin/env bash
set -euo pipefail

C="${CONTAINER:-h-flock-bus-lab-tenant-1}"
POD="${POD:-acme}"
TENANT="${TENANT:-bus-lab}"
PREFIX="pod:$POD:tenant:$TENANT"
ROSTER="$PREFIX:roster"
AGENT="retained-probe"
RUN="retained-$(date +%s)-$$"
IDENTIFIER=$(printf '%032x' "$$")
EGRESS="$PREFIX:agent:$AGENT:egress"
INBOX="$PREFIX:agent:api:inbox"

dx() { docker exec "$C" "$@"; }
cleanup() {
  dx redis-cli HDEL "$ROSTER" "$AGENT" >/dev/null 2>&1 || true
  for resource in ingress egress inbox dead tasks.todo tasks.doing tasks.hold tasks.done; do
    dx redis-cli DEL "$PREFIX:agent:$AGENT:$resource" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

echo "container=$C tenant=$TENANT run=$RUN"
dx redis-cli HSET "$ROSTER" "$AGENT" api >/dev/null
dx redis-cli HDEL "$ROSTER" "$AGENT" >/dev/null
echo "after_retire roster_value=[$(dx redis-cli HGET "$ROSTER" "$AGENT")] egress=$(dx redis-cli LLEN "$EGRESS")"

envelope="{\"v\":1,\"kind\":\"Message\",\"stream_id\":\"$IDENTIFIER\",\"correlation_id\":\"$IDENTIFIER\",\"ts\":\"2026-08-11T00:00:00.000Z\",\"source\":\"$AGENT\",\"destination\":\"api\",\"payload\":{\"text\":\"$RUN\"}}"
dx redis-cli RPUSH "$EGRESS" "$envelope" >/dev/null
sleep 2
echo "while_absent egress=$(dx redis-cli LLEN "$EGRESS") inbox_matches=$(dx redis-cli XRANGE "$INBOX" - + | grep -c "$RUN" || true)"

dx redis-cli HSET "$ROSTER" "$AGENT" api >/dev/null
for _ in $(seq 1 50); do
  [ "$(dx redis-cli LLEN "$EGRESS")" = 0 ] && break
  sleep 0.1
done
sleep 1
echo "after_reenrol roster_value=[$(dx redis-cli HGET "$ROSTER" "$AGENT")] egress=$(dx redis-cli LLEN "$EGRESS") inbox_matches=$(dx redis-cli XRANGE "$INBOX" - + | grep -c "$RUN" || true)"
echo "matching_logs:"
docker logs "$C" 2>&1 | grep "$IDENTIFIER" || true
