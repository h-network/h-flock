#!/usr/bin/env bash
# flock-compose.sh — one answer to "which compose files are we loading?".
# Source it.
#
#   . container/flock-compose.sh
#   flock_compose_args            # populates FLOCK_COMPOSE_ARGS array
#   docker compose "${FLOCK_COMPOSE_ARGS[@]}" ...
#
# ⚠ WHY THIS EXISTS. A tenant's base compose.yaml carries NO `ports:` key,
# so an unpublished tenant exposes zero ports by default. When an operator
# publishes a door, setup.sh writes the `ports:` block into an override
# fragment at `container/compose.ports.yaml`.
#
# Sourcing this helper guarantees every compose invocation includes the
# fragment when present and omits it when absent, avoiding ten manual
# `-f` repetitions across setup and testbed scenarios.

flock_compose_args() {
  local root="${1:-.}"
  local base="${root}/container/compose.yaml"
  local ports="${root}/container/compose.ports.yaml"
  FLOCK_COMPOSE_ARGS=("-f" "$base")
  if [ -f "$ports" ]; then
    FLOCK_COMPOSE_ARGS+=("-f" "$ports")
  fi
}
