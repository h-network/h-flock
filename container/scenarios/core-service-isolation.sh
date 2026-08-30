#!/usr/bin/env bash
# Kill each independently supervised service and prove only its child PID changes.
# Then kill Redis and prove that the critical exception restarts the container.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

TENANT="${TENANT:-}"
[ -n "$TENANT" ] || incomplete core-service-isolation tenant_required
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
docker inspect "$C" >/dev/null 2>&1 || incomplete core-service-isolation container_missing

services=(tmux_reconciler switch watchdog api session)
patterns=(
  '[p]ython3 -m flock.tmux_reconciler'
  '[p]ython3 -m flock.switch'
  '[p]ython3 -m flock.watchdog'
  '[p]ython3 -m flock.api'
  '[p]ython3 -m flock.session'
)

pid_for() {
  docker exec "$C" pgrep -f "$1" 2>/dev/null | head -1
}

container_id="$(docker inspect -f '{{.Id}}' "$C")"
tmux_server_before="$(docker exec "$C" pgrep -f 'tmux.*server' 2>/dev/null | head -1 || true)"
redis_before="$(pid_for '[r]edis-server.*6379' || true)"
[ -n "$redis_before" ] || incomplete core-service-isolation redis_missing

for i in "${!services[@]}"; do
  service="${services[$i]}"
  old_pid="$(pid_for "${patterns[$i]}" || true)"
  # The api is deliberately optional. Every other core service must be present.
  if [ -z "$old_pid" ] && [ "$service" = api ]; then
    echo "  - api disabled; skipped"
    continue
  fi
  [ -n "$old_pid" ] || incomplete core-service-isolation "${service}_missing"

  declare -a peer_before=()
  for j in "${!services[@]}"; do
    peer_before[$j]="$(pid_for "${patterns[$j]}" || true)"
  done

  docker exec "$C" kill -TERM "$old_pid" >/dev/null 2>&1 \
    || incomplete core-service-isolation "${service}_kill_failed"
  deadline=$((SECONDS + 15))
  new_pid=""
  until [ "$SECONDS" -ge "$deadline" ]; do
    new_pid="$(pid_for "${patterns[$i]}" || true)"
    [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ] && break
    sleep 0.2
  done
  if [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ]; then
    echo "  ✓ $service restarted pid=$old_pid→$new_pid"
  else
    echo "  ✗ $service did not restart" >&2
    _FAILED=$((_FAILED+1))
  fi

  expect "$service kept container" "$container_id" "$(docker inspect -f '{{.Id}}' "$C" 2>/dev/null || true)"
  expect "$service kept redis" "$redis_before" "$(pid_for '[r]edis-server.*6379' || true)"
  for j in "${!services[@]}"; do
    [ "$j" -eq "$i" ] && continue
    [ -z "${peer_before[$j]}" ] && continue
    expect "$service kept ${services[$j]}" "${peer_before[$j]}" "$(pid_for "${patterns[$j]}" || true)"
  done
done

if [ -n "$tmux_server_before" ]; then
  expect "tmux server survived all service restarts" "$tmux_server_before" \
    "$(docker exec "$C" pgrep -f 'tmux.*server' 2>/dev/null | head -1 || true)"
fi

# Redis is intentionally not isolated: only a full container restart provides
# the boot-time transport purge before the switch reconnects.
started_before="$(docker inspect -f '{{.State.StartedAt}}' "$C")"
docker exec "$C" kill -TERM "$redis_before" >/dev/null 2>&1 \
  || incomplete core-service-isolation redis_kill_failed
deadline=$((SECONDS + 30))
started_after="$started_before"
redis_after=""
until [ "$SECONDS" -ge "$deadline" ]; do
  started_after="$(docker inspect -f '{{.State.StartedAt}}' "$C" 2>/dev/null || true)"
  redis_after="$(pid_for '[r]edis-server.*6379' || true)"
  [ -n "$redis_after" ] && [ "$redis_after" != "$redis_before" ] \
    && [ "$started_after" != "$started_before" ] && break
  sleep 0.5
done
expect "redis exit kept container identity" "$container_id" "$(docker inspect -f '{{.Id}}' "$C" 2>/dev/null || true)"
if [ -n "$redis_after" ] && [ "$redis_after" != "$redis_before" ] \
  && [ "$started_after" != "$started_before" ]; then
  echo "  ✓ redis exit restarted tenant pid=$redis_before→$redis_after"
else
  echo "  ✗ redis exit did not restart tenant" >&2
  _FAILED=$((_FAILED+1))
fi
finish core-service-isolation
