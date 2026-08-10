#!/usr/bin/env bash
# seed-home.sh — copy container/home/ into a running tenant, and copy credentials
# back out again after an interactive login.
#
#   ./container/seed-home.sh in    [container]     host  → container
#   ./container/seed-home.sh out   [container]     container → host   (logins only)
#   ./container/seed-home.sh check [container]     which accounts still need one
#
# Run `in` after `compose up`. Secrets travel by `docker cp` rather than a COPY
# or a volume: the image is rebuilt constantly and these are not, and a secret in
# an image is a secret in every copy of it (LLD-container §3).
set -uo pipefail

MODE="${1:-in}"
# Pod, tenant and container name come from container/.env — the same file the
# tenant was built from — rather than being hardcoded here. setup.sh names the
# compose project "h-flock-<tenant>", so the container is "<project>-tenant-1".
# Override either by exporting POD/TENANT, or by passing the container name.
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_here/.env" ] && . "$_here/.env"
POD="${POD:-acme}"
TENANT="${TENANT:-hq}"
CONTAINER="${2:-h-flock-${TENANT}-tenant-1}"
HOME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/home"
IN_CONTAINER="/home/ubuntu"

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
    echo "seed-home: no container '$CONTAINER'" >&2; exit 1; }

# The credential files each CLI keeps, and where. agy is the Antigravity CLI and
# keeps its own OAuth token — it is a third account, not a passenger on the other
# two (PLAN-profiles.md §7).
CRED_PATHS=(
    ".claude/.credentials.json"
    ".codex/auth.json"
    ".gemini/antigravity-cli/antigravity-oauth-token"
)

case "$MODE" in
  in)
    shopt -s dotglob nullglob
    items=("$HOME_DIR"/*)
    shopt -u dotglob nullglob
    copied=0
    for item in "${items[@]}"; do
        [ "$(basename "$item")" = "README.md" ] && continue
        docker cp "$item" "$CONTAINER:$IN_CONTAINER/" && copied=$((copied+1))
    done
    [ "$copied" -eq 0 ] && echo "seed-home: nothing in container/home to copy"

    # ssh refuses keys it considers world-readable, and docker cp does not
    # preserve the modes we need. Fix them in place rather than relying on the
    # host's.
    docker exec -u root "$CONTAINER" bash -c '
        chown -R ubuntu:ubuntu /home/ubuntu
        [ -d /home/ubuntu/.ssh ] && { chmod 700 /home/ubuntu/.ssh
            find /home/ubuntu/.ssh -type f -exec chmod 600 {} +
            chmod 644 /home/ubuntu/.ssh/*.pub 2>/dev/null; }
        for f in /home/ubuntu/.claude*/.credentials.json \
                 /home/ubuntu/.codex*/auth.json \
                 /home/ubuntu/.gemini/antigravity-cli/antigravity-oauth-token; do
            [ -f "$f" ] && chmod 600 "$f"
        done; true' >/dev/null 2>&1
    echo "seed-home: copied $copied item(s) into $CONTAINER"
    # ⚠ A CLI reads its credentials at startup, so one already running does not
    # notice these. It keeps sitting at a login prompt with a valid credential
    # on disk beside it, which reads as broken auth rather than a stale process.
    echo "seed-home: CLIs already running will not pick these up — restart them:"
    echo "           office pause <agent> && office resume <agent>   (keeps the agent, its board and its queue)"
    echo "           or  docker restart $CONTAINER                   (whole tenant)"
    ;;

  out)
    # After an interactive login inside a window, bring the credential back so
    # the next rebuild starts logged in. Only credentials — never the session
    # transcripts or project history that live alongside them.
    saved=0
    for rel in "${CRED_PATHS[@]}"; do
        docker exec "$CONTAINER" test -s "$IN_CONTAINER/$rel" 2>/dev/null || continue
        mkdir -p "$HOME_DIR/$(dirname "$rel")"
        docker cp "$CONTAINER:$IN_CONTAINER/$rel" "$HOME_DIR/$rel" && saved=$((saved+1))
    done
    # Extra profiles: .claude-<profile>/.credentials.json and .codex-<profile>/auth.json
    for rel in $(docker exec "$CONTAINER" bash -c \
        'ls -d /home/ubuntu/.claude-*/.credentials.json /home/ubuntu/.codex-*/auth.json 2>/dev/null' \
        | sed "s|$IN_CONTAINER/||"); do
        mkdir -p "$HOME_DIR/$(dirname "$rel")"
        docker cp "$CONTAINER:$IN_CONTAINER/$rel" "$HOME_DIR/$rel" && saved=$((saved+1))
    done
    echo "seed-home: saved $saved credential file(s) to container/home/"
    ;;

  check)
    docker exec "$CONTAINER" bash -c '
        profiles=("default")
        for d in /home/ubuntu/.claude-* /home/ubuntu/.codex-*; do
            [ -d "$d" ] || continue
            base="$(basename "$d")"
            p="${base#.*-}"
            [ -n "$p" ] && [[ " ${profiles[*]} " != *" $p "* ]] && profiles+=("$p")
        done

        for p in "${profiles[@]}"; do
            if [ "$p" = "default" ]; then
                claude_path="/home/ubuntu/.claude/.credentials.json"
                codex_path="/home/ubuntu/.codex/auth.json"
                agy_path="/home/ubuntu/.gemini/antigravity-cli/antigravity-oauth-token"
            else
                claude_path="/home/ubuntu/.claude-$p/.credentials.json"
                codex_path="/home/ubuntu/.codex-$p/auth.json"
                agy_path=""
            fi

            # ⚠ A file is not a login. Measured on a from-scratch install: a
            # 281-byte credentials file with expiresAt of 0 reported "logged in"
            # while every agent sat at "Not logged in · Run /login". Check the
            # token, not the inode.
            if [ -s "$claude_path" ]; then
                claude_state="$(python3 - "$claude_path" <<'PY' 2>/dev/null || echo UNREADABLE
import json, sys, time
try:
    d = json.load(open(sys.argv[1]))["claudeAiOauth"]
except Exception:
    print("UNREADABLE"); raise SystemExit
exp = d.get("refreshTokenExpiresAt") or d.get("expiresAt") or 0
print("logged in" if exp / 1000 > time.time() else "EXPIRED")
PY
)"
                printf "  %-9s %-7s %s\n" "$p" "claude" "$claude_state"
            else
                printf "  %-9s %-7s %s\n" "$p" "claude" "NEEDS LOGIN"
            fi

            if [ -s "$codex_path" ]; then
                printf "  %-9s %-7s %s\n" "$p" "codex" "logged in"
            else
                printf "  %-9s %-7s %s\n" "$p" "codex" "NEEDS LOGIN"
            fi

            if [ -n "$agy_path" ]; then
                if [ -s "$agy_path" ]; then
                    printf "  %-9s %-7s %s\n" "$p" "agy" "logged in"
                else
                    printf "  %-9s %-7s %s\n" "$p" "agy" "NEEDS LOGIN"
                fi
            fi
        done'
    ;;

  *) echo "usage: seed-home.sh [in|out|check] [container]" >&2; exit 2 ;;
esac
