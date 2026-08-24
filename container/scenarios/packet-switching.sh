#!/usr/bin/env bash
set -uo pipefail
MODE=steady; COUNT=${COUNT:-10}; ROUNDS=${ROUNDS:-10}; WORK=""; RECONCILE_ONLY=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2;; --count) COUNT="$2"; shift 2;;
    --rounds) ROUNDS="$2"; shift 2;; --work) WORK="$2"; shift 2;;
    --reconcile-only) RECONCILE_ONLY="$2"; shift 2;;
    -h|--help) echo "packet-switching.sh [--mode steady|burst] [--count N] [--rounds N] [--work DIR] [--reconcile-only DIR]"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 100;;
  esac
done

judge() {
  python3 - "$1" <<'PY'
import collections, datetime, json, pathlib, subprocess, sys
d = pathlib.Path(sys.argv[1]); log = d / "custody.log"; sent = {}; opened = collections.Counter(); popped = {}; forwarded = {}; stages = collections.Counter(); ignored = 0
for line in log.read_text(errors="replace").splitlines():
    if not line.lstrip().startswith("{"): continue
    try: rec = json.loads(line)
    except Exception: continue
    sid = rec.get("stream_id")
    if not sid: continue
    own = any(str(rec.get(field, "")).startswith("bench-") for field in ("source", "destination"))
    if not own:
        ignored += 1
        continue
    stages[rec.get("event", "unknown")] += 1
    if rec.get("event") == "sent": sent[sid] = rec
    if rec.get("event") == "opened": opened[sid] += 1
    if rec.get("event") == "popped": popped[sid] = rec
    if rec.get("event") == "forwarded": forwarded[sid] = rec
stray = sorted(set(opened) - set(sent))
with (d / "ledger.tsv").open("w") as out:
    for n, rec in enumerate(sent.values(), 1):
        ts = datetime.datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
        print(n, rec["stream_id"], rec.get("source", ""), rec.get("destination", ""), ts, sep="\t", file=out)
for name in ("dead.jsonl", "ingress.jsonl", "injections.tsv"): (d / name).touch()
print(f"PACKET_BOUNDARY start=popped stop=forwarded outside=port,terminal,application")
print(f"PACKET_SCOPE source_or_destination_prefix=bench- ignored_out_of_scope={ignored}")
print(f"PACKET_COUNTS submitted={len(sent)} opened={sum(opened.values())} stray={len(stray)}")
print("PACKET_STAGES " + " ".join(f"{event}={stages[event]}" for event in ("sent", "popped", "forwarded", "received", "opened")))
pairs = []
for sid in sent:
    if sid in popped and sid in forwarded:
        a = datetime.datetime.fromisoformat(popped[sid]["ts"].replace("Z", "+00:00")).timestamp()
        b = datetime.datetime.fromisoformat(forwarded[sid]["ts"].replace("Z", "+00:00")).timestamp()
        pairs.append((a, b))
if pairs:
    span = max(b for _, b in pairs) - min(a for a, _ in pairs)
    rate = len(pairs) / span if span > 0 else 0.0
    print(f"PACKET_THROUGHPUT boundary=popped->forwarded envelopes={len(pairs)} seconds={span:.6f} rate={rate:.2f}")
else:
    print("PACKET_THROUGHPUT boundary=popped->forwarded envelopes=0 seconds=0 rate=0.00")
if stray:
    print(f"STRAY_OPENED {stray[0]}"); print("PACKET_RESULT rc=3 reason=stray"); raise SystemExit(3)
rc = subprocess.run(["python3", "container/scenarios/reconcile-unicast.py", str(d/"ledger.tsv"), str(log), str(d/"dead.jsonl"), str(d/"ingress.jsonl"), str(d/"injections.tsv")]).returncode
if rc == 0: print("PACKET_RESULT rc=0 reason=clean")
elif rc == 5: print("PACKET_RESULT rc=5 reason=indeterminate_forward")
else: print(f"PACKET_RESULT rc={rc} reason=conservation_failure")
raise SystemExit(rc)
PY
}

