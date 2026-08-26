#!/usr/bin/env bash
# accept.sh — the operator's whole path, in one command.
#
#   bash container/accept.sh [SUITE...] [--tenant NAME] [--api-port N]
#                            [--session-port N] [--console-port N]
#                            [--keep] [--no-console] [--scenario NAME] [--help]
#
# --scenario analyse-run --log PATH [--expect-writer NAME=COUNT],
# --scenario analyse-verification --log PATH, and --scenario analyse-v4-aof
# --aof-dir DIR run standalone analysers; tmux-boundary, tmux-concurrent-hire,
# and tmux-window-loss run one terminal scenario. Core console emits RESULT console-ready and
# RESULT console-flow as separate gates.
#
# Installs a tenant the way a person would, waits for it to be healthy, runs the
# selected suites against it, and tears it down.
#
# SUITES — bare `accept.sh` is `--core`. They compose: `--core --tmux`.
#
#   --core    plumbing check · failure simulator · packet switching ·
#             payload and ack · console            (the framework works)
#   --fault   conservation under injected death · forward-unknown ·
#             partial control damage               (it fails honestly)
#   --api     token auth and limits · concurrency and time ·
#             session and log privacy              (the door behaves)
#   --tmux    credential boundary · concurrent hire · window loss
#             Requires real agents in real panes and the REST API door. It is
#             deliberately limited to the three verified scenarios below.
#   --all     every suite above
#
# EXCLUDED: tmux-nemotron is manual integration only. bus-* scenarios belong
# under conservation/fault, never --tmux.
#
# LIMIT: these three members do NOT exercise a successful paste_text.
# tmux-window-loss targets a missing window, tmux-boundary sends nothing, and
# tmux-concurrent-hire uses the control-plane opener. Until a successful-paste
# scenario joins this suite, it does not exercise delivery_unverified and does
# not run analyse-verification.
#
# ⚠ EXIT CODES, so a caller never has to read the prose:
#   0    every selected suite passed
#   1+   that many steps FAILED
#   2    bad arguments, or a refusal to touch something this run does not own
#   100  ran but INCOMPLETE — a step could not reach a verdict, which is
#        neither a pass nor a failure and must not be collapsed into either
#
# ⚠ Each step prints one `RESULT <step> <verdict>` line. Parse those, not the
# banners.
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
#
# ⚠ **Over SSH, run this detached with stdin closed — not as a blocking
# foreground call.** It ends up piping into setup.sh's interactive prompts; a
# backgrounded remote process that still has stdin attached gets stopped on
# SIGTTIN and hangs silently, which looks exactly like a dead SSH channel with
# no exit code. Close stdin, detach, and poll the log instead of holding the
# connection open:
#
#   ssh host "cd h-flock && nohup bash -c 'bash container/accept.sh --tenant T --keep \
#     >run-T.log 2>&1; echo EXIT:\$? >>run-T.log' >/dev/null 2>&1 </dev/null & disown"
#   ssh host "tail -30 run-T.log"
set -uo pipefail

TENANT="${TENANT:-}"
TENANT_EXPLICIT=0
[ -n "$TENANT" ] && TENANT_EXPLICIT=1
API_PORT="${API_PORT:-}"
API_PORT_EXPLICIT=0
[ -n "$API_PORT" ] && API_PORT_EXPLICIT=1
SESSION_PORT=8081
CONSOLE_PORT=8099
KEEP=0
CONSOLE=1
SUITES=""
SCENARIO=""
ANALYSER_LOG=""
AOF_DIR=""
ANALYSER_ARGS=()
SCENARIO_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --tenant) TENANT="$2"; TENANT_EXPLICIT=1; shift 2 ;;
    --api-port) API_PORT="$2"; API_PORT_EXPLICIT=1; shift 2 ;;
    --session-port) SESSION_PORT="$2"; shift 2 ;;
    --console-port) CONSOLE_PORT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --no-console) CONSOLE=0; shift ;;
    --core) SUITES="$SUITES core"; shift ;;
    --fault) SUITES="$SUITES fault"; shift ;;
    --api) SUITES="$SUITES api"; shift ;;
    --tmux) SUITES="$SUITES tmux"; shift ;;
    --all) SUITES="core fault api tmux"; shift ;;
    --scenario) SCENARIO="$2"; shift 2 ;;
    --log) ANALYSER_LOG="$2"; shift 2 ;;
    --aof-dir) AOF_DIR="$2"; shift 2 ;;
    --expect-writer) ANALYSER_ARGS+=(--expect-writer "$2"); shift 2 ;;
    --break-delivery) SCENARIO_ARGS+=(--break-delivery); shift ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "accept: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
