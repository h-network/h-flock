#!/usr/bin/env bash
set -uo pipefail
COUNT=${COUNT:-2}; ROUNDS=${ROUNDS:-10}; PREFIX=payload-; WORK=${WORK:-/tmp/payload-ack-${TENANT:-run}}
while [ "$#" -gt 0 ]; do case "$1" in --count) COUNT=$2; shift 2;; --rounds) ROUNDS=$2; shift 2;; --work) WORK=$2; shift 2;; *) echo "INCOMPLETE: unknown option" >&2; exit 100;; esac; done
[ -n "${CONTAINER:-}" ] && [ -n "${TENANT:-}" ] || { echo "INCOMPLETE: CONTAINER and TENANT required" >&2; exit 100; }
mkdir -p "$WORK"
# ⚠ The switch kicks `flock.port` on EVERY forward for ANY roster member
# (Switch._kick -> subprocess.Popen), so a real port spawns for our payload-*
# participants and races payload-ack-port.py for the same ingress. Prepending to
# OUR PATH does nothing: the switch resolves the name with ITS OWN path. The shim
# must replace the executable the switch actually finds. Restored on exit.
restore_kick() { if ! docker exec "$CONTAINER" sh -c 'p=$(cat /tmp/flock.port.path); cp /tmp/flock.port.real "$p"; test "$(wc -c < "$p")" -gt 20' >/dev/null 2>&1; then echo 'ERROR: flock.port restore failed' >&2; exit 125; fi; }
trap restore_kick EXIT
docker exec "$CONTAINER" sh -c 'p=$(command -v flock.port); cp "$p" /tmp/flock.port.real; printf "#!/bin/sh\nexit 0\n" > "$p"; chmod +x "$p"; echo "$p" >/tmp/flock.port.path'
docker cp "$(dirname "$0")/payload-ack-port.py" "$CONTAINER:/tmp/payload-ack-port.py" >/dev/null || exit 100
docker exec "$CONTAINER" redis-cli HSET "pod:${POD:-acme}:tenant:$TENANT:roster" $(printf 'payload-%s api ' $(seq 1 "$COUNT")) >/dev/null || exit 100
names="$(printf 'payload-%s ' $(seq 1 "$COUNT") | sed 's/[[:space:]]*$//')"
docker exec "$CONTAINER" sh -c "python3 /tmp/payload-ack-port.py --pod '${POD:-acme}' --tenant '$TENANT' --count '$COUNT' --prefix '$PREFIX' --idle-exit 120 >>/proc/1/fd/1 2>&1 &"
docker cp "$(dirname "$0")/bench-send.py" "$CONTAINER:/tmp/payload-send.py" >/dev/null || exit 100
docker exec "$CONTAINER" sh -c "python3 - '$names' '$ROUNDS' '${POD:-acme}' '$TENANT' <<'PY' >>/proc/1/fd/1
import hashlib, os, sys
sys.path.insert(0, '/app/src')
import redis
from flock.bus.doors import send
from flock.bus.logging import log_record
names=sys.argv[1].split(); rounds=int(sys.argv[2]); pod=sys.argv[3]; tenant=sys.argv[4]; r=redis.Redis.from_url(os.environ.get('REDIS_URL','redis://127.0.0.1:6379/0'))
for rnd in range(rounds):
  for i, source in enumerate(names):
    marker=f'payload-{rnd}-{i}-{source}'; sid=send(r,pod=pod,tenant=tenant,source=source,destination=names[(i+1)%len(names)],kind='Message',payload={'marker':marker,'checksum':hashlib.sha256(marker.encode()).hexdigest()}); log_record('payload-send','payload_sent',stream_id=sid,source=source,destination=names[(i+1)%len(names)])
