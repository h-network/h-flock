#!/usr/bin/env bash
# soak.sh — run a tenant for hours under steady traffic and sample what grows.
#
#   CONTAINER=h-flock-soak-tenant-1 POD=acme TENANT=soak \
#   HOURS=6 bash container/scenarios/soak.sh | tee /tmp/soak.log
#
# ⚠ **Three audit findings lived here and none of them fire in a five-minute
# test**: the activity tailer replaying a whole file when the newest session
# changes, the window-log spool re-emitting forever on one undecodable byte, and
# presence reading 1000 stream entries per agent per pass. All three were found
# by reading. This is the instrument that would have found them by running.
#
# ⚠ **It prints samples, not verdicts.** Growth is not automatically a defect —
# a stream that grows to its cap and stops is correct. What matters is the
# SHAPE over time, which a human reads at the end. A script asserting "memory
# must not grow" would fail on a healthy tenant warming up.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
HOURS="${HOURS:-6}"
EVERY="${EVERY:-300}"          # sample period, seconds
SEND_EVERY="${SEND_EVERY:-20}" # traffic period, seconds

P="pod:${POD}:tenant:${TENANT}"
dx() { docker exec "$CONTAINER" "$@"; }
r() { dx redis-cli "$@" 2>/dev/null | tr -d '\r'; }

# ⚠ REFUSE A TENANT WHOSE AGENTS RUN A CLI. Every message this script sends
# wakes a real model and spends the operator's subscription. Measured: eight
# hours at one message per twenty seconds is ~1,440 model turns, to observe
# Redis stream lengths and RSS — none of which needs a model at all.
#
# I started exactly that run before the operator stopped it. A duration test
# belongs on a tenant of plain shells: the bus, switch, adapter, spool, presence
# sampler and session door are all exercised identically, and the paste lands in
# bash instead of a CLI.
live=$(dx redis-cli --scan --pattern "$P:agent:*:launch" 2>/dev/null | tr -d '\r' | wc -l | tr -d ' ')
if [ "${live:-0}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "soak: $live agent(s) in '$TENANT' run a CLI, not a shell." >&2
  echo "  This script sends a message every ${SEND_EVERY}s for ${HOURS}h — every one" >&2
  echo "  of them a model turn on somebody's account. Bring up a CLI-less tenant:" >&2
  echo "    docker exec <c> redis-cli --scan --pattern '*:launch' | xargs -r -n1 docker exec -i <c> redis-cli DEL" >&2
  echo "    docker exec <c> bash -lc 'TMUX_TMPDIR=… tmux kill-window -t <tenant>:<agent>'   # tmuxhost rebuilds it as a shell" >&2
  echo "  or set FORCE=1 if you genuinely mean to spend that." >&2
  exit 2
fi

read -r AG1 AG2 <<<"$(dx redis-cli --no-raw HGETALL "$P:roster" 2>/dev/null \
  | paste - - | grep '"tmux"' | awk -F'"' '{print $2}' | sort | head -2 | tr '\n' ' ')"
[ -n "${AG1:-}" ] || { echo "soak: no tmux agents in $P:roster" >&2; exit 2; }

echo "soak: $CONTAINER  tenant=$TENANT  agents=$AG1,$AG2  hours=$HOURS"
echo "soak: sampling every ${EVERY}s, one message every ${SEND_EVERY}s"
echo

# Traffic, in the background: ordinary agent-to-agent messages, the thing a real
# office does all day. Not a load test — a *duration* test.
( while :; do
    dx bash -lc "cd /workdir/$AG1 && AGENT_NAME=$AG1 office send -a $AG2 'soak $(date +%s)'" >/dev/null 2>&1
    sleep "$SEND_EVERY"
  done ) &
TRAFFIC=$!
trap 'kill $TRAFFIC 2>/dev/null' EXIT INT TERM

printf '%-9s %-8s %-9s %-9s %-9s %-10s %-10s %-8s\n' \
  elapsed activity alerts inbox logspool rss_router rss_session redis_kb

START=$(date +%s)
END=$(( START + HOURS * 3600 ))
while [ "$(date +%s)" -lt "$END" ]; do
  NOW=$(( $(date +%s) - START ))
  ACT=$(r XLEN "$P:agent:$AG2:activity")
  ALERTS=$(r XLEN "$P:alerts")
  INBOX=$(r XLEN "$P:agent:api:inbox")
  SPOOL=$(dx bash -lc 'ls -l /home/ubuntu/.flock/*.log 2>/dev/null | awk "{s+=\$5} END {print s+0}"' 2>/dev/null | tr -d '\r')
  RSS_R=$(dx bash -lc "ps -o rss= -C python3 2>/dev/null | sort -rn | head -1" 2>/dev/null | tr -d ' \r')
  RSS_S=$(dx bash -lc "ps -o rss=,args= -C python3 2>/dev/null | grep flock.session | awk '{print \$1}'" 2>/dev/null | tr -d ' \r')
  RKB=$(r INFO memory | grep '^used_memory:' | cut -d: -f2 | awk '{printf "%d", $1/1024}')
  printf '%-9s %-8s %-9s %-9s %-9s %-10s %-10s %-8s\n' \
    "${NOW}s" "${ACT:-?}" "${ALERTS:-?}" "${INBOX:-?}" "${SPOOL:-?}" "${RSS_R:-?}" "${RSS_S:-?}" "${RKB:-?}"
  sleep "$EVERY"
done

echo
echo "soak: finished after ${HOURS}h. Read the shape, not any single row:"
echo "  - a stream that rises to its cap and flattens is correct"
echo "  - a spool that grows without bound, or never truncates, is not"
echo "  - RSS that climbs steadily with no plateau is the session door leaking"
echo "  - presence cost shows up as redis_kb and CPU, not as a stream length"