# SCENARIO_ARGS currently contains only --break-delivery; widen this guard when another scenario flag is added.
[ "${#SCENARIO_ARGS[@]}" -eq 0 ] || [ "$SCENARIO" = tmux-paste-delivery ] || {
  echo "accept: --break-delivery requires --scenario tmux-paste-delivery" >&2
  exit 2
}
[ -n "$TENANT" ] || TENANT="accept"
[ -n "$API_PORT" ] || API_PORT=8080

# Bare invocation is the common case: is the framework healthy.
SUITES="${SUITES:-}"; [ -n "${SUITES// /}" ] || SUITES="core"
has_suite() { case " $SUITES " in *" $1 "*) return 0;; *) return 1;; esac; }

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$_here" || exit 2

# Standalone analyser seam: run one log judge without installing a tenant.
# The analysers own their RESULT contract and return 0, failed-check count, or
# 100 for an unavailable capture. This path is deliberately before Docker and
# setup so red controls can be demonstrated in seconds with --scenario.
if [ -n "$SCENARIO" ]; then
  case "$SCENARIO" in
    analyse-run)
      [ -n "$ANALYSER_LOG" ] || { echo "RESULT analyse-run incomplete reason=missing_argument" >&2; exit 100; }
      exec python3 container/scenarios/analyse-run.py "$ANALYSER_LOG" "${ANALYSER_ARGS[@]}" ;;
    analyse-verification)
      [ -n "$ANALYSER_LOG" ] || { echo "RESULT analyse-verification incomplete reason=missing_argument" >&2; exit 100; }
      exec python3 container/scenarios/analyse-verification.py "$ANALYSER_LOG" ;;
    analyse-v4-aof)
      [ -n "$AOF_DIR" ] || { echo "RESULT analyse-v4-aof incomplete reason=missing_argument" >&2; exit 100; }
      exec python3 container/scenarios/analyse-v4-aof.py "$AOF_DIR" ;;
    tmux-boundary|tmux-paste-delivery)
      [ "$TENANT_EXPLICIT" = 1 ] || { echo "RESULT $SCENARIO incomplete reason=tenant_required" >&2; exit 100; }
      export TENANT API_PORT
      exec bash "container/scenarios/${SCENARIO}.sh" "${SCENARIO_ARGS[@]}" ;;
    tmux-concurrent-hire|tmux-window-loss)
      [ "$TENANT_EXPLICIT" = 1 ] || { echo "RESULT $SCENARIO incomplete reason=tenant_required" >&2; exit 100; }
      [ "$API_PORT_EXPLICIT" = 1 ] || { echo "RESULT $SCENARIO incomplete reason=api_port_required" >&2; exit 100; }
      export TENANT API_PORT
      exec bash "container/scenarios/${SCENARIO}.sh" ;;
    *) echo "accept: unknown scenario '$SCENARIO'" >&2; exit 2 ;;
  esac
fi
PROJECT="h-flock-${TENANT}"
CONTAINER="${PROJECT}-tenant-1"
FAILED=0
SKIPPED=""
CREATED_PROJECT=""
CONSOLE_PID=""
step() { echo; echo "══ $* ══"; }
fail() { echo "  ✗ $*" >&2; FAILED=$((FAILED+1)); }

# ⚠ ONE MACHINE-READABLE LINE PER STEP. A caller greps `^RESULT ` and never has
# to read a banner. `incomplete` is deliberately distinct from `fail`: a step
# that could not reach a verdict is neither a pass nor a failure, and collapsing
# it into either is how a gate starts lying.
INCOMPLETE=0
record() {                       # record <step> <rc> [note]
  local name="$1" rc="$2" note="${3:-}"
  case "$rc" in
    0)   echo "RESULT $name pass ${note}" ;;
    100) echo "RESULT $name incomplete ${note}" >&2; INCOMPLETE=$((INCOMPLETE+1)) ;;
    *)   echo "RESULT $name fail rc=$rc ${note}" >&2; FAILED=$((FAILED+1)) ;;
  esac
}

