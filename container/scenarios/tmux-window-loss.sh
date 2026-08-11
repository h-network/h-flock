#!/usr/bin/env bash
set -uo pipefail

TENANT="${TENANT:-tmux-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
PORT="${API_PORT:-8120}"
AGENT="${AGENT:-observer}"
TOKEN="$(docker exec "$C" printenv API_TOKEN)"
AUTH="Authorization: Bearer $TOKEN"

echo "scenario=window-loss tenant=$TENANT container=$C agent=$AGENT"
echo "before windows:"
docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
  tmux list-windows -t "$TENANT" -F '#{window_name}'

for run in 1 2; do
  echo "run=$run action=kill-window-then-immediate-message"
  docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
    tmux kill-window -t "${TENANT}:${AGENT}"
  response="$(curl -sS -w $'\nhttp_status=%{http_code}' -H "$AUTH" \
    -H 'Content-Type: application/json' -d "{\"text\":\"window-loss-$run\"}" \
    "http://127.0.0.1:${PORT}/agents/${AGENT}/envelopes")"
  printf '%s\n' "$response"
  sleep 2
  echo "dead-letter tail after run=$run:"
  docker exec "$C" redis-cli --raw LRANGE \
    "pod:acme:tenant:${TENANT}:agent:${AGENT}:dead" -2 -1
  echo "delivery log tail after run=$run:"
  docker logs --since 5s "$C" 2>&1 | grep -E "${AGENT}|window_missing|list-windows|paste" | tail -20 || true
  sleep 5
  echo "windows after reconciliation run=$run:"
  docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
    tmux list-windows -t "$TENANT" -F '#{window_name}'
done
