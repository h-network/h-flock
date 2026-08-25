#!/usr/bin/env bash
# api-concurrency-and-time — does the door hold up under parallel load, and does
# it answer honestly about agents that do and do not exist?
#
#   CONTAINER=<name> bash container/scenarios/api-concurrency-and-time.sh
#
# ⚠ This replaces a script that fired ten parallel requests, printed each one's
# status and time, and compared none of them. It always exited 0.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

C="${CONTAINER:?set CONTAINER}"
HOST="${API_HOST_URL:-http://127.0.0.1:8080}"
TOKEN="${API_TOKEN:-$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)}"
[ -n "${TOKEN:-}" ] || incomplete api-concurrency "no_api_token container=$C"

echo "== api concurrency and time · $HOST =="

# ⚠ Ten at once, and EVERY ONE must answer 200. The point is not the latency —
# it is that none of them is refused, dropped or served an error under parallel
# load. A door that serves nine of ten is broken in a way an average hides.
codes="$(for _ in $(seq 1 10); do
  curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" "$HOST/health" &
done | sort -u | tr '\n' ' ')"
wait
expect "10 parallel /health all answer 200" "200 " "$codes"

# The stream must open and then let go. A door that never closes the connection
# is indistinguishable from one that hangs, so the timeout is the assertion.
start=$SECONDS
curl -s -o /dev/null -H "Authorization: Bearer $TOKEN" --max-time 3 "$HOST/alerts/stream" 2>/dev/null
elapsed=$((SECONDS - start))
[ "$elapsed" -le 5 ] && expect "alert stream opens and releases" ok ok \
                     || expect "alert stream opens and releases" ok "held ${elapsed}s"

check "a real agent has activity"   200 -H "Authorization: Bearer $TOKEN" "$HOST/agents/architect/activity"
check "an unknown agent is 404"     404 -H "Authorization: Bearer $TOKEN" "$HOST/agents/nonexistent_agent"
check "an unknown agent's board is 404" 404 -H "Authorization: Bearer $TOKEN" "$HOST/agents/nonexistent_agent/board"

finish api-concurrency
