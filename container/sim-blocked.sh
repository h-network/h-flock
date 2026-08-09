#!/usr/bin/env bash
# sim-blocked.sh — failure simulator for unverified deliveries and blocked states.
#
# Drives three failure cases against a running tenant:
#   1. wedged_process          (SIGSTOP CLI process -> delivery unverified, blocked set)
#   2. trust_picker            (unseeded claude trust -> delivery unverified, blocked set)
#   3. login_prompt_known_gap  (unauthenticated CLI profile -> verify passes, blocked NOT set [known gap])
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

HAD_CLAUDE_JSON=0
PANE_PID=""

poll_window_gone() {
    local agent="$1"
    for _ in $(seq 1 20); do
        if [ "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT 2>/dev/null | grep -c \" $agent\" || true")" = "0" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

cleanup() {
    echo "=== sim-blocked teardown: restoring tenant state ==="
    if [ -n "$PANE_PID" ]; then
        dx kill -CONT "$PANE_PID" 2>/dev/null || true
    fi

    for agent in sim-wedged sim-trust sim-nologin; do
        cu -X POST -H 'Content-Type: application/json' -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"$agent\"}}" "$A/agents/host/envelopes" >/dev/null 2>&1 || true
        dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:$agent:profile" >/dev/null 2>&1 || true
        poll_window_gone "$agent" || true
    done

    if [ "$HAD_CLAUDE_JSON" -eq 1 ]; then
        dx bash -c "if [ -f /home/ubuntu/.claude.json.sim-bak ]; then mv -f /home/ubuntu/.claude.json.sim-bak /home/ubuntu/.claude.json; fi" 2>/dev/null || true
    else
        dx bash -c "rm -f /home/ubuntu/.claude.json /home/ubuntu/.claude.json.sim-bak" 2>/dev/null || true
    fi

    dx bash -c "rm -rf /home/ubuntu/.codex-simnologin /home/ubuntu/.claude-simnologin" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "=== sim-blocked: failure simulator ==="

# Check initial state of .claude.json and back up if present
if dx bash -c "[ -f /home/ubuntu/.claude.json ]" 2>/dev/null; then
    HAD_CLAUDE_JSON=1
    dx bash -c "cp -f /home/ubuntu/.claude.json /home/ubuntu/.claude.json.sim-bak" 2>/dev/null
fi

# ── Case 1: wedged_process (SIGSTOP CLI) ──
echo "== Case 1: wedged_process (SIGSTOP CLI) =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-wedged","cli":"claude"}}' "$A/agents/host/envelopes" >/dev/null
sleep 4

PANE_PID=$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-panes -t ${TENANT}:sim-wedged -F '#{pane_pid}' 2>/dev/null | head -1" || true)

if [ -n "$PANE_PID" ]; then
    dx kill -STOP "$PANE_PID" 2>/dev/null || true

    cu -X POST -H 'Content-Type: application/json' -d '{"text":"wake up","as":"telegram"}' "$A/agents/sim-wedged/envelopes" >/dev/null

    echo "  waiting for router verification pass..."
    sleep 12

    BLOCKED_STATE=$(cu "$A/agents/sim-wedged" | python3 -c "import sys,json; print(json.load(sys.stdin).get('presence',{}).get('state',''))" 2>/dev/null || true)
    ckc "sim-wedged is blocked" "$BLOCKED_STATE" "blocked"

    dx kill -CONT "$PANE_PID" 2>/dev/null || true
    PANE_PID=""
else
    echo "  FAIL  sim-wedged pane PID not found"
    fail=$((fail+1))
fi

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-wedged"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_gone "sim-wedged"
ck "sim-wedged window cleaned up" "$?" "0"


# ── Case 2: trust_picker (unseeded trust) ──
echo "== Case 2: trust_picker (unseeded trust) =="
dx bash -c "rm -f /home/ubuntu/.claude.json" 2>/dev/null || true

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-trust","cli":"claude"}}' "$A/agents/host/envelopes" >/dev/null
sleep 4

cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello trust picker","as":"telegram"}' "$A/agents/sim-trust/envelopes" >/dev/null

echo "  waiting for router verification pass..."
sleep 12

BLOCKED_STATE=$(cu "$A/agents/sim-trust" | python3 -c "import sys,json; print(json.load(sys.stdin).get('presence',{}).get('state',''))" 2>/dev/null || true)
ckc "sim-trust is blocked" "$BLOCKED_STATE" "blocked"

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-trust"}}' "$A/agents/host/envelopes" >/dev/null
poll_window_gone "sim-trust"
ck "sim-trust window cleaned up" "$?" "0"


# ── Case 3: login_prompt_known_gap (unauthenticated CLI profile) ──
echo "== Case 3: login_prompt_known_gap (unauthenticated CLI profile) =="
# Isolate profile credential by assigning an isolated unauthenticated profile directory
dx redis-cli SET "pod:$POD:tenant:$TENANT:agent:sim-nologin:profile" "simnologin" >/dev/null
dx bash -c "rm -rf /home/ubuntu/.codex-simnologin" 2>/dev/null || true

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"sim-nologin","cli":"codex"}}' "$A/agents/host/envelopes" >/dev/null
sleep 4

cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello login prompt","as":"telegram"}' "$A/agents/sim-nologin/envelopes" >/dev/null

echo "  waiting for router verification pass..."
sleep 12

# ⚠ Known gap: CLI at login prompt records input in transcript/history log, so verify passes and blocked is NOT set
BLOCKED_STATE=$(cu "$A/agents/sim-nologin" | python3 -c "import sys,json; print(json.load(sys.stdin).get('presence',{}).get('state',''))" 2>/dev/null || true)
ck "sim-nologin known gap: blocked is NOT set" "$BLOCKED_STATE" "idle"

cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"sim-nologin"}}' "$A/agents/host/envelopes" >/dev/null
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:sim-nologin:profile" >/dev/null
poll_window_gone "sim-nologin"
ck "sim-nologin window cleaned up" "$?" "0"

echo
echo "sim-blocked: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
