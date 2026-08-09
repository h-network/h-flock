#!/usr/bin/env bash
# Plumbing check — the bus, boards, both doors and lifecycle, against a running
# tenant. No CLIs: bring the tenant up with AGENT_CLIS= so every window is a
# plain shell, and what is under test is h-flock rather than an agent's judgement.
#
#   AGENT_CLIS= docker compose -p h-flock-hq up -d --force-recreate
#   bash container/plumbing-check.sh
#
# ⚠ A pasted message is executed by the shell in a CLI-less window, so
# "command not found" in a pane is the expected result and not a failure — the
# check is that the text arrived at all.
C=h-flock-hq-tenant-1
T=$(docker exec $C printenv API_TOKEN)
A="http://127.0.0.1:8080"
H="Authorization: Bearer $T"
dx() { docker exec "$C" "$@"; }
cu() { dx curl -s -H "$H" "$@"; }
pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : expected [$3] got [$2]"; fail=$((fail+1)); fi; }
ckc() { if echo "$2" | grep -q "$3"; then echo "  ok    $1"; pass=$((pass+1)); else echo "  FAIL  $1 : [$2] lacks [$3]"; fail=$((fail+1)); fi; }

echo "== 1. doors =="
ckc "health"        "$(cu $A/health)" '"ok"'
ckc "agents list"   "$(cu $A/agents)" 'alice'
ck  "no token 401"  "$(dx curl -s -o /dev/null -w '%{http_code}' $A/agents)" "401"

echo "== 2. agent -> agent message =="
dx bash -lc "cd /workdir/alice && AGENT_NAME=alice office send -a bob plumbing-check-42" >/dev/null 2>&1
sleep 3
ckc "pasted into bob" "$(dx bash -c 'TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t hq:bob 2>/dev/null | grep -v \"^$\"')" "plumbing-check-42"

echo "== 3. board =="
dx bash -lc "cd /workdir/alice && AGENT_NAME=alice office add -a bob -t plumb-ticket -d 'the brief'" >/dev/null 2>&1
sleep 3
ckc "ticket on bob todo" "$(cu $A/agents/bob/board)" "plumb-ticket"
ckc "board has hold col" "$(cu $A/agents/bob/board)" '"hold"'
ckc "bob takes it"       "$(dx bash -lc 'cd /workdir/bob && AGENT_NAME=bob office take' 2>&1)" "plumb-ticket"
ckc "now in doing"       "$(cu $A/agents/bob/board)" '"doing":\['
ckc "task record file"   "$(dx bash -lc 'cat /home/ubuntu/.flock/tasks.jsonl 2>/dev/null | tail -2')" '"event"'
# ⚠ Finish it, or the next run finds bob still holding one and `take` correctly
# refuses — a failing check that is the board working exactly as designed.
dx bash -lc 'cd /workdir/bob && AGENT_NAME=bob office done' >/dev/null 2>&1

echo "== 4. app client =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"telegram","vab":"api"}}' $A/agents/host/envelopes >/dev/null
sleep 3
ckc "client enrolled"    "$(dx redis-cli HGET pod:acme:tenant:hq:roster telegram)" "api"
ck  "no window made"     "$(dx bash -c 'TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t hq' | grep -c telegram)" "0"
ckc "peers hides client" "$(dx bash -lc 'cd /workdir/alice && AGENT_NAME=alice office peers')" "bob"
ck  "peers really hides" "$(dx bash -lc 'cd /workdir/alice && AGENT_NAME=alice office peers' | grep -c telegram)" "0"

echo "== 5. app -> agent, as itself =="
cu -X POST -H 'Content-Type: application/json' -d '{"text":"hello from the app","as":"telegram"}' $A/agents/carol/envelopes >/dev/null
sleep 3
ckc "carol sees client name" "$(dx bash -c 'TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux capture-pane -p -t hq:carol | grep -v \"^$\"')" "message from telegram"

echo "== 6. agent -> app, the return path =="
dx bash -lc "cd /workdir/carol && AGENT_NAME=carol office send -a telegram reply-from-carol-99" >/dev/null 2>&1
sleep 3
M="$(cu "$A/agents/telegram/messages")"
ckc "in the mailbox"   "$M" "reply-from-carol-99"
ckc "producer is carol" "$M" '"producer": *"carol"'
ckc "cursor present"    "$M" '"cursor"'

echo "== 7. cursor resume =="
CUR=$(echo "$M" | python3 -c "import sys,json;print(json.load(sys.stdin)['next_cursor'])")
ck "after=cursor is empty" "$(cu "$A/agents/telegram/messages?after=$CUR" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')" "0"
dx bash -lc "cd /workdir/carol && AGENT_NAME=carol office send -a telegram second-message-77" >/dev/null 2>&1
sleep 3
ckc "only the new one" "$(cu "$A/agents/telegram/messages?after=$CUR")" "second-message-77"
ck  "and only one"     "$(cu "$A/agents/telegram/messages?after=$CUR" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')" "1"

echo "== 8. isolation between clients =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"webapp","vab":"api"}}' $A/agents/host/envelopes >/dev/null
sleep 3
ck "webapp mailbox empty" "$(cu $A/agents/webapp/messages | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')" "0"

echo "== 9. lifecycle =="
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"dave"}}' $A/agents/host/envelopes >/dev/null
sleep 5
ck "dave window exists" "$(dx bash -c 'TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t hq' | grep -c dave)" "1"
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"dave"}}' $A/agents/host/envelopes >/dev/null
sleep 4
ck "dave window gone"   "$(dx bash -c 'TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t hq' | grep -c dave)" "0"

echo "== 10. dead-letter =="
cu -X POST -H 'Content-Type: application/json' -d '{"text":"nobody home"}' $A/agents/ghost/envelopes >/dev/null
sleep 2
ckc "unroutable dead-lettered" "$(dx docker logs 2>/dev/null || true; dx redis-cli KEYS 'pod:acme:tenant:hq:agent:*:dead')" "dead"

echo "== 11. booted and hired agents get the same environment =="
# ⚠ The one check that would have caught the build 17 drift. Two code paths built
# a window environment, each was individually correct, each passed its own unit
# tests — only their EQUALITY was wrong, and nothing compared them. Comparing the
# two at the level where they actually differ is the whole point.
penv() { dx bash -c "tr '\0' '\n' < /proc/\$(TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-panes -t hq:$1 -F '#{pane_pid}' | head -1)/environ" \
         | grep -E '^(OFFICE_TOOLS|AGENT_GUIDE|CLAUDE_CONFIG_DIR|CODEX_HOME)=' | sed "s|/$1|/<agent>|g" | sort; }
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StartAgent","payload":{"agent":"envprobe"}}' $A/agents/host/envelopes >/dev/null
sleep 6
ck "hired env == booted env" "$(penv envprobe)" "$(penv alice)"
cu -X POST -H 'Content-Type: application/json' -d '{"kind":"StopAgent","payload":{"agent":"envprobe"}}' $A/agents/host/envelopes >/dev/null

echo
echo "PASS=$pass FAIL=$fail"
