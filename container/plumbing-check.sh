#!/usr/bin/env bash
# Plumbing check — the bus, boards, both doors and lifecycle, against a running
# tenant. No CLIs: bring the tenant up with AGENT_CLIS= so every window is a
# plain shell, and what is under test is h-flock rather than an agent's judgement.
#
#   AGENT_CLIS= docker compose -p h-flock-hq up -d --force-recreate
#
# ⚠ AGENT_CLIS= no longer gives plain shells on its own — the entrypoint defaults
# every tmux agent to claude, so that a plain install is not three bash prompts.
# For a CLI-less tenant, clear the launch keys and let the windows be rebuilt:
#
#   docker exec <c> redis-cli --scan --pattern '*:launch' | xargs -r docker exec -i <c> redis-cli DEL
#   docker exec <c> bash -lc 'TMUX_TMPDIR=… tmux kill-window -t <tenant>:<agent>'
#   bash container/plumbing-check.sh
#
# ⚠ Give the tenant a few seconds to settle first. The first run straight after
# --force-recreate can fail a check while windows are still being created; three
# consecutive runs on a settled tenant are clean.
#
# ⚠ A pasted message is executed by the shell in a CLI-less window, so
# "command not found" in a pane is the expected result and not a failure — the
# check is that the text arrived at all.
# Pod, tenant and container name come from container/.env — the same file the
# tenant was built from — rather than being hardcoded here. setup.sh names the
# compose project "h-flock-<tenant>", so the container is "<project>-tenant-1".
# Override either by exporting POD/TENANT, or by passing the container name.
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ⚠ Hold anything already exported. Sourcing .env would otherwise overwrite it,
# so the documented `POD=… TENANT=… bash plumbing-check.sh` override silently
# checked the wrong tenant — measured while checking a disposable one.
_pod="${POD:-}"; _tenant="${TENANT:-}"
[ -f "$_here/.env" ] && . "$_here/.env"
POD="${_pod:-${POD:-acme}}"
TENANT="${_tenant:-${TENANT:-hq}}"
C="${CONTAINER:-h-flock-${TENANT}-tenant-1}"
ROSTER="pod:$POD:tenant:$TENANT:roster"
T=$(docker exec $C printenv API_TOKEN)
# Agent names come from the roster, not from this file. The default tenant is
# architect/sme-2/sme-3 and any real one is named for its jobs, so hardcoding
# two names makes the check work on exactly one office.
read -r AG1 AG2 <<<"$(docker exec $C redis-cli --no-raw HGETALL $ROSTER \
  | paste - - | grep '"tmux"' | awk -F'"' '{print $2}' | sort | head -2 | tr '\n' ' ')"
[ -n "${AG1:-}" ] && [ -n "${AG2:-}" ] || { echo "plumbing-check: need two tmux agents in the roster" >&2; exit 2; }
echo "using agents: $AG1 (sender) and $AG2 (destination)"

H="Authorization: Bearer $T"
dx() { docker exec "$C" "$@"; }
cu() { dx curl -sk -H "$H" "$@"; }
# ⚠ The door speaks TLS when certs are configured, so the scheme is not a
# constant — and this must come AFTER dx() exists. Placed above it, the probe
# silently found nothing, every call went to http against an HTTPS listener, and
# fourteen checks failed with empty output that looked like a broken door.
if [ -n "$(dx printenv API_TLS_CERT 2>/dev/null)" ]; then A="https://127.0.0.1:8080"; else A="http://127.0.0.1:8080"; fi

