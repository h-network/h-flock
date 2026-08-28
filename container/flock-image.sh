#!/usr/bin/env bash
# flock-image.sh — one answer to "which image are we testing?". Source it.
#
#   . container/flock-image.sh
#   export FLOCK_IMAGE="$(flock_image_tag)"
#   flock_build_flag                      # prints --build, or nothing
#
# ⚠ WHY THIS EXISTS. Everything used to build `h-flock:latest` with `--build` on
# every `compose up`. A full sweep of three suites built the SAME image FIVE
# times — setup.sh once per suite, plus once inside each self-contained fault
# scenario — all of them overwriting one mutable tag with an identical result.
#
# ⚠⚠ AND `latest` IS WHY WE COULD NOT SIMPLY SKIP THE REBUILD. A tag that says
# nothing about its source cannot tell you whether the image matches the code
# under test, so "reuse if present" would silently test stale code — a suite
# passing against something you did not write is worse than a slow suite.
#
# Tagging by commit removes the question: the image's EXISTENCE is proof it was
# built from that source. Source changes, SHA changes, no image, it builds.
#
# ⚠ A dirty tree cannot be named, so it is never cached. `h-flock:dirty` is
# rebuilt every time and reused by nothing, because an image tagged with a commit
# it does not contain would be a lie of exactly the kind this avoids.

flock_image_tag() {
  local sha
  if sha="$(git rev-parse --short HEAD 2>/dev/null)" \
     && git diff --quiet HEAD -- 2>/dev/null \
     && [ -z "$(git ls-files --others --exclude-standard -- src container setup.sh 2>/dev/null)" ]; then
    echo "h-flock:${sha}"
  else
    echo "h-flock:dirty"
  fi
}

flock_web_image_tag() {
  local tenant_image="${FLOCK_IMAGE:-$(flock_image_tag)}"
  echo "h-flock-web:${tenant_image#h-flock:}"
}

# `--build` when the image is absent or unnameable, nothing when it is already
# there. FLOCK_FORCE_BUILD=1 overrides, for when you want it fresh regardless.
flock_build_flag() {
  local image="${FLOCK_IMAGE:-$(flock_image_tag)}"
  local web_image="${FLOCK_WEB_IMAGE:-$(flock_web_image_tag)}"
  if [ "${FLOCK_FORCE_BUILD:-0}" = "1" ] || [ "$image" = "h-flock:dirty" ] \
     || { [ "${MINI_APP_ENABLED:-0}" = "1" ] && [ "$web_image" = "h-flock-web:dirty" ]; }; then
    echo "--build"; return
  fi
  docker image inspect "$image" >/dev/null 2>&1 || { echo "--build"; return; }
  [ "${MINI_APP_ENABLED:-0}" != "1" ] \
    || docker image inspect "$web_image" >/dev/null 2>&1 \
    || echo "--build"
}

# Say which image a run used, so a surprising result can be traced to the build
# it came from rather than assumed to be current.
flock_image_line() {
  local image="${FLOCK_IMAGE:-$(flock_image_tag)}"
  local created
  created="$(docker image inspect -f '{{.Created}}' "$image" 2>/dev/null | cut -c1-19)"
  echo "FLOCK_IMAGE ${image} created=${created:-absent}"
}

# ⚠ Keep the newest few and drop the rest. One image per commit fills a disk
# quickly, and the lab has ~26G. Three is enough to switch between a branch and
# main without rebuilding both every time.
flock_prune_images() {
  local keep="${FLOCK_IMAGE_KEEP:-3}"
  docker images --filter=reference='h-flock:*' --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | sort -r | tail -n +$((keep + 1)) | cut -f2 \
    | while read -r old; do
        [ "$old" = "${FLOCK_IMAGE:-}" ] && continue
        docker rmi "$old" >/dev/null 2>&1 || true
      done
}
