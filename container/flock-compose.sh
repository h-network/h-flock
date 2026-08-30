#!/usr/bin/env bash
# Resolve the complete tenant-specific compose file list. Source this file.
#
#   . container/flock-compose.sh
#   resolve_compose_files hq      # populates tenant context and file list
#   COMPOSE=(docker compose -p "$FLOCK_COMPOSE_PROJECT" --env-file "$FLOCK_TENANT_ENV_PATH")
#   for file in "${FLOCK_COMPOSE_FILES[@]}"; do COMPOSE+=(-f "$file"); done
#   "${COMPOSE[@]}" ...
# The base has no ports; optional publication and mini-app fragments must be
# included consistently by every caller.

FLOCK_REPO_ROOT="${FLOCK_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

resolve_tenant_context() {
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
  FLOCK_TENANT_DIR="$FLOCK_REPO_ROOT/tenants/$tenant"
  FLOCK_TENANT_ENV_PATH="$FLOCK_TENANT_DIR/.env"
  FLOCK_COMPOSE_PROJECT="h-flock-$tenant"
  FLOCK_TENANT_CONTAINER="$FLOCK_COMPOSE_PROJECT-tenant-1"
  export TENANT FLOCK_TENANT_DIR FLOCK_TENANT_ENV_PATH FLOCK_COMPOSE_PROJECT FLOCK_TENANT_CONTAINER
}

resolve_compose_files() {
  resolve_tenant_context "${1:-${TENANT:-}}" || return
  FLOCK_COMPOSE_FILES=("$FLOCK_REPO_ROOT/container/compose.yaml")
  if [ -f "$FLOCK_TENANT_DIR/compose.ports.yaml" ]; then
    FLOCK_COMPOSE_FILES+=("$FLOCK_TENANT_DIR/compose.ports.yaml")
  fi
  if [ -f "$FLOCK_TENANT_DIR/compose.mini-app.yaml" ]; then
    FLOCK_COMPOSE_FILES+=("$FLOCK_TENANT_DIR/compose.mini-app.yaml")
  fi
}
