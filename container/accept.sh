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
# ⚠ **`--api-port` now works before the tenant starts.** setup.sh asks for the
# host ports, so `--api-port`/`--session-port` are answered at the prompt rather
# than patched in afterwards. A port already listening is refused there, loudly,
# instead of producing a tenant whose mapping points at nothing. Two acceptance
# runs on one host is therefore a matter of choosing different ports.
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
SKIPPED=""
CREATED_PROJECT=""
CONSOLE_PID=""
step() { echo; echo "══ $* ══"; }
fail() { echo "  ✗ $*" >&2; FAILED=$((FAILED+1)); }
CONSOLE_GATE_DEADLINE_SECONDS="${CONSOLE_GATE_DEADLINE_SECONDS:-15}"
NEGATIVE_GATE="${NEGATIVE_GATE:-}"
poll_console() {
  local deadline=$(( $(date +%s) + CONSOLE_GATE_DEADLINE_SECONDS ))
  CODE=""
  while :; do
    CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${CONSOLE_PORT}/" || true)"
    [ "$CODE" = "200" ] && return 0
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "  ✗ console deadline ${CONSOLE_GATE_DEADLINE_SECONDS}s expected [http 200] got [${CODE:-no response}]" >&2
      FAILED=$((FAILED+1))
      if [ "$NEGATIVE_GATE" = "console-ready" ]; then
        echo "NEGATIVE_CONTROL gate=console-ready deadline=${CONSOLE_GATE_DEADLINE_SECONDS}s condition=absent"
        exit 97
      fi
      return 1
    fi
    sleep 0.1
  done
}

cleanup() {
  [ "$KEEP" = "1" ] && { echo; echo "kept: $CONTAINER (--keep)"; return 0; }
  step "teardown"
  # Kill only the console this invocation started. A host-wide pkill pattern
  # killed unrelated SSH shells whose command line happened to contain it.
  [ -n "$CONSOLE_PID" ] && kill "$CONSOLE_PID" 2>/dev/null || true
  # Never destroy a compose project that this invocation did not create.
  [ "$CREATED_PROJECT" = "$PROJECT" ] && \
    docker compose -p "$CREATED_PROJECT" --env-file container/.env \
      -f container/compose.yaml down -v 2>&1 | tail -2
}

# This harness is destructive by design. Refuse the live office even if its
# tenant name was supplied by reflex or leaked from the agent environment.
if [ "${FORCE:-0}" != "1" ] && { [ "$PROJECT" = "${AGENT_OFFICE:-}" ] || [ "$TENANT" = "${AGENT_OFFICE:-}" ]; }; then
  echo "accept: refusing live office '${AGENT_OFFICE}' (set FORCE=1 only if destruction is intentional)" >&2
  exit 2
fi

command -v docker >/dev/null || { echo "accept: docker is required" >&2; exit 2; }

# An existing project cannot have been created by this invocation. Refusing it
# also makes the ownership rule hold for non-office tenants. Query Docker's
# compose labels directly: loading compose.yaml can fail before setup writes
# its .env, and an empty result from that failure would be dangerously false.
EXISTING_PROJECT_RESOURCE="$({
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"
  docker network ls -q --filter "label=com.docker.compose.project=$PROJECT"
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"
} 2>/dev/null | head -1)"
if [ -n "$EXISTING_PROJECT_RESOURCE" ]; then
  echo "accept: refusing existing compose project '$PROJECT'; this run does not own it" >&2
  exit 2
fi
trap cleanup EXIT

