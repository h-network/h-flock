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

poll_blocked_key() {
    local agent="$1"
    local key="pod:$POD:tenant:$TENANT:agent:$agent:blocked"
    for _ in $(seq 1 40); do
        local val=$(dx redis-cli HGETALL "$key" 2>/dev/null || true)
        if [ -n "$val" ]; then
            echo "$val"
            return 0
        fi
        sleep 0.5
    done
    dx redis-cli HGETALL "$key" 2>/dev/null || true
}

get_cli_pid() {
    local pane_pid="$1"
    local target_cli="${2:-claude}"

    # 1. Check pane_pid directly first — since startAgent execs, pane_pid IS the CLI
    local pane_cmd=$(dx bash -c "cat /proc/$pane_pid/cmdline 2>/dev/null | tr '\0' ' '" || true)
    if echo "$pane_cmd" | grep -iqE "$target_cli|claude|codex|node|python"; then
        echo "$pane_pid"
        return 0
    fi

    # 2. Check direct children if pane_pid was bash
    local children=$(dx pgrep -P "$pane_pid" 2>/dev/null || true)
    for cpid in $children; do
        local ccmd=$(dx bash -c "cat /proc/$cpid/cmdline 2>/dev/null | tr '\0' ' '" || true)
        if echo "$ccmd" | grep -iqE "$target_cli|claude|codex|node|python"; then
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

PROVED_WEDGED=0
CLI_PID=""

if [ -n "$PANE_PID" ]; then
    CLI_PID=$(get_cli_pid "$PANE_PID" "claude")
    dx kill -STOP "$CLI_PID" 2>/dev/null || true
    STOPPED_PIDS="$CLI_PID"

    if is_process_stopped "$CLI_PID"; then
        PROVED_WEDGED=1
    fi
fi

if [ "$PROVED_WEDGED" -eq 1 ]; then
    ck "sim-wedged precondition proved (CLI process $CLI_PID stopped in state T)" "0" "0"

    cu -X POST -H 'Content-Type: application/json' -d '{"text":"wake up","as":"telegram"}' "$A/agents/sim-wedged/envelopes" >/dev/null

    echo "  polling for router verification pass (blocked Redis key)..."
    BLOCKED_KEY=$(poll_blocked_key "sim-wedged")
    ckc "sim-wedged is blocked" "$BLOCKED_KEY" "since"

    dx kill -CONT "$CLI_PID" 2>/dev/null || true
    STOPPED_PIDS=""
else
    ck "sim-wedged precondition proved (CLI process $CLI_PID stopped in state T)" "failed" "0"
    echo "  ABORT Case 1: wedged process setup failed (CLI process PID: $CLI_PID not stopped)"
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

# Remove pre-seeded trust file in isolated profile and restart claude in pane
dx bash -c "rm -rf /home/ubuntu/.claude-simtrust/.claude.json" 2>/dev/null || true
PANE_PID=$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-panes -t ${TENANT}:sim-trust -F '#{pane_pid}' 2>/dev/null | head -1" || true)
if [ -n "$PANE_PID" ]; then
    C_PID=$(get_cli_pid "$PANE_PID" "claude")
    [ -n "$C_PID" ] && dx kill -9 "$C_PID" 2>/dev/null || true
fi
dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux send-keys -t ${TENANT}:sim-trust C-c 'startAgent claude' Enter" 2>/dev/null || true

# Prove precondition: poll pane output for trust picker or onboarding prompt
PROVED_TRUST=0
for _ in $(seq 1 20); do
    PANE_TEXT=$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t ${TENANT}:sim-trust 2>/dev/null" || true)
    if echo "$PANE_TEXT" | grep -iqE "trust|Do you trust|Yes, I trust|trust this folder|onboarding|welcome"; then
        PROVED_TRUST=1
        break
    fi
    sleep 0.5
done

if [ "$PROVED_TRUST" -eq 1 ]; then
    ck "sim-trust precondition proved (trust picker prompt shown)" "0" "0"

    cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello trust picker","as":"telegram"}' "$A/agents/sim-trust/envelopes" >/dev/null

    echo "  polling for router verification pass (blocked Redis key)..."
    BLOCKED_KEY=$(poll_blocked_key "sim-trust")
    ckc "sim-trust is blocked" "$BLOCKED_KEY" "since"
else
    ck "sim-trust precondition proved (trust picker prompt shown)" "failed" "0"
    echo "  ABORT Case 2: trust picker setup failed (prompt not shown in pane)"
fi

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

# Prove precondition: poll pane output for login prompt keywords
PROVED_NOLOGIN=0
for _ in $(seq 1 20); do
    PANE_TEXT=$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t ${TENANT}:sim-nologin 2>/dev/null" || true)
    if echo "$PANE_TEXT" | grep -iqE "Sign in|ChatGPT|OpenAI|API key|login|device code|auth"; then
        PROVED_NOLOGIN=1
        break
    fi
    sleep 0.5
done

if [ "$PROVED_NOLOGIN" -eq 1 ]; then
    ck "sim-nologin precondition proved (login prompt shown)" "0" "0"

    cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello login prompt","as":"telegram"}' "$A/agents/sim-nologin/envelopes" >/dev/null

    echo "  polling for router verification pass..."
    sleep 11

    # ⚠ Known gap: CLI at login prompt records input in transcript/history log, so verify passes and blocked key is ABSENT in Redis
    BLOCKED_RAW=$(dx redis-cli HGETALL "pod:$POD:tenant:$TENANT:agent:sim-nologin:blocked" 2>/dev/null || true)
    ck "sim-nologin known gap: blocked key is empty" "$BLOCKED_RAW" ""
else
    ck "sim-nologin precondition proved (login prompt shown)" "failed" "0"
    echo "  ABORT Case 3: login prompt setup failed (prompt not shown in pane)"
fi

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-nologin"}}' "$A/agents/host/envelopes" >/dev/null
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:sim-nologin:profile" >/dev/null
poll_window_gone "sim-nologin"
ck "sim-nologin window cleaned up" "$?" "0"

echo
echo "sim-blocked: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
