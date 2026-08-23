#!/usr/bin/env bash
# Create one disposable tenant and make one forward outcome genuinely unknown.
set -uo pipefail

CONFIRM="${1:-}"
if [ "$CONFIRM" != "I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT" ] || [ "$#" -ne 1 ]; then
  echo "REFUSED: pass I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT exactly" >&2
  exit 2
fi
command -v docker >/dev/null || { echo "REFUSED: docker is required" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 2
RUN_ID="$(date +%s)-$$"
TENANT="bus100-${RUN_ID}"
PROJECT="h-flock-${TENANT}"
CONTAINER="${PROJECT}-tenant-1"
API_PORT="${BUILD100_API_PORT:-8100}"
SESSION_PORT="${BUILD100_SESSION_PORT:-8101}"
WORK="${BUILD100_WORK:-/tmp/build100-${RUN_ID}}"
CREATED_PROJECT=""
SWITCH_PID=""
mkdir -p "$WORK"

cleanup() {
  if [ -n "$SWITCH_PID" ] && [ -n "$CREATED_PROJECT" ]; then
    docker exec "$CONTAINER" kill -CONT "$SWITCH_PID" >/dev/null 2>&1 || true
  fi
  if [ "$CREATED_PROJECT" = "$PROJECT" ]; then
    echo "FAULT_INJECTION_TEARDOWN project=$CREATED_PROJECT"
    docker compose -p "$CREATED_PROJECT" --env-file container/.env \
      -f container/compose.yaml down -v >/dev/null
  fi
}
trap cleanup EXIT INT TERM

echo "FAULT_INJECTION_ACTIVE kind=forward_unknown project=$PROJECT tenant=$TENANT"
echo "FAULT_INJECTION_ACTIVE disposable=1 target=fault-src->fault-dst work=$WORK"

# accept.sh refuses any existing project and records its own ownership before
# teardown. --keep transfers the newly-created disposable tenant to this run.
EXISTING_PROJECT_RESOURCE="$({
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"
  docker network ls -q --filter "label=com.docker.compose.project=$PROJECT"
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"
} 2>/dev/null | head -1)"
if [ -n "$EXISTING_PROJECT_RESOURCE" ]; then
  echo "REFUSED: generated project $PROJECT already exists; this run did not create it" >&2
  exit 2
fi
bash container/accept.sh --tenant "$TENANT" --api-port "$API_PORT" \
  --session-port "$SESSION_PORT" --keep --no-console >"$WORK/accept.log" 2>&1
accept_rc=$?
# We proved absence immediately before invoking accept.sh. If its project now
# exists, this invocation created it even when a later acceptance gate failed;
# record ownership before interpreting the status so failure cleanup is safe.
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | head -1)" ]; then
  CREATED_PROJECT="$PROJECT"
fi
if [ "$accept_rc" -ne 0 ]; then
  echo "REFUSED: disposable tenant creation/acceptance exited $accept_rc" >&2
  tail -20 "$WORK/accept.log" >&2
  exit "$accept_rc"
fi
if [ "$CREATED_PROJECT" != "$PROJECT" ] \
  || [ -z "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | head -1)" ]; then
  echo "REFUSED: expected newly-created project $PROJECT is absent" >&2
  exit 2
fi

# The marker binds the injector to the tenant this invocation created. Merely
# invoking the Python helper, setting an environment variable, or copying an
# old command cannot arm another tenant.
TOKEN="$(openssl rand -hex 16)"
docker exec "$CONTAINER" redis-cli SET \
  "pod:acme:tenant:${TENANT}:fault.injection" "$TOKEN" >/dev/null
SWITCH_PID="$(docker exec "$CONTAINER" pgrep -f '^python3 -m flock.switch$' | head -1 | tr -d '\r')"
if [ -z "$SWITCH_PID" ]; then
  echo "REFUSED: disposable tenant switch process was not found" >&2
  exit 2
fi
docker exec "$CONTAINER" kill -STOP "$SWITCH_PID"

docker exec -i \
  -e REDIS_URL=redis://127.0.0.1:6379/0 \
  -e FLOCK_WRITER=fault-injection \
  "$CONTAINER" python3 - \
    --pod acme --tenant "$TENANT" --source fault-src --destination fault-dst \
    --token "$TOKEN" --ledger /tmp/build100-ledger.tsv \
    < container/scenarios/inject-forward-unknown.py
inject_rc=$?
if [ "$inject_rc" -ne 0 ]; then
  echo "REFUSED: injector exited $inject_rc" >&2
  exit "$inject_rc"
fi
set -e

docker cp "$CONTAINER:/tmp/build100-ledger.tsv" "$WORK/ledger.tsv" >/dev/null
docker cp "$CONTAINER:/home/ubuntu/.flock/custody/custody.jsonl" \
  "$WORK/custody.log" >/dev/null
# Capture the live queues instead of manufacturing empty inputs. The expected
# emptiness is part of the result: if the write committed, ingress settles the
# UNKNOWN as a strand and INDETERMINATE_FORWARD would be the wrong verdict.
docker exec -i -e REDIS_URL=redis://127.0.0.1:6379/0 "$CONTAINER" \
  python3 - acme "$TENANT" dead >"$WORK/dead.jsonl" <<'PY'
import json, os, sys
import redis
from flock.bus import parse
pod, tenant, resource = sys.argv[1:4]
r = redis.Redis.from_url(os.environ["REDIS_URL"])
for key in r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:*:{resource}"):
    for raw in r.lrange(key, 0, -1):
        print(json.dumps(parse(raw)))
PY
docker exec -i -e REDIS_URL=redis://127.0.0.1:6379/0 "$CONTAINER" \
  python3 - acme "$TENANT" ingress >"$WORK/ingress.jsonl" <<'PY'
import json, os, sys
import redis
from flock.bus import parse
pod, tenant, resource = sys.argv[1:4]
r = redis.Redis.from_url(os.environ["REDIS_URL"])
for key in r.scan_iter(match=f"pod:{pod}:tenant:{tenant}:agent:*:{resource}"):
    for raw in r.lrange(key, 0, -1):
        print(json.dumps(parse(raw)))
PY
: >"$WORK/injections.tsv"

set +e
python3 container/scenarios/reconcile-unicast.py \
  "$WORK/ledger.tsv" "$WORK/custody.log" "$WORK/dead.jsonl" \
  "$WORK/ingress.jsonl" "$WORK/injections.tsv" | tee "$WORK/reconcile.log"
reconcile_rc="${PIPESTATUS[0]}"
set -e
if [ "$reconcile_rc" -ne 5 ] \
  || ! grep -q '^INDETERMINATE_FORWARD ' "$WORK/reconcile.log" \
  || grep -q '^LOSS_' "$WORK/reconcile.log"; then
  echo "REFUSED: expected rc5 INDETERMINATE_FORWARD without LOSS, got rc=$reconcile_rc" >&2
  exit 1
fi
echo "FAULT_INJECTION_RESULT rc=5 event=INDETERMINATE_FORWARD loss=0"
