#!/usr/bin/env bash
# base-run-tmux — the same workload down the path real agents actually use.
#
#   CONTAINER=… POD=acme TENANT=… AGENTS="a b c" ROUNDS=20 bash base-run-tmux.sh OUT.log
#
# ⚠ **Every benchmark we have measures the API path.** `fabric-bench`,
# `base-run` and `conservation.sh` all use api clients — deliberately, so nothing
# runs a CLI and nothing costs a token. But a real agent is a **tmux** port, and
# that path does something the api path never does: it pastes into a pane and
# then sleeps `PASTE_ENTER_DELAY` (0.5 s) before sending Enter.
#
# Measured api delivery is 3–6 ms. A tmux delivery cannot be under 500 ms.
# **So every throughput figure in docs/BUILD-*.md describes a path agents do not
# use.**
#
# ⚠ **No CLI, no tokens.** An agent with no `launch` key gets a plain shell
# window from tmuxhost — the recipe `soak.sh` documents. The paste lands in
# `bash`. Bus, switch, port, spool, presence and the paste itself are all
# exercised identically; only the thing reading the pane differs.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
AGENTS="${AGENTS:?set AGENTS, space separated}"
ROUNDS="${ROUNDS:-20}"
OUT="${1:?usage: base-run-tmux.sh OUTPUT.log}"

dx() { docker exec "$CONTAINER" "$@"; }
read -r -a LIST <<< "$AGENTS"
N=${#LIST[@]}

echo "base-run-tmux: $N tmux ports x $ROUNDS rounds -> $OUT"

# ⚠ Strip the CLI so tmuxhost rebuilds each window as a shell.
for a in "${LIST[@]}"; do
  dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:$a:launch" >/dev/null 2>&1
done
dx bash -lc 'export TMUX_TMPDIR=/home/ubuntu/.flock/tmux; for w in $(tmux list-windows -t '"$TENANT"' -F "#{window_name}" 2>/dev/null); do tmux kill-window -t '"$TENANT"':$w 2>/dev/null; done' >/dev/null 2>&1
sleep 20
echo "  windows: $(dx bash -lc 'export TMUX_TMPDIR=/home/ubuntu/.flock/tmux; tmux list-windows -t '"$TENANT"' 2>/dev/null | wc -l' | tr -d '\r')"

docker exec -i "$CONTAINER" python3 - <<PY
import os, sys, time
sys.path.insert(0, "/app/src")
import redis
from flock.bus.doors import send
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
agents = "$AGENTS".split()
t0 = time.time()
n = 0
for rnd in range($ROUNDS):
    for i, a in enumerate(agents):
        send(r, pod="$POD", tenant="$TENANT", source=a,
             destination=agents[(i + 1) % len(agents)],
             kind="Message", payload={"text": f"r{rnd}"})
        n += 1
print(f"  submitted {n} in {time.time()-t0:.1f}s")
PY

echo "  draining"
for _ in $(seq 1 1800); do
  DEPTH=$(dx python3 -c "
import os,sys; sys.path.insert(0,'/app/src')
import redis
r=redis.Redis.from_url(os.environ.get('REDIS_URL','redis://127.0.0.1:6379/0'))
print(sum(r.llen(k) for k in r.scan_iter(match='pod:$POD:tenant:$TENANT:agent:*:ingress')) +
      sum(r.llen(k) for k in r.scan_iter(match='pod:$POD:tenant:$TENANT:agent:*:egress')))" 2>/dev/null | tr -d '\r')
  [ "${DEPTH:-1}" = "0" ] && break
  sleep 2
done

sleep 3
docker logs "$CONTAINER" > "$OUT" 2>&1
echo "  captured $(wc -l < "$OUT") lines"
echo "  ⚠ compare received->opened against the api baseline: that is where the paste delay lives"