# Run one scenario against THIS tenant and record its verdict by exit code.
run_scenario() {                 # run_scenario <name> <script> [args...]
  local name="$1"; shift
  local script="$1"; shift
  if [ ! -f "$script" ]; then record "$name" 100 "missing=$script"; return; fi
  # ⚠ NO `|| true` ON THE FILTER. It used to read PIPESTATUS[0] after
  # `... | grep ... || true`, and when grep matched nothing the `|| true` fired,
  # PIPESTATUS became 0, and a scenario that exited 6 in silence recorded as a
  # PASS. Dropping the `|| true` keeps PIPESTATUS[0] as the SCRIPT's code, which
  # is the only number that decides the verdict.
  #
  # ⚠ And --line-buffered so lines appear AS THEY HAPPEN. Buffering to a file and
  # printing at the end made a multi-minute step indistinguishable from a hang,
  # and someone killed a working run because of it. A test bed that goes quiet
  # for minutes teaches people to interrupt it.
  POD=acme TENANT="$TENANT" CONTAINER="$CONTAINER" API_PORT="$API_PORT" bash "$script" "$@" 2>&1 \
    | grep --line-buffered -E "^RESULT|_RESULT |^==|FAIL|PASS="
  record "$name" "${PIPESTATUS[0]}"
}
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
  if [ "$KEEP" = "1" ]; then
    echo
    if [ -n "$CONSOLE_PID" ]; then
      echo "kept: container=$CONTAINER; console_pid=$CONSOLE_PID (stop console: kill $CONSOLE_PID)"
    else
      echo "kept: container=$CONTAINER; console=not-started"
    fi
    return 0
  fi
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
#
# ⚠ A stray VOLUME left by a prior `down` without `-v` is enough on its own to
# trigger this refusal with no container or network in sight — `docker ps`
# alone will look clean. Always tear down with `down -v`, and give each run a
# fresh timestamped --tenant so this can never fire.
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

# ⚠ Name the image before anything runs. A suite that passes tells you nothing
# unless you know WHAT it passed against, and an image reused from an earlier
# commit is exactly the sort of thing that makes a green run meaningless.
. container/flock-image.sh 2>/dev/null || true
if declare -f flock_image_tag >/dev/null; then
  export FLOCK_IMAGE="$(flock_image_tag)"
  flock_prune_images
fi

step "install — driving setup.sh as a person would"
declare -f flock_image_line >/dev/null && flock_image_line
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
# ⚠ A SHORT VERIFICATION WINDOW, ON PURPOSE. The failure simulator proves the
# fabric still CATCHES a wedged agent, and no verdict can exist until a marker is
# older than this. Production is 120s, which would make each of the four cases
# wait out two minutes. What is under test is the detection, not the tuning
# value — that is measured separately in BUILD-81's live arm.
# ⚠ It also exercises the knob end to end. `Dockerfile:119` shadowed this exact
# variable and two lanes' fixes never reached a running tenant.
export VERIFY_AFTER_SECONDS=5

rm -f container/.env
# ⚠ POSITIONAL, AND setup.sh's PROMPT ORDER IS PART OF THIS FILE'S CONTRACT.
# Two answers were inserted on 2026-08-23 when "Default CLI" and "any agents
# differing" moved OUT of the accounts branch so a single-account tenant can
# still choose codex or agy. Both are blank here: claude for everyone, no
# exceptions. Adding a prompt to setup.sh without adding an answer here shifts
# every later field and the tenant comes up configured as something nobody asked
# for — which is why the answers are listed one per line below.
#
#   acme        pod                     n     more than one account?
#   $TENANT     tenant                  ""    OAuth token -> none, log in later
#   2           how many agents         ""    default CLI  -> claude
#   architect   agent #1                ""    any agents differing -> none
#   sme-2       agent #2                n     local model provider?
#                                       y     open the REST API door?
#                                       n     telegram?
#   $API_PORT   api host port           $SESSION_PORT  session host port
#   y           reach from elsewhere    ""    tls cert path -> more choices
#   n           generate self-signed?
printf 'acme\n%s\n2\narchitect\nsme-2\nn\n\n\n\nn\ny\nn\n%s\n%s\ny\n\nn\n' \
  "$TENANT" "$API_PORT" "$SESSION_PORT" | ./setup.sh \
  > >(grep -E "healthy|error|Error|NEEDS LOGIN|logged in|wrote container/.env|not enabled" | head -10) 2>&1