capture_diagnostics() {
  local rc="$1"
  [ "$rc" -eq 0 ] && return 0
  echo "PACKET_DIAGNOSTICS retaining work=$WORK"
  docker logs "$CONTAINER" >"$WORK/diagnostic-container.log" 2>&1 || true
  docker inspect "$CONTAINER" | python3 -c '
import json, re, sys
rows = json.load(sys.stdin)
secret = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CRED|AUTH", re.I)
for row in rows:
    env = row.get("Config", {}).get("Env") or []
    row.setdefault("Config", {})["Env"] = [
        (name + "=REDACTED" if "=" in item and secret.search((name := item.split("=", 1)[0])) else item)
        for item in env
    ]
json.dump(rows, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
' >"$WORK/diagnostic-inspect.json" 2>&1 || true
  docker exec "$CONTAINER" ps -ef >"$WORK/diagnostic-processes.txt" 2>&1 || true
  docker exec -e POD="$POD" -e TENANT="$TENANT" "$CONTAINER" python3 -c '
import json, os, redis
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
pattern = "pod:%s:tenant:%s:*" % (os.environ["POD"], os.environ["TENANT"])
for raw_key in sorted(r.scan_iter(match=pattern)):
    key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
    kind = r.type(raw_key).decode()
    if kind == "list": value = [x.decode(errors="replace") for x in r.lrange(raw_key, 0, -1)]
    elif kind == "hash": value = {k.decode(errors="replace"): v.decode(errors="replace") for k, v in r.hgetall(raw_key).items()}
    elif kind == "set": value = sorted(x.decode(errors="replace") for x in r.smembers(raw_key))
    elif kind == "string": value = (r.get(raw_key) or b"").decode(errors="replace")
    else: value = f"<unsupported redis type {kind}>"
    print(json.dumps({"key": key, "type": kind, "value": value}, sort_keys=True))
' >"$WORK/diagnostic-keyspace.jsonl" 2>&1 || true
  docker exec -e POD="$POD" -e TENANT="$TENANT" "$CONTAINER" python3 -c '
import os, redis
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
pattern = "pod:%s:tenant:%s:agent:*" % (os.environ["POD"], os.environ["TENANT"])
for raw_key in sorted(r.scan_iter(match=pattern)):
    key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
    if key.endswith(":ingress") or key.endswith(":egress"):
        print(f"{key}\t{r.llen(raw_key)}")
' >"$WORK/diagnostic-queues.tsv" 2>&1 || true
  # ⚠ Redis DELETES a list key when it empties, so a fully drained tenant has no
  # queue keys to report. An empty file here is the CORRECT answer, not a failed
  # capture — without this marker the validation below calls every non-zero run
  # `status=incomplete`. Found by `acceptance` in BUILD-115.
  [ -s "$WORK/diagnostic-queues.tsv" ] || printf '%s\n' 'NO_NONEMPTY_QUEUES: empty lists are deleted after drain' >"$WORK/diagnostic-queues.tsv"
  if docker exec "$CONTAINER" test -f /home/ubuntu/.flock/window.log.jsonl 2>/dev/null; then
    docker cp "$CONTAINER:/home/ubuntu/.flock/window.log.jsonl" "$WORK/diagnostic-window.log.jsonl" >/dev/null 2>&1 || true
  else
    printf '%s\n' 'NO_FLOCK_LOG_FILE: daemon records use stdout' >"$WORK/diagnostic-window.log.jsonl"
  fi
  local capture_ok=1 f
  for f in diagnostic-container.log diagnostic-inspect.json diagnostic-processes.txt \
      diagnostic-keyspace.jsonl diagnostic-queues.tsv diagnostic-window.log.jsonl; do
    if [ ! -s "$WORK/$f" ]; then
      capture_ok=0; echo "PACKET_DIAGNOSTICS missing=$f" >&2
      continue
    fi
    if grep -Eq 'Traceback \(most recent call last\):|No module named' "$WORK/$f"; then
      capture_ok=0; echo "PACKET_DIAGNOSTICS invalid=$f" >&2
    fi
  done
  sha256sum "$WORK"/diagnostic-* >"$WORK/diagnostic-sha256.txt" 2>&1 || capture_ok=0
  if [ "$capture_ok" = "1" ]; then
    echo "PACKET_DIAGNOSTICS status=complete files=diagnostic-container.log,diagnostic-inspect.json,diagnostic-processes.txt,diagnostic-keyspace.jsonl,diagnostic-queues.tsv,diagnostic-window.log.jsonl,diagnostic-sha256.txt"
  else
    echo "PACKET_DIAGNOSTICS status=incomplete" >&2
  fi
}

if [ -n "$RECONCILE_ONLY" ]; then
  [ -d "$RECONCILE_ONLY" ] || { echo "INCOMPLETE: fixture directory missing" >&2; exit 100; }
  judge "$RECONCILE_ONLY"; exit $?
fi
[ -n "${CONTAINER:-}" ] && [ -n "${TENANT:-}" ] || { echo "INCOMPLETE: CONTAINER and TENANT are required" >&2; exit 100; }
[ "$MODE" = steady ] || [ "$MODE" = burst ] || { echo "INCOMPLETE: invalid mode" >&2; exit 100; }
WORK="${WORK:-/tmp/packet-switching-$TENANT}"; mkdir -p "$WORK"
restore_kick() { if ! docker exec "$CONTAINER" sh -c 'p=$(cat /tmp/flock.port.path); cp /tmp/flock.port.real "$p"; test "$(wc -c < "$p")" -gt 20' >/dev/null 2>&1; then echo 'ERROR: flock.port restore failed' >&2; exit 125; fi; }
trap restore_kick EXIT
docker exec "$CONTAINER" sh -c 'p=$(command -v flock.port); cp "$p" /tmp/flock.port.real; printf "#!/bin/sh\nexit 0\n" > "$p"; chmod +x "$p"; echo "$p" >/tmp/flock.port.path'
docker cp "$(dirname "$0")/bench-port.py" "$CONTAINER:/tmp/build114-bench-port.py" >/dev/null || { echo "INCOMPLETE: receiver copy" >&2; exit 100; }
docker cp "$(dirname "$0")/bench-send.py" "$CONTAINER:/tmp/bench-send.py" >/dev/null || { echo "INCOMPLETE: sender copy" >&2; exit 100; }
docker exec "$CONTAINER" redis-cli HSET "pod:${POD:-acme}:tenant:$TENANT:roster" $(printf 'bench-%s api ' $(seq 1 "$COUNT")) >/dev/null 2>&1 || { echo "INCOMPLETE: roster seed" >&2; exit 100; }
names="$(printf 'bench-%s ' $(seq 1 "$COUNT") | sed 's/[[:space:]]*$//')"
receiver="python3 /tmp/build114-bench-port.py --pod '${POD:-acme}' --tenant '$TENANT' --count '$COUNT' --prefix bench- --idle-exit 8 >>/proc/1/fd/1 2>&1 &"
[ "$MODE" = steady ] && docker exec "$CONTAINER" sh -c "$receiver"
docker exec "$CONTAINER" sh -c "python3 /tmp/bench-send.py --pod '${POD:-acme}' --tenant '$TENANT' --count '$COUNT' --rounds '$ROUNDS' --names '$names' >>/proc/1/fd/1 2>&1" || { echo "INCOMPLETE: sender" >&2; exit 100; }
[ "$MODE" = burst ] && docker exec "$CONTAINER" sh -c "$receiver"
drained=0; depth=1
for _ in $(seq 1 120); do
  depth=$(docker exec "$CONTAINER" python3 -c "
import os, redis
r = redis.Redis.from_url(os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0'))
print(sum(r.llen(k) for k in r.scan_iter(match='pod:${POD:-acme}:tenant:${TENANT}:agent:*:ingress')) +
      sum(r.llen(k) for k in r.scan_iter(match='pod:${POD:-acme}:tenant:${TENANT}:agent:*:egress')))
" 2>/dev/null | tr -d '\r' || echo 1)
  [ "${depth:-1}" = "0" ] && { drained=1; break; }
  sleep 1
done
echo "PACKET_QUEUE_DEPTH ingress_plus_egress=${depth:-unknown} drained=${drained}"
docker logs "$CONTAINER" >"$WORK/custody.log" 2>&1 || { echo "INCOMPLETE: capture" >&2; exit 100; }
[ -s "$WORK/custody.log" ] || { echo "INCOMPLETE: empty capture" >&2; exit 100; }
[ "$drained" = "1" ] || { echo "INCOMPLETE: queues did not drain before capture" >&2; capture_diagnostics 100; exit 100; }
judge "$WORK"; rc=$?
capture_diagnostics "$rc"
exit "$rc"
