#!/usr/bin/env bash
# Brings up one tenant. Holds no logic of its own — it starts the modules in
# dependency order and gets out of the way (LLD-container §5, §8).
set -euo pipefail

require() {
  local missing=0
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      echo "entrypoint: $var is required" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || exit 1
}

# API_TOKEN is not optional: the api is the only mapped port and therefore the
# entire attack surface (LLD-container §3).
require POD TENANT AGENTS API_TOKEN

export TMUX_SESSION="${TMUX_SESSION:-$TENANT}"

# Socket access is total — anything that can reach it can send-keys into any
# pane. The directory permissions are the whole boundary (LLD-tmux-host §4).
mkdir -p "$TMUX_TMPDIR"
chmod 700 "$TMUX_TMPDIR"

pids=()
start() {
  local name="$1"; shift
  "$@" &
  local pid=$!
  pids+=("$pid")
  echo "{\"module\":\"container\",\"event\":\"started\",\"reason\":\"$name pid=$pid\"}"
}

# If a module exits, the tenant exits and the restart policy brings it back.
# Deliberately blunt for a skeleton — no partial states to reason about (§6).
shutdown() {
  local code=$?
  echo "{\"module\":\"container\",\"event\":\"stopped\",\"reason\":\"exit=$code\"}"
  kill "${pids[@]}" 2>/dev/null || true
  exit "$code"
}
trap shutdown EXIT INT TERM

# ── redis ─────────────────────────────────────────────────────────────────────
# Loopback only and never published. No persistence: a skeleton losing its
# queues on a restart is acceptable (§2, §7).
start redis redis-server --bind 127.0.0.1 --port 6379 --save '' --appendonly no
until redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; do sleep 0.2; done

# ── seed the roster ───────────────────────────────────────────────────────────
# Boot configuration, not the write path LLD-bus-and-router §7 defers. SADD is
# idempotent, so bringing the container up twice converges (CONTRACTS §5).
roster_key="pod:${POD}:tenant:${TENANT}:roster"
IFS=',' read -ra agents <<< "$AGENTS"
redis-cli -h 127.0.0.1 SADD "$roster_key" "${agents[@]}" >/dev/null
echo "{\"module\":\"container\",\"event\":\"roster_seeded\",\"count\":${#agents[@]}}"

# ── tmux host ─────────────────────────────────────────────────────────────────
start tmuxhost python -m flock.tmuxhost

# Windows lead routes. LLD-bus-and-router §3.2 names the one roster case that is
# not harmless: the router routing to an agent whose window does not exist yet,
# whose first envelopes are then dead-lettered into nothing. Waiting here is the
# cheapest possible answer — the host is already ahead, so nothing can race it.
deadline=$((SECONDS + 30))
for agent in "${agents[@]}"; do
  until tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
     && tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "entrypoint: timed out waiting for window '$agent'" >&2
      exit 1
    fi
    sleep 0.3
  done
done
echo "{\"module\":\"container\",\"event\":\"windows_ready\",\"count\":${#agents[@]}}"

# ── the rest ──────────────────────────────────────────────────────────────────
start router  python -m flock.router
start adapter python -m flock.adapter
# api last, so it is not reachable before the tenant behind it is up (§5).
start api     python -m flock.api

wait -n
