#!/usr/bin/env bash
# accept.sh — the operator's whole path, in one command.
#
#   bash container/accept.sh [--tenant NAME] [--api-port N] [--session-port N]
#                            [--console-port N] [--keep] [--no-console]
#
# Installs a tenant the way a person would, waits for it to be healthy, runs the
# plumbing check and the failure simulator against it, optionally drives the
# console in a browser, and tears it down.
#
# ⚠ **This exists because every verification this week ran as a hand-typed
# sequence, and twice the thing that mattered was found only because someone got
# round to running it.** Build 36 shipped a guard that proved itself and refused
# every container. A hire path was rewritten and the failure simulator caught a
# fixture that had been passing because of a bug. Neither is visible from a unit
# test.
#
# ⚠ **It runs `setup.sh` rather than writing `.env` itself.** The installer is
# the operator's path, so it has to be the thing under test — piping answers into
# it is deliberate, and if the prompts change this script must change with them.
# That is a feature: a silent prompt change should break the acceptance run.
#
# ⚠ **One acceptance run per host at a time.** `setup.sh` publishes 8080/8081 and
# has no way to be told otherwise before it starts the tenant, so `--api-port`
# can only move the mapping *afterwards*. If another tenant holds 8080 the
# install step fails on a port conflict, loudly. Free the host first.
#
# ⚠ **Everything is printed, including the dull parts.** A harness that reports
# only its verdict hides the output someone needed.
set -uo pipefail

TENANT="accept"
API_PORT=8080
SESSION_PORT=8081
CONSOLE_PORT=8099
KEEP=0
CONSOLE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tenant) TENANT="$2"; shift 2 ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --session-port) SESSION_PORT="$2"; shift 2 ;;
    --console-port) CONSOLE_PORT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --no-console) CONSOLE=0; shift ;;
    *) echo "accept: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$_here" || exit 2
PROJECT="h-flock-${TENANT}"
CONTAINER="${PROJECT}-tenant-1"
FAILED=0
step() { echo; echo "══ $* ══"; }
fail() { echo "  ✗ $*" >&2; FAILED=$((FAILED+1)); }

cleanup() {
  [ "$KEEP" = "1" ] && { echo; echo "kept: $CONTAINER (--keep)"; return 0; }
  step "teardown"
  pkill -9 -f "[s]erver\.py --listen 0.0.0.0 --port $CONSOLE_PORT" 2>/dev/null || true
  docker compose -p "$PROJECT" --env-file container/.env -f container/compose.yaml down -v 2>&1 | tail -2
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "accept: docker is required" >&2; exit 2; }

step "install — driving setup.sh as a person would"
# pod, tenant, 2 agents and their names, no extra accounts, no endpoint,
# reachable from another machine, no certificate, no self-signed.
rm -f container/.env
printf 'acme\n%s\n2\narchitect\nsme-2\nn\nn\ny\n\nn\n' "$TENANT" | ./setup.sh 2>&1 \
  | grep -E "healthy|error|Error|NEEDS LOGIN|logged in|wrote container/.env" | head -8
[ -f container/.env ] || { fail "setup.sh wrote no container/.env"; exit 1; }

if [ "$API_PORT" != "8080" ] || [ "$SESSION_PORT" != "8081" ]; then
  # ⚠ Host side only. compose pins the container-side bind, because setting
  # these in .env used to move the door's own port while the mapping still
  # pointed at 8080 — a healthy-looking tenant nobody could reach.
  sed -i -e "s/^API_PORT=.*/API_PORT=${API_PORT}/" -e "s/^SESSION_PORT=.*/SESSION_PORT=${SESSION_PORT}/" container/.env
  docker compose -p "$PROJECT" --env-file container/.env -f container/compose.yaml up -d >/dev/null 2>&1
fi

step "health"
for _ in $(seq 1 60); do
  STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)"
  [ "$STATUS" = "healthy" ] && break
  sleep 2
done
echo "  container: ${STATUS:-unknown}"
[ "${STATUS:-}" = "healthy" ] || fail "tenant never became healthy"
docker exec "$CONTAINER" bash -lc "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT -F '#{window_name}'" 2>/dev/null | tr '\n' ' '
echo

step "plumbing check and failure simulator"
# FORCE=1: these agents run CLIs, and the check pastes fixtures into panes. On a
# disposable tenant that is what we want; the guard exists so it never happens
# to somebody's office by reflex.
FORCE=1 POD=acme TENANT="$TENANT" CONTAINER="$CONTAINER" bash container/plumbing-check.sh 2>&1 \
  | grep -E "^==|FAIL|PASS=|sim-blocked:"
PLUMB="${PIPESTATUS[0]}"
[ "$PLUMB" = "0" ] || fail "plumbing check reported failures"

if [ "$CONSOLE" = "1" ]; then
  step "console"
  SECRET="$(openssl rand -hex 8 2>/dev/null || echo acceptsecret)"
  TOKEN="$(grep '^API_TOKEN=' container/.env | cut -d= -f2)"
  ( cd clients/web && setsid nohup python3 server.py --listen 0.0.0.0 --port "$CONSOLE_PORT" \
      --api "http://127.0.0.1:${API_PORT}" --session "http://127.0.0.1:${SESSION_PORT}" \
      --token "$TOKEN" --secret "$SECRET" > /tmp/accept-console.log 2>&1 & )
  sleep 8
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${CONSOLE_PORT}/" || true)"
  echo "  console http=${CODE}"
  [ "$CODE" = "200" ] || { fail "console did not answer"; tail -3 /tmp/accept-console.log; }
  if python3 -c "import playwright" 2>/dev/null; then
    python3 clients/web/flow-check.py --console "http://127.0.0.1:${CONSOLE_PORT}" \
      --secret "$SECRET" --container "$CONTAINER" --tenant "$TENANT" 2>&1 | tail -12
    [ "${PIPESTATUS[0]}" = "0" ] || fail "console flows failed"
  else
    # ⚠ Not a pass. Say what was not checked, so nobody reads silence as green.
    echo "  ⚠ playwright is not installed here — console FLOWS WERE NOT CHECKED."
    echo "    The console answering 200 says nothing about whether it works."
  fi
fi

step "result"
if [ "$FAILED" = "0" ]; then
  echo "  accepted: install, health, plumbing, simulator${CONSOLE:+, console}"
else
  echo "  NOT accepted: $FAILED step(s) failed"
fi
echo "  ⚠ This is the operator's path, not the whole product. It does not run for"
echo "    hours, does not inject failures, and cannot tell you whether anything"
echo "    looks right."
exit "$FAILED"
