#!/usr/bin/env bash
set -euo pipefail

C="${CONTAINER:-h-flock-bus-lab-tenant-1}"
POD="${POD:-acme}"
TENANT="${TENANT:-bus-lab}"
PREFIX="pod:$POD:tenant:$TENANT"
RUN="restart-$(date +%s)-$$"
SENTINEL="$PREFIX:scenario:$RUN"
QUEUE="$PREFIX:agent:restart-probe:ingress"

dx() { docker exec "$C" "$@"; }
cleanup() {
  dx redis-cli DEL "$SENTINEL" >/dev/null 2>&1 || true
  dx redis-cli LREM "$QUEUE" 0 "$RUN" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "container=$C tenant=$TENANT run=$RUN"
dx redis-cli SET "$SENTINEL" "$RUN" >/dev/null
dx redis-cli RPUSH "$QUEUE" "$RUN" >/dev/null
echo "before_restart sentinel=[$(dx redis-cli GET "$SENTINEL")] queued=$(dx redis-cli LLEN "$QUEUE")"

docker restart "$C"
for _ in $(seq 1 60); do
  status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$C")
  [ "$status" = healthy ] && break
  sleep 1
done
echo "after_restart health=$(docker inspect -f '{{.State.Health.Status}}' "$C") sentinel=[$(dx redis-cli GET "$SENTINEL")] queue_contains=$(dx redis-cli LRANGE "$QUEUE" 0 -1 | grep -c "$RUN" || true) queue_depth=$(dx redis-cli LLEN "$QUEUE")"
echo "recent_startup:"
docker logs --since 2m "$C" 2>&1 | grep -E 'redis|windows_ready|module.*(switch|container).*event.*(started|error)' | tail -20 || true
