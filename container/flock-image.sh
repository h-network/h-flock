#!/usr/bin/env bash
# Resolve reproducible image tags and build policy. Source this file.
#
#   . container/flock-image.sh
#   export FLOCK_TENANT_IMAGE="$(tenant_image_tag)"
#   required_build_flag                   # prints --build, or nothing
# Commit tags make image existence evidence of matching source. Dirty trees use
# an uncacheable tag and therefore always rebuild.

tenant_image_tag() {
  local sha
  if sha="$(git rev-parse --short HEAD 2>/dev/null)" \
     && git diff --quiet HEAD -- 2>/dev/null \
     && [ -z "$(git ls-files --others --exclude-standard -- src container setup.sh 2>/dev/null)" ]; then
    echo "h-flock:${sha}"
  else
    echo "h-flock:dirty"
  fi
}

mini_app_image_tag() {
  local tenant_image="${FLOCK_TENANT_IMAGE:-$(tenant_image_tag)}"
  echo "h-flock-web:${tenant_image#h-flock:}"
}

# Force a build for absent, dirty, or explicitly invalidated images.
required_build_flag() {
  local image="${FLOCK_TENANT_IMAGE:-$(tenant_image_tag)}"
  local mini_app_image="${FLOCK_MINI_APP_IMAGE:-$(mini_app_image_tag)}"
  if [ "${FLOCK_FORCE_IMAGE_BUILD:-0}" = "1" ] || [ "$image" = "h-flock:dirty" ] \
     || { [ "${MINI_APP_ENABLED:-0}" = "1" ] && [ "$mini_app_image" = "h-flock-web:dirty" ]; }; then
    echo "--build"; return
  fi
  docker image inspect "$image" >/dev/null 2>&1 || { echo "--build"; return; }
  [ "${MINI_APP_ENABLED:-0}" != "1" ] \
    || docker image inspect "$mini_app_image" >/dev/null 2>&1 \
    || echo "--build"
}

describe_tenant_image() {
  local image="${FLOCK_TENANT_IMAGE:-$(tenant_image_tag)}"
  local created
  created="$(docker image inspect -f '{{.Created}}' "$image" 2>/dev/null | cut -c1-19)"
  echo "FLOCK_TENANT_IMAGE ${image} created=${created:-absent}"
}

# Bound disk use while retaining enough images for branch switching.
prune_tenant_images() {
  local retention_count="${FLOCK_IMAGE_RETENTION_COUNT:-3}"
  docker images --filter=reference='h-flock:*' --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | sort -r | tail -n +$((retention_count + 1)) | cut -f2 \
    | while read -r old_image; do
        [ "$old_image" = "${FLOCK_TENANT_IMAGE:-}" ] && continue
        docker rmi "$old_image" >/dev/null 2>&1 || true
      done
}
