#!/usr/bin/env bash
# api-auth-and-limits — does the REST door refuse what it should?
#
#   CONTAINER=<name> bash container/scenarios/api-auth-and-limits.sh
#
# ⚠ This script used to make seven calls and `echo "HTTP Status: $STATUS"` for
# each, comparing none of them. It always exited 0, so it could not fail and was
# not a test. Every check below now states the status it EXPECTS and the run
# fails if the door answers differently.
#
# Exit: 0 all checks passed · 1+ that many failed · 100 could not run.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

C="${CONTAINER:?set CONTAINER}"
HOST="${API_HOST_URL:-http://127.0.0.1:8080}"
TOKEN="${API_TOKEN:-$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)}"
[ -n "${TOKEN:-}" ] || incomplete api-auth "no_api_token container=$C"

echo "== api auth and limits · $HOST =="

check "health is open"            200 "$HOST/health"
check "no token is refused"       401 "$HOST/agents"
check "bad token is refused"      401 -H "Authorization: Bearer wrong_token" "$HOST/agents"
check "good token is accepted"    200 -H "Authorization: Bearer $TOKEN" "$HOST/agents"
check "board is readable"         200 -H "Authorization: Bearer $TOKEN" "$HOST/board"
check "unknown agent is 404"      404 -H "Authorization: Bearer $TOKEN" "$HOST/agents/nobody-here/board"

check "malformed 'as' is refused" 422 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"as": {"invalid": "dict"}, "text": "hello"}' "$HOST/agents/architect/envelopes"

# ⚠ The bound is the point: a door that accepts an unbounded body is a door that
# can be used to fill a disk.
big="$(mktemp)"; python3 -c 'import json,sys; sys.stdout.write(json.dumps({"text": "x" * (1024*1024 + 100)}))' > "$big"
check "oversized body is refused" 422 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary "@$big" "$HOST/agents/architect/envelopes"
rm -f "$big"

finish api-auth
