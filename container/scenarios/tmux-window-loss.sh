#!/usr/bin/env bash
# Proves observable at-most-once loss plus terminal recovery, NOT delivery:
# a message sent while its window is absent is dead-lettered window_missing,
# never opened, and reconciliation restores exactly one fresh pane.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

TENANT="${TENANT:-}"
[ -n "$TENANT" ] || incomplete tmux-window-loss tenant_required
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
PORT="${API_PORT:-8120}"
AGENT="${AGENT:-observer}"
POD="${POD:-acme}"
ROSTER_POLL_SECONDS="${ROSTER_POLL_SECONDS:-5}"
DEADLINE_SECONDS="${WINDOW_LOSS_DEADLINE_SECONDS:-20}"
[ "$DEADLINE_SECONDS" -ge 15 ] || DEADLINE_SECONDS=15
[ "$DEADLINE_SECONDS" -ge $((ROSTER_POLL_SECONDS * 2)) ] || DEADLINE_SECONDS=$((ROSTER_POLL_SECONDS * 2))
TMUX=(docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)
ROSTER="pod:${POD}:tenant:${TENANT}:roster"
LAUNCH="pod:${POD}:tenant:${TENANT}:agent:${AGENT}:launch"

TOKEN="$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)"
[ -n "$TOKEN" ] || incomplete tmux-window-loss missing_api_token
tmuxhost_pid="$(docker exec "$C" pgrep -fo 'python3 -m flock.tmuxhost' 2>/dev/null || true)"
[ -n "$tmuxhost_pid" ] || incomplete tmux-window-loss missing_tmuxhost_pid

mapfile -t before < <("${TMUX[@]}" list-windows -t "$TENANT" \
  -F '#{window_name}|#{window_id}|#{pane_pid}' 2>/dev/null | awk -F'|' -v a="$AGENT" '$1==a')
[ "${#before[@]}" -eq 1 ] || incomplete tmux-window-loss initial_window_count_${#before[@]}
IFS='|' read -r old_name old_window_id old_pane_pid <<<"${before[0]}"
port_type="$(docker exec "$C" redis-cli --raw HGET "$ROSTER" "$AGENT" 2>/dev/null || true)"
launch_before="$(docker exec "$C" redis-cli --raw GET "$LAUNCH" 2>/dev/null || true)"
[ -n "$port_type" ] && [ -n "$launch_before" ] || incomplete tmux-window-loss missing_desired_state
[ "$port_type" = tmux ] || incomplete tmux-window-loss target_not_tmux

resumed=0
resume_tmuxhost() {
  if [ "$resumed" = 0 ]; then
    resumed=1
    if ! docker exec "$C" kill -CONT "$tmuxhost_pid" >/dev/null 2>&1; then
      echo "ERROR: failed to SIGCONT tmuxhost pid=$tmuxhost_pid; tenant may remain wedged" >&2
      exit 125
    fi
  fi
}
docker exec "$C" kill -STOP "$tmuxhost_pid" >/dev/null 2>&1 || incomplete tmux-window-loss tmuxhost_stop_failed
trap resume_tmuxhost EXIT
"${TMUX[@]}" kill-window -t "$old_window_id" >/dev/null 2>&1 || incomplete tmux-window-loss window_kill_failed

absent_count="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}' 2>/dev/null | awk -v a="$AGENT" '$0==a' | wc -l | tr -d ' ')"
expect "target absent before send" 0 "$absent_count"
if docker exec "$C" kill -0 "$old_pane_pid" >/dev/null 2>&1; then echo "  ✗ old pane pid survived window kill" >&2; _FAILED=$((_FAILED+1)); else echo "  ✓ old pane pid is gone before send"; fi

response="$(curl -sS -w $'\n%{http_code}' -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"text":"window-loss-observable-at-most-once"}' \
  "http://127.0.0.1:${PORT}/agents/${AGENT}/envelopes" 2>/dev/null || true)"
status="${response##*$'\n'}"
body="${response%$'\n'*}"
expect "message accepted during reconcile gap" 202 "${status:-000}"
stream_id="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("stream_id", ""))' <<<"$body" 2>/dev/null || true)"
[ -n "$stream_id" ] || incomplete tmux-window-loss missing_stream_id

custody_counts() {
  docker logs "$C" 2>/dev/null | python3 -c '
import json, sys
sid, target=sys.argv[1:3]; dead=opened=0
for line in sys.stdin:
    try: row=json.loads(line)
    except Exception: continue
    if row.get("stream_id") != sid or row.get("destination") != target: continue
    dead += row.get("event") == "dead_lettered" and row.get("reason") == "window_missing"
    opened += row.get("event") == "opened"
print(dead, opened)
' "$stream_id" "$AGENT"
}

deadline=$(( $(date +%s) + DEADLINE_SECONDS ))
dead=0; opened=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  read -r dead opened <<<"$(custody_counts)"
  [ "$dead" -ge 1 ] && break
  sleep 0.2
done
expect "one window_missing dead letter" 1 "$dead"
expect "stream never opened during gap" 0 "$opened"

resume_tmuxhost
deadline=$(( $(date +%s) + DEADLINE_SECONDS ))
recovered=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  recovered="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}|#{pane_pid}' 2>/dev/null | awk -F'|' -v a="$AGENT" '$1==a')"
  recovered_count="$(printf '%s\n' "$recovered" | sed '/^$/d' | wc -l | tr -d ' ')"
  [ "$recovered_count" = 1 ] && break
  sleep 0.2
done
expect "exactly one recovered window" 1 "${recovered_count:-0}"
new_pane_pid="${recovered#*|}"
# window_id is deliberately not compared: tmux may reuse @0 when rebuilding a
# session. A new live pane PID, with the old PID gone, is the recovery proof.
[ -n "$new_pane_pid" ] && docker exec "$C" kill -0 "$new_pane_pid" >/dev/null 2>&1 || { echo "  ✗ recovered pane pid is not live" >&2; _FAILED=$((_FAILED+1)); }
[ "$new_pane_pid" != "$old_pane_pid" ] || { echo "  ✗ recovered pane reused old pane pid" >&2; _FAILED=$((_FAILED+1)); }
if docker exec "$C" kill -0 "$old_pane_pid" >/dev/null 2>&1; then echo "  ✗ old pane pid is still live" >&2; _FAILED=$((_FAILED+1)); else echo "  ✓ old pane pid is gone"; fi
expect "roster desired state unchanged" "$port_type" "$(docker exec "$C" redis-cli --raw HGET "$ROSTER" "$AGENT" 2>/dev/null || true)"
expect "launch desired state unchanged" "$launch_before" "$(docker exec "$C" redis-cli --raw GET "$LAUNCH" 2>/dev/null || true)"
read -r dead opened <<<"$(custody_counts)"
expect "dead letter remains singular after recovery" 1 "$dead"
expect "recovery did not retry or deliver stream" 0 "$opened"
finish tmux-window-loss
