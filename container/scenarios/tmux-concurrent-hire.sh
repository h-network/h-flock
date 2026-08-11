#!/usr/bin/env bash
set -uo pipefail

TENANT="${TENANT:-tmux-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
PORT="${API_PORT:-8120}"
AGENT="${AGENT:-race-hire}"
TOKEN="$(docker exec "$C" printenv API_TOKEN)"
AUTH="Authorization: Bearer $TOKEN"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "scenario=concurrent-hire tenant=$TENANT container=$C agent=$AGENT"
curl -sS -w $'\nhttp_status=%{http_code}\n' -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"$AGENT\",\"cli\":\"claude\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes" >"$TMP/claude" &
p1=$!
curl -sS -w $'\nhttp_status=%{http_code}\n' -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"$AGENT\",\"cli\":\"codex\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes" >"$TMP/codex" &
p2=$!
wait "$p1" "$p2"
echo "claude request:"; sed -n '1,5p' "$TMP/claude"
echo "codex request:"; sed -n '1,5p' "$TMP/codex"

sleep 8
echo "desired state:"
docker exec "$C" redis-cli --raw HGET "pod:acme:tenant:${TENANT}:roster" "$AGENT"
docker exec "$C" redis-cli --raw GET "pod:acme:tenant:${TENANT}:agent:${AGENT}:launch"
echo "matching windows:"
docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
  tmux list-windows -t "$TENANT" -F '#{window_name}|#{pane_current_command}' | grep -F "${AGENT}|" || true
echo "all exact-name count:"
docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
  tmux list-windows -t "$TENANT" -F '#{window_name}' | grep -Fxc "$AGENT" || true

echo "action=unchanged-rehire using-current-launch"
launch="$(docker exec "$C" redis-cli --raw GET "pod:acme:tenant:${TENANT}:agent:${AGENT}:launch")"
curl -sS -w $'\nhttp_status=%{http_code}\n' -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"$AGENT\",\"cli\":\"$launch\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes"
sleep 2
echo "matching windows after unchanged rehire:"
docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
  tmux list-windows -t "$TENANT" -F '#{window_name}|#{pane_pid}|#{pane_current_command}' | grep -F "${AGENT}|" || true

curl -sS -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"$AGENT\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes" >/dev/null
