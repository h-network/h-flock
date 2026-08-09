#!/usr/bin/env bash
# sim-blocked.sh — failure simulator for unverified deliveries and blocked states.
#
# Drives three failure cases against a running tenant:
#   1. wedged_process          (SIGSTOP CLI process -> delivery unverified, blocked set)
#   2. trust_picker            (unseeded claude trust profile -> delivery unverified, blocked set)
#   3. login_prompt_known_gap  (unauthenticated CLI profile -> verify passes, blocked key empty [known gap])
#
# Usage:
#   bash container/sim-blocked.sh
#
set -uo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_here/.env" ] && . "$_here/.env"
POD="${POD:-acme}"
TENANT="${TENANT:-hq}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
ROSTER="pod:$POD:tenant:$TENANT:roster"
T=$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)
[ -n "$T" ] || { echo "sim-blocked: container $C is not running" >&2; exit 1; }

A="http://127.0.0.1:8080"
H="Authorization: Bearer $T"
dx() { docker exec "$C" "$@"; }
cu() { dx curl -s -H "$H" "$@"; }

pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : expected [$3] got [$2]"; fail=$((fail+1)); fi; }
ckc() { if echo "$2" | grep -q "$3"; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : [$2] lacks [$3]"; fail=$((fail+1)); fi; }

STOPPED_PIDS=""

poll_window_ready() {
    local agent="$1"
    for _ in $(seq 1 30); do
        if [ "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT 2>/dev/null | grep -c \" $agent\" || true")" -gt 0 ]; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

poll_window_gone() {
    local agent="$1"
    for _ in $(seq 1 30); do
        if [ "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT 2>/dev/null | grep -c \" $agent\" || true")" = "0" ]; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

poll_blocked_state() {
    local agent="$1"
    for _ in $(seq 1 40); do
        local state=$(cu "$A/agents/$agent" | python3 -c "import sys,json; print(json.load(sys.stdin).get('presence',{}).get('state',''))" 2>/dev/null || true)
        if [ "$state" = "blocked" ]; then
            echo "blocked"
            return 0
        fi
        sleep 0.5
    done
    cu "$A/agents/$agent" | python3 -c "import sys,json; print(json.load(sys.stdin).get('presence',{}).get('state',''))" 2>/dev/null || true
}

get_cli_pid() {
    local pane_pid="$1"
    local children=$(dx pgrep -P "$pane_pid" 2>/dev/null || true)
    for cpid in $children; do
        local grandchildren=$(dx pgrep -P "$cpid" 2>/dev/null || true)
        if [ -n "$grandchildren" ]; then
            echo "$grandchildren" | head -1
            return 0
        else
            echo "$cpid"
            return 0
        fi
    done
    echo "$pane_pid"
}

is_process_stopped() {
    local pid="$1"
    local state=$(dx bash -c "ps -o state= -p $pid 2>/dev/null | tr -d ' '" || true)
    case "$state" in
        T*|t*) return 0 ;;
        *) return 1 ;;
    esac
}

cleanup() {
    echo "=== sim-blocked teardown: restoring tenant state ==="
    if [ -n "$STOPPED_PIDS" ]; then
        for pid in $STOPPED_PIDS; do
            dx kill -CONT "$pid" 2>/dev/null || true
        done
    fi

    for agent in sim-wedged sim-trust sim-nologin; do
        cu -X POST -H 'Content-Type: application/json' -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"$agent\"}}" "$A/agents/host/envelopes" >/dev/null 2>&1 || true
        dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:$agent:profile" >/dev/null 2>&1 || true
        poll_window_gone "$agent" || true
    done

    # Clean up isolated per-agent profile directories only (NEVER touch shared ~/.claude.json)
    dx bash -c "rm -rf /home/ubuntu/.claude-simtrust /home/ubuntu/.codex-simnologin /home/ubuntu/.claude-simnologin" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "=== sim-blocked: failure simulator ==="

# ── Case 1: wedged_process (SIGSTOP CLI process) ──
echo "== Case 1: wedged_process (SIGSTOP CLI) =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-wedged","cli":"claude"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_ready "sim-wedged"
ck "sim-wedged window created" "$?" "0"

PANE_PID=$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-panes -t ${TENANT}:sim-wedged -F '#{pane_pid}' 2>/dev/null | head -1" || true)

if [ -n "$PANE_PID" ]; then
    CLI_PID=$(get_cli_pid "$PANE_PID")
    dx kill -STOP "$CLI_PID" 2>/dev/null || true
    dx kill -STOP "$PANE_PID" 2>/dev/null || true
    STOPPED_PIDS="$CLI_PID $PANE_PID"

    # Assert that CLI process is actually stopped (state T) BEFORE posting envelope
    is_process_stopped "$CLI_PID"
    ck "CLI process is stopped (state T)" "$?" "0"

    cu -X POST -H 'Content-Type: application/json' -d '{"text":"wake up","as":"telegram"}' "$A/agents/sim-wedged/envelopes" >/dev/null

    echo "  polling for router verification pass..."
    BLOCKED_STATE=$(poll_blocked_state "sim-wedged")
    ckc "sim-wedged is blocked" "$BLOCKED_STATE" "blocked"

    dx kill -CONT "$CLI_PID" 2>/dev/null || true
    dx kill -CONT "$PANE_PID" 2>/dev/null || true
    STOPPED_PIDS=""
else
    echo "  FAIL  sim-wedged pane PID not found"
    fail=$((fail+1))
fi

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-wedged"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_gone "sim-wedged"
ck "sim-wedged window cleaned up" "$?" "0"


# ── Case 2: trust_picker (unseeded claude trust profile) ──
echo "== Case 2: trust_picker (unseeded trust) =="
# Isolate profile for sim-trust to avoid touching shared tenant ~/.claude.json
dx redis-cli SET "pod:$POD:tenant:$TENANT:agent:sim-trust:profile" "simtrust" >/dev/null
dx bash -c "rm -rf /home/ubuntu/.claude-simtrust" 2>/dev/null || true

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-trust","cli":"claude"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_ready "sim-trust"
ck "sim-trust window created" "$?" "0"

# Remove the isolated profile's .claude.json so trust picker prompt appears
dx bash -c "rm -f /home/ubuntu/.claude-simtrust/.claude.json" 2>/dev/null || true

cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello trust picker","as":"telegram"}' "$A/agents/sim-trust/envelopes" >/dev/null

echo "  polling for router verification pass..."
BLOCKED_STATE=$(poll_blocked_state "sim-trust")
ckc "sim-trust is blocked" "$BLOCKED_STATE" "blocked"

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-trust"}}' "$A/agents/host/envelopes" >/dev/null
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:sim-trust:profile" >/dev/null
poll_window_gone "sim-trust"
ck "sim-trust window cleaned up" "$?" "0"


# ── Case 3: login_prompt_known_gap (unauthenticated CLI profile) ──
echo "== Case 3: login_prompt_known_gap (unauthenticated CLI profile) =="
# Isolate profile credential by assigning an isolated unauthenticated profile directory
dx redis-cli SET "pod:$POD:tenant:$TENANT:agent:sim-nologin:profile" "simnologin" >/dev/null
dx bash -c "rm -rf /home/ubuntu/.codex-simnologin" 2>/dev/null || true

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-nologin","cli":"codex"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_ready "sim-nologin"
ck "sim-nologin window created" "$?" "0"

cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello login prompt","as":"telegram"}' "$A/agents/sim-nologin/envelopes" >/dev/null

echo "  polling for router verification pass..."
# Wait for verifier pass (verify_after_seconds = 10s)
sleep 11

# ⚠ Known gap: CLI at login prompt records input in transcript/history log, so verify passes and blocked key is ABSENT in Redis
BLOCKED_RAW=$(dx redis-cli HGETALL "pod:$POD:tenant:$TENANT:agent:sim-nologin:blocked" 2>/dev/null || true)
ck "sim-nologin known gap: blocked key is empty" "$BLOCKED_RAW" ""

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-nologin"}}' "$A/agents/host/envelopes" >/dev/null
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:sim-nologin:profile" >/dev/null
poll_window_gone "sim-nologin"
ck "sim-nologin window cleaned up" "$?" "0"

echo
echo "sim-blocked: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