# ⚠ Placed after dx(), like the probe above. Written above it first, where it
# silently measured nothing and let the run proceed — the same ordering mistake
# this file already carries a comment about.
# ⚠ Refuse a tenant whose windows run real agents, unless told twice.
#
# This check enrols a client called `telegram`, sends a message as it, and
# pastes text into panes. In a CLI-less tenant those land in a shell and the
# worst case is "command not found". In a live one they land as *prompts to a
# working agent*, which then acts on them — and the fixture client is removed in
# teardown, so the agent chases a route that no longer resolves.
#
# Measured twice, the second time on an operator's own laptop: alice spent her
# turn retesting `office send -a telegram` and reporting that it would not
# resolve, because of a message this script had invented.
live=$(dx redis-cli --scan --pattern "pod:$POD:tenant:$TENANT:agent:*:launch" 2>/dev/null | tr -d '\r' | wc -l | tr -d ' ')
if [ "${live:-0}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "plumbing-check: $live agent(s) in tenant '$TENANT' run a CLI, not a shell." >&2
  echo "  This check pastes fixtures into panes and enrols a fake 'telegram' client," >&2
  echo "  which a live agent will read as real work. Bring the tenant up with a" >&2
  echo "  CLI-less roster, or re-run with FORCE=1 if this tenant is disposable." >&2
  exit 2
fi
pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : expected [$3] got [$2]"; fail=$((fail+1)); fi; }
ckc() { if echo "$2" | grep -q "$3"; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : [$2] lacks [$3]"; fail=$((fail+1)); fi; }

# Fixed sleeps followed by assertions are load-dependent gates. Every converted
# gate uses this wall-clock deadline and can be falsified by withholding only
# its own trigger. Negative-control runs exit 97 at the expected deadline so a
# different failure cannot masquerade as proof that the poll went red.
GATE_DEADLINE_SECONDS="${GATE_DEADLINE_SECONDS:-15}"
NEGATIVE_GATE="${NEGATIVE_GATE:-}"
GATE_RUN_TAG="${GATE_RUN_TAG:-$$}"
gate_skip() { [ "$NEGATIVE_GATE" = "$1" ]; }
gate_timeout() {
  local id="$1" label="$2" expected="$3" seen="$4"
  echo "  FAIL  $label : deadline ${GATE_DEADLINE_SECONDS}s expected [$expected] got [${seen:0:200}]"
  fail=$((fail+1))
  if [ "$NEGATIVE_GATE" = "$id" ]; then
    echo "NEGATIVE_CONTROL gate=$id deadline=${GATE_DEADLINE_SECONDS}s condition=absent"
    exit 97
  fi
  return 1
}
poll_contains() {
  local id="$1" label="$2" expected="$3"; shift 3
  local deadline=$(( $(date +%s) + GATE_DEADLINE_SECONDS )) seen=""
  while :; do
    seen="$("$@" 2>&1)"
    if grep -Fq -- "$expected" <<<"$seen"; then
      echo "  ok    $label"; pass=$((pass+1)); return 0
    fi
    [ "$(date +%s)" -ge "$deadline" ] && { gate_timeout "$id" "$label" "contains $expected" "$seen"; return; }
    sleep 0.1
  done
}
poll_equals() {
  local id="$1" label="$2" expected="$3"; shift 3
  local deadline=$(( $(date +%s) + GATE_DEADLINE_SECONDS )) seen=""
  while :; do
    seen="$("$@" 2>&1)"
    if [ "$seen" = "$expected" ]; then
      echo "  ok    $label"; pass=$((pass+1)); return 0
    fi
    [ "$(date +%s)" -ge "$deadline" ] && { gate_timeout "$id" "$label" "$expected" "$seen"; return; }
    sleep 0.1
  done
}

echo "== 1. doors =="
ckc "health"        "$(cu $A/health)" '"ok"'
ckc "agents list"   "$(cu $A/agents)" "$AG1"
ck  "no token 401"  "$(dx curl -sk -o /dev/null -w '%{http_code}' $A/agents)" "401"

echo "== 2. agent -> agent message =="
MESSAGE_MARKER="plumbing-check-42-$GATE_RUN_TAG"
gate_skip agent-message || dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office send -a $AG2 $MESSAGE_MARKER" >/dev/null 2>&1
poll_contains agent-message "pasted into $AG2" "$MESSAGE_MARKER" dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t $TENANT:$AG2 2>/dev/null"

echo "== 3. board =="
TICKET_MARKER="plumb-ticket-$GATE_RUN_TAG"
gate_skip board-ticket || dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office add -a $AG2 -t $TICKET_MARKER -d 'the brief'" >/dev/null 2>&1
poll_contains board-ticket "ticket on $AG2 todo" "$TICKET_MARKER" cu "$A/agents/$AG2/board"
ckc "board has hold col" "$(cu $A/agents/$AG2/board)" '"hold"'
ckc "$AG2 takes it"       "$(dx bash -lc "cd /workdir/$AG2 && AGENT_NAME=$AG2 office take" 2>&1)" "$TICKET_MARKER"
ckc "now in doing"       "$(cu $A/agents/$AG2/board)" '"doing":\['
ckc "task record file"   "$(dx bash -lc 'cat /home/ubuntu/.flock/tasks.jsonl 2>/dev/null | tail -2')" '"event"'
# ⚠ Finish it, or the next run finds $AG2 still holding one and `take` correctly
# refuses — a failing check that is the board working exactly as designed.
dx bash -lc "cd /workdir/$AG2 && AGENT_NAME=$AG2 office done" >/dev/null 2>&1

echo "== 4. app client =="
gate_skip client-enrolled || cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"telegram","port_type":"api"}}' $A/agents/host/envelopes >/dev/null
poll_equals client-enrolled "client enrolled" "api" dx redis-cli --raw HGET "$ROSTER" telegram
ck  "no window made"     "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT" | grep -c telegram)" "0"
ckc "peers hides client" "$(dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office peers")" "$AG2"
ck  "peers really hides" "$(dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office peers" | grep -c telegram)" "0"

