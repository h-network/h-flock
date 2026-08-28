#!/usr/bin/env bash
# flock-compose.sh — one answer to "which compose files are we loading?".
# Source it.
#
#   . container/flock-compose.sh
#   flock_compose_args hq         # populates tenant context and compose args
#   docker compose -p "$FLOCK_PROJECT" --env-file "$TENANT_ENV_FILE" \
#     "${FLOCK_COMPOSE_ARGS[@]}" ...
#
# ⚠ WHY THIS EXISTS. A tenant's base compose.yaml carries NO `ports:` key,
# so an unpublished tenant exposes zero ports by default. When an operator
# publishes a door, setup.sh writes the `ports:` block into an override
# fragment at `tenants/<tenant>/compose.ports.yaml`.
#
# Sourcing this helper guarantees every compose invocation includes the
# fragments when present and omits them when absent, avoiding ten manual
# `-f` repetitions across setup and testbed scenarios.

FLOCK_REPO_ROOT="${FLOCK_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

flock_tenant_context() {
  local tenant="${1:-}"
  if [[ ! "$tenant" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] \
     || [[ "$tenant" =~ ^[0-9]+$ ]]; then
    echo "flock-compose: invalid tenant '$tenant'" >&2
    return 2
  fi
  case "$tenant" in pod|tenant|agent|all)
    echo "flock-compose: reserved tenant '$tenant'" >&2
    return 2
  esac

  TENANT="$tenant"
  TENANT_DIR="$FLOCK_REPO_ROOT/tenants/$tenant"
  TENANT_ENV_FILE="$TENANT_DIR/.env"
  FLOCK_TENANT_ENV_FILE="$TENANT_ENV_FILE"
  FLOCK_PROJECT="h-flock-$tenant"
  FLOCK_CONTAINER="$FLOCK_PROJECT-tenant-1"
  export TENANT TENANT_DIR TENANT_ENV_FILE FLOCK_TENANT_ENV_FILE FLOCK_PROJECT FLOCK_CONTAINER
}

flock_compose_args() {
  flock_tenant_context "${1:-${TENANT:-}}" || return
  FLOCK_COMPOSE_ARGS=("-f" "$FLOCK_REPO_ROOT/container/compose.yaml")
  if [ -f "$TENANT_DIR/compose.ports.yaml" ]; then
    FLOCK_COMPOSE_ARGS+=("-f" "$TENANT_DIR/compose.ports.yaml")
  fi
  if [ -f "$TENANT_DIR/compose.mini-app.yaml" ]; then
    FLOCK_COMPOSE_ARGS+=("-f" "$TENANT_DIR/compose.mini-app.yaml")
  fi
}
