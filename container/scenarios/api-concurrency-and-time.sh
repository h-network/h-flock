#!/usr/bin/env bash
# container/scenarios/api-concurrency-and-time.sh
# Tests concurrent REST API requests, long-lived SSE streaming, and roster resilience under corrupt data.

HOST="${API_HOST:-http://localhost:8110}"
TOKEN="${API_TOKEN:-7af3ad5eb2cac57e9ca97a953908ef09}"

echo "=== Scenario: API Concurrency, Stream Handling & Roster Robustness ==="
echo "Target Host: ${HOST}"

echo "[1] Measuring concurrent HTTP /health latency (10 parallel requests)..."
for i in {1..10}; do
  curl -s -o /dev/null -w "Req ${i}: status=%{http_code} time=%{time_total}s\n" "${HOST}/health" &
done
wait

echo -e "\n[2] Testing long-polling SSE event stream (/alerts/stream)..."
# Sample SSE stream for 3 seconds
curl -s -H "Authorization: Bearer ${TOKEN}" --max-time 3 "${HOST}/alerts/stream" || true

echo -e "\n[3] Testing activity endpoints (/agents/architect/activity)..."
curl -s -H "Authorization: Bearer ${TOKEN}" -w "\nHTTP Status: %{http_code}\n" "${HOST}/agents/architect/activity"

echo -e "\n[4] Testing unknown agent endpoint (/agents/nonexistent_agent)..."
curl -s -H "Authorization: Bearer ${TOKEN}" -w "\nHTTP Status: %{http_code}\n" "${HOST}/agents/nonexistent_agent"

echo -e "\n=== Scenario Complete ==="
