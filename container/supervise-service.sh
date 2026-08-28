#!/usr/bin/env bash
# Restart one core service without coupling its lifetime to any peer service.
set -uo pipefail

name="$1"
shift
delay="${SERVICE_RESTART_SECONDS:-1}"
[[ "$delay" =~ ^[0-9]+([.][0-9]+)?$ ]] || delay=1
child_pid=""
stopping=0

jlog() {
  printf '%s\n' "$1"
  if [ -n "${FLOCK_CUSTODY_FILE:-}" ]; then
    { printf '%s\n' "$1" >> "$FLOCK_CUSTODY_FILE"; } 2>/dev/null || true
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
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"service_started\",\"service\":\"$name\",\"pid\":$child_pid}"

  wait "$child_pid"
  code=$?
  if [ "$stopping" -ne 0 ]; then
    # A signal interrupts bash's wait before the child necessarily finishes.
    # Reap it after forwarding the signal so the supervisor cannot orphan it.
    wait "$child_pid" 2>/dev/null || true
  fi
  child_pid=""
  [ "$stopping" -eq 0 ] || break

  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"service_restart_scheduled\",\"service\":\"$name\",\"exit\":$code,\"delay_s\":$delay}"
  sleep "$delay" &
  child_pid=$!
  wait "$child_pid" 2>/dev/null || true
  child_pid=""
done

exit 0