PY"
capture_diagnostics() {
  local rc="$1"; [ "$rc" -eq 0 ] && return 0
  echo "PAYLOAD_DIAGNOSTICS retaining work=$WORK"
  docker logs "$CONTAINER" >"$WORK/diagnostic-container.log" 2>&1 || true
  docker inspect "$CONTAINER" | python3 -c 'import json,re,sys; rows=json.load(sys.stdin); p=re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CRED|AUTH",re.I); [row.setdefault("Config",{}).__setitem__("Env",[(x.split("=",1)[0]+"=REDACTED" if "=" in x and p.search(x.split("=",1)[0]) else x) for x in (row.get("Config",{}).get("Env") or [])]) for row in rows]; json.dump(rows,sys.stdout)' >"$WORK/diagnostic-inspect.json" 2>&1 || true
  docker exec "$CONTAINER" ps -ef >"$WORK/diagnostic-processes.txt" 2>&1 || true
  docker exec -e POD="${POD:-acme}" -e TENANT="$TENANT" "$CONTAINER" python3 -c 'import json,os,redis; r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0")); p="pod:%s:tenant:%s:*"%(os.environ["POD"],os.environ["TENANT"]); [print(json.dumps({"key":(k.decode() if isinstance(k,bytes) else k),"type":r.type(k).decode()})) for k in sorted(r.scan_iter(match=p))]' >"$WORK/diagnostic-keyspace.jsonl" 2>&1 || true
  docker exec -e POD="${POD:-acme}" -e TENANT="$TENANT" "$CONTAINER" python3 -c 'import os,redis; r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0")); p="pod:%s:tenant:%s:agent:*"%(os.environ["POD"],os.environ["TENANT"]); [print(f"{k.decode() if isinstance(k,bytes) else k}\t{r.llen(k)}") for k in sorted(r.scan_iter(match=p)) if (k.decode() if isinstance(k,bytes) else k).endswith((":ingress",":egress"))]' >"$WORK/diagnostic-queues.tsv" 2>&1 || true
  [ -s "$WORK/diagnostic-queues.tsv" ] || printf '%s\n' 'NO_NONEMPTY_QUEUES: empty lists are deleted after drain' >"$WORK/diagnostic-queues.tsv"
  if docker exec "$CONTAINER" test -f /home/ubuntu/.flock/window.log.jsonl 2>/dev/null; then
    docker cp "$CONTAINER:/home/ubuntu/.flock/window.log.jsonl" "$WORK/diagnostic-window.log.jsonl" >/dev/null 2>&1 || true
  else
    printf '%s\n' 'NO_FLOCK_LOG_FILE: daemon records use stdout' >"$WORK/diagnostic-window.log.jsonl"
  fi
  local ok=1 f; for f in diagnostic-container.log diagnostic-inspect.json diagnostic-processes.txt diagnostic-keyspace.jsonl diagnostic-queues.tsv diagnostic-window.log.jsonl; do [ -s "$WORK/$f" ] || ok=0; grep -Eq 'Traceback \(most recent call last\):|No module named' "$WORK/$f" 2>/dev/null && ok=0; done
  sha256sum "$WORK"/diagnostic-* >"$WORK/diagnostic-sha256.txt" 2>&1 || ok=0
  [ "$ok" = 1 ] && echo "PAYLOAD_DIAGNOSTICS status=complete" || echo "PAYLOAD_DIAGNOSTICS status=incomplete" >&2
}
drained=0
for _ in $(seq 1 120); do depth=$(docker exec "$CONTAINER" redis-cli --scan --pattern "pod:${POD:-acme}:tenant:${TENANT}:agent:payload-*:ingress" | wc -l | tr -d ' '); [ "$depth" = 0 ] && { drained=1; break; }; sleep 1; done
docker logs "$CONTAINER" >"$WORK/custody.log" 2>&1 || exit 100; [ -s "$WORK/custody.log" ] || exit 100
[ "$drained" = 1 ] || { echo "PAYLOAD_RESULT rc=100 reason=queues_not_drained"; capture_diagnostics 100; exit 100; }
# Wait for the expected ACK observations, but keep the bound: a missing ACK is
# unknown, never a proven loss.
expected=$((COUNT * ROUNDS)); ack_deadline=120; ack_ready=0
for _ in $(seq 1 "$ack_deadline"); do
  docker logs "$CONTAINER" >"$WORK/custody.poll.log" 2>/dev/null || true
  got=$(python3 "$(dirname "$0")/payload-ack-judge.py" "$WORK/custody.poll.log" --ack-count 2>/dev/null || printf 0)
  [ "$got" -ge "$expected" ] && { ack_ready=1; break; }
  sleep 1
done
wait_timed_out=0
if [ "$ack_ready" -ne 1 ]; then
  wait_timed_out=1
  echo "PAYLOAD_WAIT reason=ack_leg_unknown_timeout expected=$expected observed=$got" >&2
fi
docker logs "$CONTAINER" >"$WORK/custody.log" 2>&1 || exit 100
python3 "$(dirname "$0")/payload-ack-judge.py" "$WORK/custody.log"
rc=$?
[ "$rc" -eq 0 ] || capture_diagnostics "$rc"
exit "$rc"