SETUP_RC="${PIPESTATUS[1]}"
# setup.sh is the operation that creates the project. Record ownership only
# after Docker confirms that this run brought its container into existence.
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | head -1)" ]; then
  CREATED_PROJECT="$PROJECT"
fi
[ "$SETUP_RC" = "0" ] || { record "install" "$SETUP_RC" "setup_failed"; exit "$FAILED"; }
[ -f container/.env ] || { record "install" 1 "missing_env"; exit "$FAILED"; }

# ⚠ The post-hoc port rewrite that used to live here is gone. setup.sh now ASKS
# for the host ports, so they are answered above and the tenant comes up on them
# first time — no sed, no second `up -d`. It also refuses a port already
# listening, so a collision fails at the prompt rather than producing the
# healthy-looking tenant nobody could reach that the old comment described.
grep -q "^API_ENABLED=1" container/.env || { record "install" 1 "api_disabled"; exit "$FAILED"; }
grep -q "^API_PORT=${API_PORT}\$" container/.env || { record "install" 1 "wrong_api_port"; exit "$FAILED"; }
record "install" 0

step "health"
for _ in $(seq 1 60); do
  STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)"
  [ "$STATUS" = "healthy" ] && break
  sleep 2
done
echo "  container: ${STATUS:-unknown}"
[ "${STATUS:-}" = "healthy" ] || { record "health" 1 "status=${STATUS:-unknown}"; exit "$FAILED"; }
record "health" 0
docker exec "$CONTAINER" bash -lc "TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux list-windows -t $TENANT -F '#{window_name}'" 2>/dev/null | tr '\n' ' '
echo

if has_suite core; then
step "plumbing check and failure simulator"
# FORCE=1: these agents run CLIs, and the check pastes fixtures into panes. On a
# disposable tenant that is what we want; the guard exists so it never happens
# to somebody's office by reflex.
FORCE=1 POD=acme TENANT="$TENANT" CONTAINER="$CONTAINER" bash container/plumbing-check.sh 2>&1 \
  | grep -E "^==|FAIL|PASS=|sim-blocked:"
PLUMB="${PIPESTATUS[0]}"
record "plumbing" "$PLUMB"

if [ "$CONSOLE" = "1" ]; then
  step "console"
  SECRET="$(openssl rand -hex 8 2>/dev/null || echo acceptsecret)"
  TOKEN="$(grep '^API_TOKEN=' container/.env | cut -d= -f2)"
  # server.py already reads these credentials from the environment. Keeping
  # them out of argv prevents ps and /proc/<pid>/cmdline exposing them for the
  # entire lifetime of a console retained by --keep.
  export API_TOKEN="$TOKEN"
  export HFLOCK_SECRET="$SECRET"
  if [ "$NEGATIVE_GATE" != "console-ready" ]; then
    (cd clients/web && exec setsid python3 server.py --listen 0.0.0.0 --port "$CONSOLE_PORT" \
        --api "http://127.0.0.1:${API_PORT}" --session "http://127.0.0.1:${SESSION_PORT}") \
        > /tmp/accept-console.log 2>&1 &
    CONSOLE_PID="$!"
  fi
  if ! poll_console; then
    record "console-ready" 1 "http=${CODE:-no_response}"
    continue_console=0
  else
    record "console-ready" 0 "http=$CODE"
    continue_console=1
  fi
  echo "  console http=${CODE}"
  [ "$CODE" = "200" ] || tail -3 /tmp/accept-console.log
  if [ "$continue_console" = "1" ] && python3 -c "import playwright" 2>/dev/null; then
    python3 clients/web/flow-check.py --console "http://127.0.0.1:${CONSOLE_PORT}" \
      --secret "$SECRET" --container "$CONTAINER" --tenant "$TENANT" 2>&1 | tail -12
    # ⚠ Reports through record() like every other step. It used to call fail()
    # and print a banner, so it counted toward the exit code while emitting no
    # RESULT line — a caller parsing `^RESULT` was blind to a step --help
    # promises. A verdict nobody can read is not a verdict.
    record "console-flow" "${PIPESTATUS[0]}"
  elif [ "$continue_console" = "1" ]; then
    # ⚠ Not a pass. Say what was not checked, so nobody reads silence as green.
    echo "  ⚠ playwright is not installed here — console FLOWS WERE NOT CHECKED."
    echo "    The console answering 200 says nothing about whether it works."
    SKIPPED="${SKIPPED} console-flows"
    record "console-flow" 100 "playwright_absent"
  fi