echo "== 5. app -> agent, as itself =="
APP_MESSAGE="hello-from-telegram-$GATE_RUN_TAG"
gate_skip app-to-agent || cu -X POST -H 'Content-Type: application/json' -d "{\"text\":\"$APP_MESSAGE\",\"as\":\"telegram\"}" $A/agents/$AG1/envelopes >/dev/null
poll_contains app-to-agent "$AG1 sees app message" "$APP_MESSAGE" dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t $TENANT:$AG1"

echo "== 6. agent -> app, the return path =="
REPLY_MARKER="reply-from-$AG1-$GATE_RUN_TAG"
gate_skip agent-to-app || dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office send -a telegram $REPLY_MARKER" >/dev/null 2>&1
poll_contains agent-to-app "in the mailbox" "$REPLY_MARKER" cu "$A/agents/telegram/messages"
M="$(cu "$A/agents/telegram/messages")"
ckc "L2 source is $AG1" "$M" "\"source\": *\"$AG1\""
ckc "cursor present"    "$M" '"cursor"'

echo "== 7. cursor resume =="
CUR=$(echo "$M" | python3 -c "import sys,json;print(json.load(sys.stdin)['next_cursor'])")
ck "after=cursor is empty" "$(cu "$A/agents/telegram/messages?after=$CUR" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')" "0"
SECOND_MARKER="second-message-$GATE_RUN_TAG"
gate_skip cursor-resume || dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office send -a telegram $SECOND_MARKER" >/dev/null 2>&1
poll_contains cursor-resume "only the new one" "$SECOND_MARKER" cu "$A/agents/telegram/messages?after=$CUR"
ck  "and only one"     "$(cu "$A/agents/telegram/messages?after=$CUR" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')" "1"

echo "== 8. isolation between clients =="
gate_skip second-client || cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"webapp","port_type":"api"}}' $A/agents/host/envelopes >/dev/null
poll_equals second-client "second client enrolled" "api" dx redis-cli --raw HGET "$ROSTER" webapp
# ⚠ Isolation is "webapp did not get telegram's message", not "webapp's mailbox
# is empty". A raw broadcast to `all` reaches app clients too — documented
# behaviour — so an emptiness assertion fails for a correct system the moment
# anything broadcasts. It did.
ck "webapp did not get telegram's mail" \
   "$(cu $A/agents/webapp/messages?limit=1000 | grep -c "$REPLY_MARKER" || true)" "0"

# ⚠ Retire the fixtures. This suite enrols telegram and webapp and pastes a
# message into a live agent's window. Left behind, they sit in the operator's
# roster forever and the message reads as traffic from a client that does not
# exist — measured: the owner saw "[message from telegram] hello from the app"
# in his terminal and asked who sent it. A check that changes the office it
# checks must put it back.
for _fixture in telegram webapp; do
    cu -X POST -H 'Content-Type: application/json' \
       -d "{\"kind\":\"StopAgent\",\"payload\":{\"agent\":\"$_fixture\"}}" \
       $A/agents/host/envelopes >/dev/null
