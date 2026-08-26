#!/usr/bin/env bash
# One ordinary agent-to-agent Message through the real tmux opener. `opened` is
# load-bearing: doors.py emits it only after paste_text returns cleanly; every
# opener failure dead-letters instead.
# `--break-delivery` corrupts routing before paste_text. It proves these
# assertions are wired, but does not prove sensitivity to a paste_text failure.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

TENANT="${TENANT:-}"
[ -n "$TENANT" ] || incomplete tmux-paste-delivery tenant_required
CONTAINER="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
POD="${POD:-acme}"
SOURCE="${SOURCE:-architect}"
DESTINATION="${DESTINATION:-sme-2}"
DEADLINE_SECONDS="${PASTE_DELIVERY_DEADLINE_SECONDS:-15}"
BREAK_DELIVERY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --break-delivery) BREAK_DELIVERY=1; shift ;;
    *) incomplete tmux-paste-delivery unknown_argument ;;
  esac
done

TMUX=(docker exec "$CONTAINER" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)
ROSTER="pod:${POD}:tenant:${TENANT}:roster"
for agent in "$SOURCE" "$DESTINATION"; do
  count="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}' 2>/dev/null | awk -v a="$agent" '$0==a' | wc -l | tr -d ' ')"
  [ "$count" = 1 ] || incomplete tmux-paste-delivery "${agent}_window_count_${count}"
  port_type="$(docker exec "$CONTAINER" redis-cli --raw HGET "$ROSTER" "$agent" 2>/dev/null || true)"
  [ "$port_type" = tmux ] || incomplete tmux-paste-delivery "${agent}_not_tmux"
done

restore_needed=0
resume_needed=0
tmuxhost_pid=""
restore_negative_control() {
  local failed=0
  if [ "$restore_needed" = 1 ]; then
    restore_needed=0
    if ! docker exec "$CONTAINER" redis-cli HSET "$ROSTER" "$DESTINATION" tmux >/dev/null 2>&1; then
      echo "ERROR: failed to restore $DESTINATION roster port type; tenant is damaged" >&2
      failed=1
    fi
  fi
  if [ "$resume_needed" = 1 ]; then
    resume_needed=0
    if ! docker exec "$CONTAINER" kill -CONT "$tmuxhost_pid" >/dev/null 2>&1; then
      echo "ERROR: failed to SIGCONT tmuxhost pid=$tmuxhost_pid; tenant may remain wedged" >&2
      failed=1
    fi
  fi
  [ "$failed" = 0 ] || exit 125
}
trap restore_negative_control EXIT
if [ "$BREAK_DELIVERY" = 1 ]; then
  # A controlled invalid port route makes the same ordinary Message dead-letter
  # before paste_text. The green and red runs therefore exercise one assertion,
  # not separate fixture-only judges.
  mapfile -t tmuxhost_pids < <(docker exec "$CONTAINER" pgrep -f '[p]ython3 -m flock.tmuxhost' 2>/dev/null || true)
  [ "${#tmuxhost_pids[@]}" -eq 1 ] || incomplete tmux-paste-delivery tmuxhost_pid_count_${#tmuxhost_pids[@]}
  tmuxhost_pid="${tmuxhost_pids[0]}"
  resume_needed=1
  docker exec "$CONTAINER" kill -STOP "$tmuxhost_pid" >/dev/null 2>&1 || incomplete tmux-paste-delivery tmuxhost_stop_failed
  stop_deadline=$(( $(date +%s) + 5 )); tmuxhost_state=""
  while [ "$(date +%s)" -lt "$stop_deadline" ]; do
    tmuxhost_state="$(docker exec "$CONTAINER" awk '/^State:/{print $2}' "/proc/$tmuxhost_pid/status" 2>/dev/null || true)"
    [ "$tmuxhost_state" = T ] && break
    sleep 0.1
  done
  [ "$tmuxhost_state" = T ] || incomplete tmux-paste-delivery tmuxhost_not_stopped
  restore_needed=1
  docker exec "$CONTAINER" redis-cli HSET "$ROSTER" "$DESTINATION" broken-paste-control >/dev/null 2>&1 \
    || incomplete tmux-paste-delivery negative_control_setup_failed
fi

send_output="$(docker exec -e POD="$POD" -e TENANT="$TENANT" -e SOURCE="$SOURCE" \
  -e DESTINATION="$DESTINATION" "$CONTAINER" python3 -c '
import contextlib, os, redis
from flock.bus.doors import send
r=redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
with open("/proc/1/fd/1", "w") as custody, contextlib.redirect_stdout(custody):
    sid=send(r, pod=os.environ["POD"], tenant=os.environ["TENANT"],
             source=os.environ["SOURCE"], destination=os.environ["DESTINATION"],
             kind="Message", payload={"text":"tmux paste delivery control"},
             module="tmux-paste-delivery")
print("STREAM_ID=" + sid)
' 2>/dev/null || true)"
stream_id="$(printf '%s\n' "$send_output" | sed -n 's/^STREAM_ID=//p' | tail -1)"
[ -n "$stream_id" ] || incomplete tmux-paste-delivery send_failed

custody_counts() {
  docker logs "$CONTAINER" 2>/dev/null | python3 -c '
import json, sys
sid, target=sys.argv[1:3]; matched=sent=opened=dead=parse_failures=0
for line in sys.stdin:
    if not line.lstrip().startswith("{"): continue
    try: row=json.loads(line)
    except Exception:
        parse_failures += 1
        continue
    if row.get("stream_id") != sid or row.get("destination") != target: continue
    matched += 1
    sent += row.get("event") == "sent"
    opened += row.get("event") == "opened"
    dead += row.get("event") == "dead_lettered"
print(matched, sent, opened, dead, parse_failures)
' "$stream_id" "$DESTINATION"
}

deadline=$(( $(date +%s) + DEADLINE_SECONDS ))
matched=0; sent=0; opened=0; dead=0; parse_failures=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  read -r matched sent opened dead parse_failures <<<"$(custody_counts)"
  [ "$parse_failures" = 0 ] || incomplete tmux-paste-delivery malformed_custody_json
  [ "$opened" -ge 1 ] || [ "$dead" -ge 1 ] && break
  sleep 0.2
done
restore_negative_control
[ "$matched" -gt 0 ] || incomplete tmux-paste-delivery no_custody_for_stream
expect "ordinary message entered custody" 1 "$sent"
expect "ordinary message reached opened after real pane paste" 1 "$opened"
expect "ordinary message was not dead-lettered" 0 "$dead"
finish tmux-paste-delivery
