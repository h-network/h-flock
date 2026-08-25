#!/usr/bin/env bash
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

TENANT="${TENANT:-tmux-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
PORT="${API_PORT:-8120}"
AGENT="${AGENT:-race-hire}"
TOKEN="$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)"
[ -n "$TOKEN" ] || incomplete tmux-concurrent-hire missing_api_token
AUTH="Authorization: Bearer $TOKEN"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
TMUX=(docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)
ROSTER="pod:acme:tenant:${TENANT}:roster"
LAUNCH="pod:acme:tenant:${TENANT}:agent:${AGENT}:launch"

for cli in claude codex; do
  curl -sS -o "$TMP/$cli" -w '%{http_code}' -H "$AUTH" -H 'Content-Type: application/json' \
    -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"$AGENT\",\"cli\":\"$cli\"}}" \
    "http://127.0.0.1:${PORT}/agents/host/envelopes" >"$TMP/$cli.status" || true
done
status_a="$(cat "$TMP/claude.status" 2>/dev/null || echo 000)"
status_b="$(cat "$TMP/codex.status" 2>/dev/null || echo 000)"
expect "concurrent hire claude request" 202 "$status_a"
expect "concurrent hire codex request" 202 "$status_b"

sleep 8
desired="$(docker exec "$C" redis-cli --raw HGET "$ROSTER" "$AGENT" 2>/dev/null || true)"
launch="$(docker exec "$C" redis-cli --raw GET "$LAUNCH" 2>/dev/null || true)"
[ "$desired" = "$launch" ] || { echo "  ✗ desired CLI and launch differ" >&2; _FAILED=$((_FAILED+1)); }
[ "$launch" = claude ] || [ "$launch" = codex ] || { echo "  ✗ winning CLI is invalid" >&2; _FAILED=$((_FAILED+1)); }
windows="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}|#{pane_current_command}' 2>/dev/null | awk -F'|' -v a="$AGENT" '$1==a')"
count="$(printf '%s\n' "$windows" | sed '/^$/d' | wc -l | tr -d ' ')"
expect "one window after concurrent hire" 1 "$count"
case "$windows" in *"|$launch"*) echo "  ✓ window command matches winning CLI";; *) echo "  ✗ window command does not match winning CLI" >&2; _FAILED=$((_FAILED+1));; esac

curl -sS -o "$TMP/rehire" -w '%{http_code}' -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StartAgent\",\"payload\":{\"agent\":\"$AGENT\",\"cli\":\"$launch\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes" >"$TMP/rehire.status" || true
expect "unchanged rehire request" 202 "$(cat "$TMP/rehire.status")"
sleep 2
windows_after="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}' 2>/dev/null | awk -v a="$AGENT" '$0==a')"
expect "one window after unchanged rehire" 1 "$(printf '%s\n' "$windows_after" | sed '/^$/d' | wc -l | tr -d ' ')"

curl -sS -o /dev/null -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"$AGENT\"}}" \
  "http://127.0.0.1:${PORT}/agents/host/envelopes" || true
finish tmux-concurrent-hire
