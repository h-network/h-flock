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
d = pathlib.Path(sys.argv[1]); log = d / "custody.log"; sent = {}; opened = collections.Counter(); popped = {}; forwarded = {}
for line in log.read_text(errors="replace").splitlines():
    if not line.lstrip().startswith("{"): continue
    try: rec = json.loads(line)
    except Exception: continue
    sid = rec.get("stream_id")
    if not sid: continue
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
print(f"PACKET_COUNTS submitted={len(sent)} opened={sum(opened.values())} stray={len(stray)}")
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

if [ -n "$RECONCILE_ONLY" ]; then
  [ -d "$RECONCILE_ONLY" ] || { echo "INCOMPLETE: fixture directory missing" >&2; exit 100; }
  judge "$RECONCILE_ONLY"; exit $?
fi
[ -n "${CONTAINER:-}" ] && [ -n "${TENANT:-}" ] || { echo "INCOMPLETE: CONTAINER and TENANT are required" >&2; exit 100; }
[ "$MODE" = steady ] || [ "$MODE" = burst ] || { echo "INCOMPLETE: invalid mode" >&2; exit 100; }
WORK="${WORK:-/tmp/packet-switching-$TENANT}"; mkdir -p "$WORK"
docker cp "$(dirname "$0")/bench-port.py" "$CONTAINER:/tmp/build114-bench-port.py" >/dev/null || { echo "INCOMPLETE: receiver copy" >&2; exit 100; }
docker cp "$(dirname "$0")/bench-send.py" "$CONTAINER:/tmp/bench-send.py" >/dev/null || { echo "INCOMPLETE: sender copy" >&2; exit 100; }
docker exec "$CONTAINER" redis-cli HSET "pod:${POD:-acme}:tenant:$TENANT:roster" $(printf 'bench-%s api ' $(seq 1 "$COUNT")) >/dev/null 2>&1 || { echo "INCOMPLETE: roster seed" >&2; exit 100; }
names="$(printf 'bench-%s ' $(seq 1 "$COUNT") | sed 's/[[:space:]]*$//')"
receiver="python3 /tmp/build114-bench-port.py --pod '${POD:-acme}' --tenant '$TENANT' --count '$COUNT' --prefix bench- --idle-exit 8 >>/proc/1/fd/1 2>&1 &"
[ "$MODE" = steady ] && docker exec "$CONTAINER" sh -c "$receiver"
docker exec "$CONTAINER" sh -c "python3 /tmp/bench-send.py --pod '${POD:-acme}' --tenant '$TENANT' --count '$COUNT' --rounds '$ROUNDS' --names '$names' >>/proc/1/fd/1 2>&1" || { echo "INCOMPLETE: sender" >&2; exit 100; }
[ "$MODE" = burst ] && docker exec "$CONTAINER" sh -c "$receiver"
sleep 10; docker logs "$CONTAINER" >"$WORK/custody.log" 2>&1 || { echo "INCOMPLETE: capture" >&2; exit 100; }
[ -s "$WORK/custody.log" ] || { echo "INCOMPLETE: empty capture" >&2; exit 100; }
judge "$WORK"; exit $?
