#!/usr/bin/env bash
# container/scenarios/api-auth-and-limits.sh
# Tests REST API token auth, payload size bounds, malformed 'as' validation, and board providers.

set -uo pipefail

TENANT="${TENANT:-api-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
HOST="${API_HOST:-http://localhost:8110}"
TOKEN="${API_TOKEN:-$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)}"
if [ -z "${TOKEN:-}" ]; then
  echo "Error: API_TOKEN is empty. Set API_TOKEN or ensure container '$C' is running." >&2
  exit 1
fi

echo "=== Scenario: API Auth, Payload Limits & Error Handling ==="
echo "Target Host: ${HOST}"

echo "[1] Testing GET /health without auth..."
BODY=$(curl -s "${HOST}/health")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${HOST}/health")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n[2] Testing GET /agents without token (unauthorized)..."
BODY=$(curl -s "${HOST}/agents")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${HOST}/agents")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n[3] Testing GET /agents with invalid token..."
BODY=$(curl -s -H "Authorization: Bearer wrong_token" "${HOST}/agents")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer wrong_token" "${HOST}/agents")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n[4] Testing GET /agents with valid token..."
BODY=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${HOST}/agents")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" "${HOST}/agents")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n[5] Testing POST /agents/architect/envelopes with malformed 'as' dict payload..."
BODY=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{"as": {"invalid": "dict"}, "text": "hello"}' "${HOST}/agents/architect/envelopes")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{"as": {"invalid": "dict"}, "text": "hello"}' "${HOST}/agents/architect/envelopes")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n[6] Testing POST /agents/architect/envelopes with oversized (>1MB) payload..."
python3 -c 'import json, sys; sys.stdout.write(json.dumps({"text": "x" * (1024*1024 + 100)}))' > /tmp/large_payload.json
BODY=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" --data-binary @/tmp/large_payload.json "${HOST}/agents/architect/envelopes")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" --data-binary @/tmp/large_payload.json "${HOST}/agents/architect/envelopes")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"
rm -f /tmp/large_payload.json

echo -e "\n[7] Testing GET /board..."
BODY=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${HOST}/board")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" "${HOST}/board")
echo "Body: ${BODY}"
echo "HTTP Status: ${STATUS}"

echo -e "\n=== Scenario Complete ==="
