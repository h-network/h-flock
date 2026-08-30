#!/usr/bin/env bash
set -uo pipefail

service_name="$1"
shift
restart_delay_seconds="${SERVICE_RESTART_DELAY_SECONDS:-1}"
[[ "$restart_delay_seconds" =~ ^[0-9]+([.][0-9]+)?$ ]] || restart_delay_seconds=1
child_pid=""
stopping=0

emit_event() {
  printf '%s\n' "$1"
  if [ -n "${FLOCK_EVENT_LOG_PATH:-}" ]; then
    { printf '%s\n' "$1" >> "$FLOCK_EVENT_LOG_PATH"; } 2>/dev/null || true
  fi
}

stop_child() {
  stopping=1
  [ -z "$child_pid" ] || kill "$child_pid" 2>/dev/null || true
}
trap stop_child INT TERM

while [ "$stopping" -eq 0 ]; do
  "$@" &
  child_pid=$!
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"service_started\",\"service\":\"$service_name\",\"pid\":$child_pid}"

  wait "$child_pid"
  exit_code=$?
  if [ "$stopping" -ne 0 ]; then
    # A signal interrupts bash's wait before the child necessarily finishes.
    # Reap it after forwarding the signal so the supervisor cannot orphan it.
    wait "$child_pid" 2>/dev/null || true
  fi
  child_pid=""
  [ "$stopping" -eq 0 ] || break

  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"service_restart_scheduled\",\"service\":\"$service_name\",\"exit\":$exit_code,\"delay_s\":$restart_delay_seconds}"
  sleep "$restart_delay_seconds" &
  child_pid=$!
  wait "$child_pid" 2>/dev/null || true
  child_pid=""
done

exit 0
