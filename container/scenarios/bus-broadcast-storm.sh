#!/usr/bin/env bash
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

C="${CONTAINER:-}"
POD="${POD:-acme}"
TENANT="${TENANT:-}"
N="${COUNT:-50}"
RUN="broadcast-$(date +%s)-$$"
EXPECTED_COUNT="${BROADCAST_EXPECT_COUNT:-$N}"
PROBES=(bus-probe-1 bus-probe-2 bus-probe-3 bus-probe-4 bus-probe-5)
[ -n "$C" ] && [ -n "$TENANT" ] || incomplete bus-broadcast-storm missing_container_or_tenant
docker inspect "$C" >/dev/null 2>&1 || incomplete bus-broadcast-storm container_not_found

PREFIX="pod:$POD:tenant:$TENANT"
ROSTER="$PREFIX:roster"
SOURCE_EGRESS="$PREFIX:agent:architect:egress"
dx() { docker exec "$C" "$@"; }
dxi() { docker exec -i "$C" "$@"; }
cleanup() {
  for probe in "${PROBES[@]}"; do
    dx redis-cli HDEL "$ROSTER" "$probe" >/dev/null 2>&1 || true
    for resource in ingress egress inbox dead tasks.todo tasks.doing tasks.hold tasks.done; do
      dx redis-cli DEL "$PREFIX:agent:$probe:$resource" >/dev/null 2>&1 || true
    done
  done
}
trap cleanup EXIT

for probe in "${PROBES[@]}"; do
  dx redis-cli HSET "$ROSTER" "$probe" api >/dev/null || incomplete bus-broadcast-storm roster_seed_failed
  dx redis-cli DEL "$PREFIX:agent:$probe:inbox" >/dev/null
done

names="${PROBES[*]}"
dxi python3 - "$POD" "$TENANT" "$N" "$RUN" <<'PY' >/dev/null || incomplete bus-broadcast-storm v4_send_failed
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus.doors import send
pod, tenant, count, marker = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
for sequence in range(1, count + 1):
    send(r, pod=pod, tenant=tenant, source="architect", destination="all",
         kind="Message", payload={"marker": marker, "sequence": sequence}, module="broadcast-storm")
PY

for _ in $(seq 1 300); do
  ready=1
  for probe in "${PROBES[@]}"; do
    matches="$(dx redis-cli XRANGE "$PREFIX:agent:$probe:inbox" - + | grep -c "$RUN" || true)"
    [ "$matches" -ge "$N" ] || ready=0
  done
  [ "$ready" = 1 ] && break
  sleep 0.1
done

for probe in "${PROBES[@]}"; do
  matches="$(dx redis-cli XRANGE "$PREFIX:agent:$probe:inbox" - + | grep -c "$RUN" || true)"
  expect "$probe receives every broadcast exactly once" "$EXPECTED_COUNT" "$matches"
done
source_depth="$(dx redis-cli LLEN "$SOURCE_EGRESS" | tr -d '\r')"
expect "broadcast source egress drained" 0 "$source_depth"
finish bus-broadcast-storm
