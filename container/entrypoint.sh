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

# Hold it out of the inherited environment from here on. The tmux server is
# started below and every agent window inherits the server's environment, so an
# exported API_TOKEN ends up readable in every pane — and with the Command kind
# that makes any agent able to run arbitrary code in any other agent's window.
# Only the api process needs it, so only the api process gets it.
api_token="$API_TOKEN"
unset API_TOKEN

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
start redis redis-server --bind 127.0.0.1 --port 6379 --save '' --appendonly no --dir /tmp
until redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; do sleep 0.2; done

# ── seed the roster ───────────────────────────────────────────────────────────
# Boot configuration, not the write path LLD-bus-and-router §7 defers. The roster
# is the MAC table: a HASH of agent -> VAB (§3.2). HSET is idempotent, so
# bringing the container up twice converges (LLD-container §5).
#
# AGENTS is name:vab pairs — AGENTS=alice:tmux,bob:tmux,carol:tmux
roster_key="pod:${POD}:tenant:${TENANT}:roster"
IFS=',' read -ra entries <<< "$AGENTS"
agents=()
fields=()
for entry in "${entries[@]}"; do
  name="${entry%%:*}"
  vab="${entry#*:}"
  if [ "$name" = "$entry" ] || [ -z "$vab" ]; then
    echo "entrypoint: AGENTS entry '$entry' is not name:vab" >&2
    exit 1
  fi
  agents+=("$name")
  fields+=("$name" "$vab")
done

# Fixed agents. Roster rows like any other — the router special-cases nothing
# (LLD-bus-and-router §3.2). `host` is what StartAgent/StopAgent are addressed
# to; its VAB routes delivery to flock.control rather than to a tmux window, so
# it has no window and the tmux host filters it out.
fields+=("api" "api")
fields+=("host" "control")

redis-cli -h 127.0.0.1 HSET "$roster_key" "${fields[@]}" >/dev/null
echo "{\"module\":\"container\",\"event\":\"roster_seeded\",\"count\":$(( ${#fields[@]} / 2 ))}"

# Seeding is the only use of AGENTS. Hold it out of the environment from here:
# the tmux server is started below and every agent window inherits its
# environment, so an exported AGENTS put the raw seed string — VABs included,
# and the agent itself in the list — in front of every agent. Asked where its
# peers were, one read that, found it confusing, and went to redis-cli for a
# better answer. Peers reach a window as AGENT_PEERS, derived from the roster.
unset AGENTS

# ── tmux host ─────────────────────────────────────────────────────────────────
start tmuxhost python3 -m flock.tmuxhost

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
start router  env REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}" python3 -m flock.router
# No adapter here. It is not a service — the router kicks `flock.adapter <agent>`
# per delivery and it exits (LLD-adapter-tmux §2). Starting one at boot would be
# the daemon this build exists to remove.
# The doors last, so neither is reachable before the tenant behind it is up
# (§5). The token is handed to these two processes and nothing else — it must
# not reach a tmux window, where the Command kind would make it root on every
# peer (§3).
start api     env API_TOKEN="$api_token" python3 -m flock.api
start session env API_TOKEN="$api_token" python3 -m flock.session

wait -n
