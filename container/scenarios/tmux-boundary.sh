#!/usr/bin/env bash
set -uo pipefail

TENANT="${TENANT:-tmux-lab}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
WRITER="${WRITER:-architect}"
READER="${READER:-observer}"
TMUX=(docker exec "$C" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)

echo "scenario=boundary tenant=$TENANT container=$C writer=$WRITER reader=$READER"
echo "tmux global credential variable names observed:"
"${TMUX[@]}" show-environment -g 2>&1 \
  | grep -E '^(API_TOKEN|REDIS_PASSWORD|REDISCLI_AUTH|REDIS_URL)=' \
  | cut -d= -f1 || true

for agent in "$WRITER" "$READER"; do
  pane_pid="$("${TMUX[@]}" list-panes -t "${TENANT}:${agent}" -F '#{pane_pid}' | head -1)"
  echo "agent=$agent pane_pid=$pane_pid credential variable names observed:"
  docker exec "$C" sh -c "tr '\\0' '\\n' </proc/$pane_pid/environ" \
    | grep -E '^(API_TOKEN|REDIS_PASSWORD|REDISCLI_AUTH|REDIS_URL)=' \
    | cut -d= -f1 || true
done

marker="boundary-$RANDOM-$(date +%s)"
echo "action=writer-creates-marker marker=$marker"
"${TMUX[@]}" send-keys -t "${TENANT}:${WRITER}" \
  "printf '%s\\n' '$marker' > /workdir/$WRITER/.boundary-probe" Enter
sleep 1
echo "action=reader-reads-writer-marker pane-output:"
"${TMUX[@]}" send-keys -t "${TENANT}:${READER}" \
  "cat /workdir/$WRITER/.boundary-probe" Enter
sleep 1
"${TMUX[@]}" capture-pane -p -S -100 -t "${TENANT}:${READER}" \
  | sed '/^[[:space:]]*$/d' | tail -12
docker exec "$C" rm -f "/workdir/$WRITER/.boundary-probe"