step "install — driving setup.sh as a person would"
# ⚠ POSITIONAL. One answer per prompt, in setup.sh's order:
#   pod · tenant · 2 agents · their names · no extra accounts · no provider
#   · OPEN THE API DOOR (yes — this harness drives it) · no Telegram
#   · api host port · session host port
#   · reachable from another machine · no certificate · no self-signed
#
# ⚠ The four middle answers were added 2026-08-20. The prompts changed and this
# string did not, which is the breakage the header above predicts — and it is
# api's "atomic edge and consumer landing" rule: an edge knob changed without
# its consumers in the same commit leaves the repo broken.
rm -f container/.env
printf 'acme\n%s\n2\narchitect\nsme-2\nn\nn\ny\nn\n%s\n%s\ny\n\nn\n' \
  "$TENANT" "$API_PORT" "$SESSION_PORT" | ./setup.sh 2>&1 \
  | grep -E "healthy|error|Error|NEEDS LOGIN|logged in|wrote container/.env|not enabled" | head -10
# setup.sh is the operation that creates the project. Record ownership only
# after Docker confirms that this run brought its container into existence.
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | head -1)" ]; then
  CREATED_PROJECT="$PROJECT"
fi
[ -f container/.env ] || { fail "setup.sh wrote no container/.env"; exit 1; }

# ⚠ The post-hoc port rewrite that used to live here is gone. setup.sh now ASKS
# for the host ports, so they are answered above and the tenant comes up on them
# first time — no sed, no second `up -d`. It also refuses a port already
# listening, so a collision fails at the prompt rather than producing the
# healthy-looking tenant nobody could reach that the old comment described.
grep -q "^API_ENABLED=1" container/.env || { fail "setup.sh did not enable the api door"; exit 1; }
grep -q "^API_PORT=${API_PORT}\$" container/.env || { fail "setup.sh wrote the wrong API_PORT"; exit 1; }

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
  if [ "$NEGATIVE_GATE" != "console-ready" ]; then
    (cd clients/web && exec setsid python3 server.py --listen 0.0.0.0 --port "$CONSOLE_PORT" \
        --api "http://127.0.0.1:${API_PORT}" --session "http://127.0.0.1:${SESSION_PORT}" \
        --token "$TOKEN" --secret "$SECRET") > /tmp/accept-console.log 2>&1 &
    CONSOLE_PID="$!"
  fi
  poll_console
  echo "  console http=${CODE}"
  [ "$CODE" = "200" ] || tail -3 /tmp/accept-console.log
  if python3 -c "import playwright" 2>/dev/null; then
    python3 clients/web/flow-check.py --console "http://127.0.0.1:${CONSOLE_PORT}" \
      --secret "$SECRET" --container "$CONTAINER" --tenant "$TENANT" 2>&1 | tail -12
    [ "${PIPESTATUS[0]}" = "0" ] || fail "console flows failed"
  else
    # ⚠ Not a pass. Say what was not checked, so nobody reads silence as green.
    echo "  ⚠ playwright is not installed here — console FLOWS WERE NOT CHECKED."
    echo "    The console answering 200 says nothing about whether it works."
    SKIPPED="${SKIPPED} console-flows"
  fi
fi

step "result"
if [ "$FAILED" = "0" ]; then
  RESULT="  passed: install, health, plumbing, simulator"
  [ "$CONSOLE" = "1" ] && RESULT="$RESULT, console reachable"
  echo "$RESULT"
else
  echo "  NOT accepted: $FAILED step(s) failed"
fi
# ⚠ Never let a skip read as a pass. The first version of this script printed
# "accepted: … console" on a host with no browser, having checked only that the
# port answered — the same defect it exists to catch elsewhere.
if [ -n "$SKIPPED" ]; then
  echo "  ⚠ NOT CHECKED:${SKIPPED}"
  echo "    This run is incomplete. Run flow-check where playwright is installed:"
  echo "    python3 clients/web/flow-check.py --console http://<host>:${CONSOLE_PORT} --secret <secret> \\"
  echo "        --container ${CONTAINER} --tenant ${TENANT} --ssh <user@host>"
fi
echo "  ⚠ This is the operator's path, not the whole product. It does not run for"
echo "    hours, does not inject failures, and cannot tell you whether anything"
echo "    looks right."
exit "$FAILED"
