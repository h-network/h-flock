#!/usr/bin/env bash
set -uo pipefail
CONFIRM="${1:-}"
if [ "$CONFIRM" != "I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT" ] || [ "$#" -ne 1 ]; then
  echo "REFUSED: pass I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT exactly" >&2; exit 2
fi
command -v docker >/dev/null || { echo "REFUSED: docker is required" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT" || exit 2
RUN_ID="$(date +%s)-$$"; TENANT="bus102-${RUN_ID}"; PROJECT="h-flock-${TENANT}"
CONTAINER="${PROJECT}-tenant-1"; WORK="${BUILD102_WORK:-/tmp/build102-${RUN_ID}}"; CREATED_PROJECT=""
mkdir -p "$WORK"
cleanup() {
  if [ "$CREATED_PROJECT" = "$PROJECT" ]; then
    echo "PARTIAL_CONTROL_TEARDOWN project=$CREATED_PROJECT"
    docker compose -p "$CREATED_PROJECT" --env-file container/.env -f container/compose.yaml down -v >/dev/null
  fi
}
trap cleanup EXIT INT TERM
echo "PARTIAL_CONTROL_ACTIVE project=$PROJECT tenant=$TENANT target=sme-2"
if [ -n "$({ docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"; docker network ls -q --filter "label=com.docker.compose.project=$PROJECT"; docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"; } 2>/dev/null | head -1)" ]; then
  echo "REFUSED: generated project already exists" >&2; exit 2
fi
TOKEN="$(openssl rand -hex 16)"
{
  echo "POD=acme"; echo "TENANT=$TENANT"; echo "AGENTS=architect:tmux,sme-2:tmux"
  echo "FLOCK_ACCOUNTS=default"; echo "API_TOKEN=$TOKEN"; echo "API_ENABLED=0"
  echo "API_PORT=18200"; echo "SESSION_PORT=18201"; echo "API_HOST=127.0.0.1"; echo "SESSION_HOST=127.0.0.1"
  echo "VERIFY_AFTER_SECONDS=120"; echo "INGRESS_MAX=300"
} > container/.env
chmod 600 container/.env
docker compose -p "$PROJECT" --env-file container/.env -f container/compose.yaml up -d --build >"$WORK/setup.log" 2>&1
up_rc=$?
if [ -n "$({ docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"; docker network ls -q --filter "label=com.docker.compose.project=$PROJECT"; docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"; } 2>/dev/null | head -1)" ]; then CREATED_PROJECT="$PROJECT"; fi
if [ "$up_rc" -ne 0 ] || [ "$CREATED_PROJECT" != "$PROJECT" ]; then echo "REFUSED: disposable tenant creation failed rc=$up_rc" >&2; exit 2; fi
if [ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$CONTAINER")" != "$PROJECT" ]; then echo "REFUSED: container/project ownership mismatch" >&2; exit 2; fi
printf 'tenant=%s\nproject=%s\ncontainer=%s\n' "$TENANT" "$PROJECT" "$CONTAINER" >"$WORK/run-identity.txt"
status=""
for _ in $(seq 1 60); do status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)"; [ "$status" = healthy ] && break; sleep 2; done
[ "$status" = healthy ] || { echo "REFUSED: tenant unhealthy" >&2; exit 2; }
TOKEN="$(openssl rand -hex 16)"
docker exec "$CONTAINER" redis-cli SET "pod:acme:tenant:${TENANT}:fault.injection" "$TOKEN" >/dev/null
docker exec -i -e REDIS_URL=redis://127.0.0.1:6379/0 -e FLOCK_WRITER=fault-injection "$CONTAINER" sh -c 'python3 - "$@" 2>&1 | tee /proc/1/fd/1' -- \
  --pod acme --tenant "$TENANT" --agent sme-2 --token "$TOKEN" --snapshot /tmp/build102-snapshot.txt < container/scenarios/inject-partial-control.py >"$WORK/injector.log" 2>&1
inject_rc=$?
docker cp "$CONTAINER:/tmp/build102-snapshot.txt" "$WORK/snapshot.txt" >/dev/null 2>&1 || true
docker logs "$CONTAINER" >"$WORK/custody.log" 2>&1
for required in run-identity.txt setup.log injector.log snapshot.txt custody.log; do
  [ -s "$WORK/$required" ] || { echo "REFUSED: missing or empty artifact $required" >&2; exit 1; }
done
grep -q "tenant=$TENANT" "$WORK/run-identity.txt" || { echo "REFUSED: stale tenant identity" >&2; exit 1; }
grep -q 'stop_agent_incomplete' "$WORK/custody.log" || { echo "REFUSED: missing incomplete control record" >&2; exit 1; }
grep -q 'resource purge outcome UNKNOWN' "$WORK/custody.log" || { echo "REFUSED: missing unknown purge reason" >&2; exit 1; }
grep -q 'START_RESULT roster=present' "$WORK/snapshot.txt" || { echo "REFUSED: missing StartAgent observation" >&2; exit 1; }
cat "$WORK/snapshot.txt"; echo "PARTIAL_CONTROL_RESULT rc=$inject_rc"
[ "$inject_rc" -eq 0 ] || exit "$inject_rc"
