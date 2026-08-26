#!/usr/bin/env bash
# MANUAL INTEGRATION TOOL — NEVER WIRE INTO accept.sh OR AN AUTOMATED SUITE.
#
# This deliberately drives real local-model agents to originate adversarial
# multiline, Unicode, JSON, quoting, and backslash payloads, then captures AOF
# byte-opacity and source-stamp evidence. Model agency is the coverage: its
# nondeterministic 30-minute wait and participant-declared completion make it
# unsuitable for a gate. It intentionally emits no RESULT verdict.
set -uo pipefail

CONTAINER="${CONTAINER:?set CONTAINER}"
POD="${POD:-acme}"
TENANT="${TENANT:?set TENANT}"
AGENTS="${AGENTS:-b74-a b74-b b74-c}"
ROUNDS="${ROUNDS:-10}"
OUT="${1:?usage: tmux-nemotron.sh OUTPUT_DIR}"
mkdir -p "$OUT"
dx() { docker exec -i "$CONTAINER" "$@"; }
read -r -a list <<<"$AGENTS"

read_transport_depth() {
  dx python3 - "$POD" "$TENANT" <<'PY'
import os,sys,redis
pod,tenant=sys.argv[1:3]
r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0"))
print(sum(r.llen(k) for p in (f"pod:{pod}:tenant:{tenant}:agent:*:egress",f"pod:{pod}:tenant:{tenant}:agent:*:ingress") for k in r.scan_iter(match=p)))
PY
}

drain_transport() {
  local timeout="$1" interval="$2" deadline depth
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if ! depth="$(read_transport_depth)"; then
      echo "tmux-nemotron: incomplete reason=queue_depth_probe_failed" >&2
      return 100
    fi
    if ! [[ "$depth" =~ ^[0-9]+$ ]]; then
      printf 'tmux-nemotron: incomplete reason=unreadable_queue_depth value=%q\n' "$depth" >&2
      return 100
    fi
    [ "$depth" -eq 0 ] && return 0
    sleep "$interval"
  done
  echo "tmux-nemotron: drain_timeout depth=$depth" >&2
  # ⚠ This rc0 is inherited and is not the final contract: a non-drained queue
  # makes the snapshot incomplete because in-transit frames can look lost. The
  # fix must NOT return 100 here, which would skip the evidence below. Instead,
  # preserve final_depth, capture custody and AOF first, then emit incomplete
  # reason=drain_timeout depth=N and exit 100. That change needs an in-situ run.
  return 0
}

token="$(dx printenv API_TOKEN | tr -d '\r')"
api=http://127.0.0.1:8080
rm -f "$OUT"/*.done

echo "tmux-nemotron agents=${#list[@]} rounds=$ROUNDS capture=$OUT"
for i in "${!list[@]}"; do
  agent="${list[$i]}"
  next="${list[$(( (i + 1) % ${#list[@]} ))]}"
  prompt="Build 74 integration exercise. Send exactly $ROUNDS separate messages to $next. Compose every message yourself in your own words. Across them include multiline text, a fenced code block, double and single quotes, backslashes, Unicode, and JSON inside prose; do not simplify or escape them merely for this test. Keep every body out of shell parsing: write each exact body to a file, then send it with office send -a $next --file PATH, replacing PATH with that file's path. After all sends succeed, run: touch /workdir/$agent/build74.done"
  dx curl -sS -o /dev/null -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' -X POST \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"kind":"Message","payload":{"text":sys.argv[1]}}))' "$prompt")" \
    "$api/agents/$agent/envelopes"
done

# Completion is declared by the participants, not inferred from passive logs.
deadline=$((SECONDS + 1800))
while [ "$SECONDS" -lt "$deadline" ]; do
  done_count=0
  for agent in "${list[@]}"; do
    dx test -f "/workdir/$agent/build74.done" 2>/dev/null && done_count=$((done_count + 1))
  done
  [ "$done_count" = "${#list[@]}" ] && break
  sleep 5
done
echo "participants_done=${done_count:-0}/${#list[@]}"

# One deliberately misclaimed source proves fixed-offset stamping preserves body.
docker exec -i "$CONTAINER" python3 - "$POD" "$TENANT" "${list[0]}" "${list[1]}" <<'PY'
import os, sys
sys.path.insert(0, "/app/src")
import redis
from flock.bus import build, encode, prefix
pod, tenant, sender, destination = sys.argv[1:5]
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
frame = build("Message", "misclaimed", destination, {
    "text": "source-stamp body: ```json\n{\"quote\":\"\\\\ snowman ☃\"}\n```"
}, pod=pod, tenant=tenant)
r.rpush(prefix(pod, tenant, sender, "egress"), encode(frame))
print(frame["stream_id"])
PY

# Wait only on transport state. Custody logs remain unread until capture.
# An unreadable depth is not a non-empty queue: refuse rather than silently
# consuming the full deadline and then snapshotting an unknown transport state.
drain_transport 300 1 || exit "$?"
sleep 15

docker logs "$CONTAINER" >"$OUT/custody.log" 2>&1
docker cp "$CONTAINER:/tmp/appendonlydir" "$OUT/appendonlydir" >/dev/null
echo "captured custody_lines=$(wc -l <"$OUT/custody.log")"
