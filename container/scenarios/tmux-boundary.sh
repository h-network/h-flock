#!/usr/bin/env bash
# Boundary is intentionally limited to credentials visible to tmux itself and
# to the actual pane processes. The old peer-workdir probe typed commands into
# interactive CLIs; docker exec would test the tenant user, not the pane, so it
# is deliberately not replaced.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

TENANT="${TENANT:-tmux-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
WRITER="${WRITER:-architect}"
READER="${READER:-observer}"
TMUX=(docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)
PROHIBITED='^(API_TOKEN|REDIS_PASSWORD|REDISCLI_AUTH|REDIS_URL)='

env_has_credentials() {
  local label="$1"; shift
  local names
  names="$("$@" 2>/dev/null | grep -E "$PROHIBITED" | cut -d= -f1 || true)"
  if [ -n "$names" ]; then
    echo "  ✗ $label exposed_names=$(printf '%s' "$names" | tr '\n' ',')" >&2
    _FAILED=$((_FAILED+1))
  else
    echo "  ✓ $label has no prohibited credential names"
  fi
}

env_has_credentials "tmux-global" "${TMUX[@]}" show-environment -g
for agent in "$WRITER" "$READER"; do
  pane_pid="$("${TMUX[@]}" list-panes -t "${TENANT}:${agent}" -F '#{pane_pid}' 2>/dev/null | head -1)"
  [ -n "$pane_pid" ] || incomplete tmux-boundary "missing_pane_pid_${agent}"
  env_has_credentials "pane-${agent}" docker exec "$C" sh -c "tr '\0' '\n' </proc/$pane_pid/environ"
done
finish tmux-boundary
