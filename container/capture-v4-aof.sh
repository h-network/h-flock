#!/usr/bin/env bash
# Produce a real Redis AOF from deterministic bus traffic, then judge it.
#
#   CONTAINER=h-flock-<tenant>-tenant-1 TENANT=<tenant> \
#     bash container/capture-v4-aof.sh OUTPUT_DIR
#
# Run only against a fresh disposable tenant: analyse-v4-aof judges every v4
# frame in the captured AOF, so pre-existing tenant traffic would be outside the
# capture universe. packet-switching supplies a run-unique participant prefix
# and an independent envelope count; no model or interactive pane is involved.
set -uo pipefail

CONTAINER="${CONTAINER:-}"
TENANT="${TENANT:-}"
OUT="${1:-}"
[ -n "$CONTAINER" ] && [ -n "$TENANT" ] && [ -n "$OUT" ] || {
  echo "RESULT capture-v4-aof incomplete reason=container_tenant_output_required" >&2
  exit 100
}
[ ! -e "$OUT" ] || {
  echo "RESULT capture-v4-aof incomplete reason=output_exists path=$OUT" >&2
  exit 100
}
mkdir -p "$OUT/packet"
RUN_ID="${RUN_ID:-$(date +%s)-$$}"
PREFIX="bench-${RUN_ID}-"

POD="${POD:-acme}" CONTAINER="$CONTAINER" TENANT="$TENANT" RUN_ID="$RUN_ID" \
  bash container/scenarios/packet-switching.sh --mode steady --count 4 --rounds 2 \
    --work "$OUT/packet" >"$OUT/packet-switching.log" 2>&1
packet_rc=$?
if [ "$packet_rc" -ne 0 ]; then
  tail -40 "$OUT/packet-switching.log" >&2
  echo "RESULT capture-v4-aof incomplete reason=packet_switching_rc_${packet_rc}" >&2
  exit 100
fi

docker cp "$CONTAINER:/tmp/appendonlydir" "$OUT/appendonlydir" >/dev/null 2>&1 || {
  echo "RESULT capture-v4-aof incomplete reason=aof_copy_failed" >&2
  exit 100
}
docker logs "$CONTAINER" >"$OUT/custody.log" 2>&1 || {
  echo "RESULT capture-v4-aof incomplete reason=custody_copy_failed" >&2
  exit 100
}

python3 container/scenarios/analyse-v4-aof.py "$OUT/appendonlydir" \
  --participant-prefix "$PREFIX"
