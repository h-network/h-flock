#!/usr/bin/env bash
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

C="${CONTAINER:-}"
POD="${POD:-acme}"
TENANT="${TENANT:-}"
AGENT="retained-probe"
CLOCK="retained-clock"
RUN="retained-$(date +%s)-$$"
SYNC_MARKER="refresh-$(date +%s)-$$"
EXPECTED_MATCHES="${RETAINED_EXPECT_MATCHES:-1}"
[ -n "$C" ] && [ -n "$TENANT" ] || incomplete bus-retained-egress missing_container_or_tenant
docker inspect "$C" >/dev/null 2>&1 || incomplete bus-retained-egress container_not_found

PREFIX="pod:$POD:tenant:$TENANT"
ROSTER="$PREFIX:roster"
EGRESS="$PREFIX:agent:$AGENT:egress"
INBOX="$PREFIX:agent:api:inbox"
dx() { docker exec "$C" "$@"; }
cleanup() {
  dx redis-cli HDEL "$ROSTER" "$AGENT" "$CLOCK" >/dev/null 2>&1 || true
  for participant in "$AGENT" "$CLOCK"; do
    for resource in ingress egress inbox dead tasks.todo tasks.doing tasks.hold tasks.done; do
      dx redis-cli DEL "$PREFIX:agent:$participant:$resource" >/dev/null 2>&1 || true
    done
  done
}
trap cleanup EXIT

dx redis-cli HSET "$ROSTER" "$AGENT" api "$CLOCK" api >/dev/null || incomplete bus-retained-egress roster_seed_failed
dx redis-cli HDEL "$ROSTER" "$AGENT" >/dev/null || incomplete bus-retained-egress retirement_failed

# A switch may already be blocked on a roster snapshot that still contains the
# retired source.  Make it consume a frame from an enrolled clock source first;
# observing that delivery proves its next BLPOP is built from the new roster.
dx python3 - "$POD" "$TENANT" "$CLOCK" "$SYNC_MARKER" <<'PY' >/dev/null || incomplete bus-retained-egress sync_enqueue_failed
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, encode, prefix
pod, tenant, source, marker = sys.argv[1:]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
frame = build("Message", source, "api", {"marker": marker}, pod=pod, tenant=tenant)
r.rpush(prefix(pod, tenant, source, "egress"), encode(frame))
PY
for _ in $(seq 1 200); do
  sync_matches="$(dx redis-cli XRANGE "$INBOX" - + | grep -c "$SYNC_MARKER" || true)"
  [ "$sync_matches" = 1 ] && break
  sleep 0.1
done
[ "${sync_matches:-0}" = 1 ] || incomplete bus-retained-egress roster_refresh_unobserved

dx python3 - "$POD" "$TENANT" "$AGENT" "$RUN" <<'PY' >/dev/null || incomplete bus-retained-egress v4_enqueue_failed
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, encode, prefix
pod, tenant, source, marker = sys.argv[1:]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
frame = build("Message", source, "api", {"marker": marker}, pod=pod, tenant=tenant)
r.rpush(prefix(pod, tenant, source, "egress"), encode(frame))
PY

sleep 2
absent_egress="$(dx redis-cli LLEN "$EGRESS" | tr -d '\r')"
absent_matches="$(dx redis-cli XRANGE "$INBOX" - + | grep -c "$RUN" || true)"
expect "retired source egress retained" 1 "$absent_egress"
expect "retired source not delivered" 0 "$absent_matches"

dx redis-cli HSET "$ROSTER" "$AGENT" api >/dev/null || incomplete bus-retained-egress reenrol_failed
for _ in $(seq 1 200); do
  [ "$(dx redis-cli LLEN "$EGRESS" | tr -d '\r')" = 0 ] && break
  sleep 0.1
done
sleep 1
after_egress="$(dx redis-cli LLEN "$EGRESS" | tr -d '\r')"
after_matches="$(dx redis-cli XRANGE "$INBOX" - + | grep -c "$RUN" || true)"
expect "re-enrolled source egress drained" 0 "$after_egress"
expect "retained frame delivered exactly once" "$EXPECTED_MATCHES" "$after_matches"
finish bus-retained-egress