done

echo "== 9. lifecycle =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"dave"}}' $A/agents/host/envelopes >/dev/null
# StartAgent travels through the same asynchronous route as StopAgent. Poll both
# halves of this lifecycle check symmetrically: a fixed wait sampled 260 ms
# before window_created on a busy tenant and reported a healthy start as absent.
_deadline=$(( $(date +%s) + 15 ))
while [ "$(date +%s)" -lt "$_deadline" ]; do
    [ "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT" | grep -c dave)" = "1" ] && break
    sleep 0.1
done
ck "dave window exists" "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT" | grep -c dave)" "1"
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"dave"}}' $A/agents/host/envelopes >/dev/null
# ⚠ Poll, do not sleep a fixed interval. A StopAgent is an envelope: it is
# routed, kicked, and opened, so the kill lands whenever it lands. A fixed 4s
# passed for weeks and then failed on a busier tenant — the check was flaky, not
# the lifecycle.
_deadline=$(( $(date +%s) + 15 ))
while [ "$(date +%s)" -lt "$_deadline" ]; do
    [ "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT" | grep -c dave)" = "0" ] && break
    sleep 0.1
done
ck "dave window gone"   "$(dx bash -c "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT" | grep -c dave)" "0"

echo "== 10. dead-letter =="
# ⚠ Written straight onto an egress queue, deliberately. Both supported doors
# refuse an unknown destination before an envelope exists — the api returns 404 and
# `office send` errors with "unknown destination agent" — so neither can reach the
# switch's dead-letter path. This is a test of the ROUTER, so the envelope is
# placed where the switch pops from. Nothing in the product may do this.
DEAD_ENV="{\"v\":2,\"kind\":\"Message\",\"stream_id\":\"plumbingdead1\",\"correlation_id\":\"plumbingdead1\",\"ts\":\"2026-01-01T00:00:00.000Z\",\"l2\":{\"source\":\"$AG1\",\"destination\":\"ghost\"},\"l3\":{\"source\":\"$POD:$TENANT:$AG1\",\"destination\":\"$POD:$TENANT:ghost\"},\"payload\":{\"text\":\"nobody home\"}}"
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:$AG1:dead" >/dev/null
dx redis-cli RPUSH "pod:$POD:tenant:$TENANT:agent:$AG1:egress" "$DEAD_ENV" >/dev/null
_deadline=$(( $(date +%s) + 10 ))
while [ "$(date +%s)" -lt "$_deadline" ]; do
    [ "$(dx redis-cli LLEN "pod:$POD:tenant:$TENANT:agent:$AG1:dead" | tr -d '\r')" != "0" ] && break
    sleep 0.1
done
ckc "unroutable dead-lettered" "$(dx redis-cli KEYS "pod:$POD:tenant:$TENANT:agent:*:dead")" "dead"
dx redis-cli DEL "pod:$POD:tenant:$TENANT:agent:$AG1:dead" >/dev/null

echo "== 11. booted and hired agents get the same environment =="
# ⚠ The one check that would have caught the build 17 drift. Two code paths built
# a window environment, each was individually correct, each passed its own unit
# tests — only their EQUALITY was wrong, and nothing compared them. Comparing the
# two at the level where they actually differ is the whole point.
penv() { dx bash -c "tr '\0' '\n' < /proc/\$(TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-panes -t $TENANT:$1 -F '#{pane_pid}' | head -1)/environ" \
         | grep -E '^(OFFICE_TOOLS|AGENT_GUIDE|CLAUDE_CONFIG_DIR|CODEX_HOME)=' | sed "s|/$1|/<agent>|g" | sort; }
BOOT_ENV="$(penv "$AG1")"
gate_skip hired-environment || cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"envprobe"}}' $A/agents/host/envelopes >/dev/null
poll_equals hired-environment "hired env == booted env" "$BOOT_ENV" penv envprobe
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"envprobe"}}' $A/agents/host/envelopes >/dev/null

echo "== 12. failure simulator =="
if ! bash "$_here/sim-blocked.sh"; then
    echo "  FAIL  failure simulator reported failures"
    fail=$((fail+1))
fi

echo
echo "PASS=$pass FAIL=$fail"
exit "$fail"