fi

# ⚠ These two are the framework's own plumbing verification: send N envelopes,
# count N at every custody stage, and hold the log to a number the harness knows
# without asking the log. They install a no-op `flock.port` for the run, because
# the switch spawns a real port for every roster member and it would otherwise
# race the synthetic one for the same queue.
step "packet switching"
run_scenario "packet-switching" container/scenarios/packet-switching.sh --mode steady --count 10 --rounds 2

step "payload and ack"
run_scenario "payload-ack" container/scenarios/payload-ack.sh --count 10 --rounds 1
fi

if has_suite fault; then
  # ⚠ conservation runs against THIS tenant. The other two build their own
  # disposable one and destroy it, which is why they refuse to start without the
  # confirmation below — a guard against someone pointing them at a live office
  # by reflex. Passing it here is deliberate: accept.sh already owns a throwaway
  # tenant and says so in its own header. It is spelled out rather than put in a
  # variable so that nobody can wire these up without reading what they do.
  DESTRUCTIVE=I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT

  step "fault — conservation under injected death"
  run_scenario "conservation" container/scenarios/conservation.sh

  step "fault — forward outcome unknown"
  run_scenario "forward-unknown" container/scenarios/fault-forward-unknown.sh "$DESTRUCTIVE"

  step "fault — partial control damage"
  run_scenario "partial-control" container/scenarios/partial-control-damage.sh "$DESTRUCTIVE"
fi

if has_suite api; then
  step "api — auth and limits"
  run_scenario "api-auth" container/scenarios/api-auth-and-limits.sh

  step "api — concurrency and time"
  run_scenario "api-concurrency" container/scenarios/api-concurrency-and-time.sh

  step "api — session and log privacy"
  run_scenario "api-privacy" container/scenarios/api-session-and-log-privacy.sh
fi

if has_suite tmux; then
  # Unlike the API-type synthetic participants used by the other suites, these
  # scenarios require real processes in real panes. setup.sh above creates the
  # architect and sme-2 panes; tenant and API port are threaded explicitly by
  # run_scenario so no scenario can fall through to a coincidental default.
  step "tmux — credential boundary"
  WRITER=architect READER=sme-2 run_scenario "tmux-boundary" container/scenarios/tmux-boundary.sh

  step "tmux — concurrent hire"
  run_scenario "tmux-concurrent-hire" container/scenarios/tmux-concurrent-hire.sh

  step "tmux — observable window loss and recovery"
  AGENT=sme-2 run_scenario "tmux-window-loss" container/scenarios/tmux-window-loss.sh
fi


step "result"
echo "  suites: $SUITES"
if [ "$FAILED" = "0" ] && [ "$INCOMPLETE" = "0" ]; then
  echo "  passed: every step in every selected suite"
elif [ "$FAILED" != "0" ]; then
  echo "  NOT accepted: $FAILED step(s) failed"
else
  echo "  INCOMPLETE: $INCOMPLETE step(s) could not reach a verdict"
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
# ⚠ A SKIP IS NOT A PASS, AND THE EXIT CODE HAS TO SAY SO.
# This used to be `exit "$FAILED"`, so a run that never opened a browser printed
# "⚠ NOT CHECKED: console-flows" and returned 0. The comment above already said
# "Never let a skip read as a pass" — which was true of the OUTPUT and false of
# the STATUS, and status is what a person glances at and what any wrapper reads.
#
# ⚠ Distinguishable on purpose: 1+ means a step FAILED, 100 means everything run
# passed but something was not run. A caller can tell "broken" from "incomplete"
# without parsing prose.
if [ "$FAILED" != "0" ]; then
  exit "$FAILED"
elif [ -n "$SKIPPED" ] || [ "$INCOMPLETE" != "0" ]; then
  exit 100
fi
exit 0
