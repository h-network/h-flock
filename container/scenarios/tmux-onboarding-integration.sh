#!/usr/bin/env bash
# MANUAL INTEGRATION TOOL — NEVER WIRE INTO accept.sh OR AN AUTOMATED SUITE.
#
# A real local model decides whether to onboard anyone, so model silence is an
# incomplete observation, never a product failure. A message that enters
# custody and is dead-lettered is different: that is plumbing loss and fails.
# This tool emits ONBOARDING, never RESULT.
#
# Usage:
#   TENANT=NAME PROVIDER_LOCAL_URL=http://HOST:PORT \
#     PROVIDER_LOCAL_MODEL=MODEL \
#     container/scenarios/tmux-onboarding-integration.sh OUTPUT_DIR
#
# PROVIDER_NAME selects the PROVIDER_<NAME>_* variables (default: local).
# KEEP=1 leaves the owned tenant running (default); KEEP=0 captures evidence
# first and then tears it down. The tool refuses to adopt an existing tenant.
# ONBOARD_CONTRADICTION_GRACE controls only the final log/pane contradiction
# recheck (default: one normal observation interval; bounded to 1..30s and no
# greater than ONBOARD_TIMEOUT).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 2

POD="${POD:-acme}"
TENANT="${TENANT:-}"
ARCHITECT="${ARCHITECT:-architect}"
SMES="${SMES:-sme-1 sme-2}"
PROVIDER_NAME="${PROVIDER_NAME:-local}"
ONBOARD_TIMEOUT="${ONBOARD_TIMEOUT:-900}"
ONBOARD_POLL_SECONDS=2
ONBOARD_CONTRADICTION_GRACE="${ONBOARD_CONTRADICTION_GRACE:-$ONBOARD_POLL_SECONDS}"
KEEP="${KEEP:-1}"
OUT="${1:-}"

PROJECT="${TENANT:+h-flock-${TENANT}}"
CONTAINER="${PROJECT:+${PROJECT}-tenant-1}"
OWNED=0
LOG_CURSOR=0
PROMPT_STREAM_ID=""
WORK=""
RUN_SUMMARY=""
API_TOKEN_CREATED=""

onboarding_incomplete() {
  echo "ONBOARDING incomplete reason=$1" >&2
  exit 100
}

onboarding_fail() {
  local count="$1" reason="$2" detail="${3:-}"
  echo "ONBOARDING fail failed=$count reason=$reason${detail:+ $detail}" >&2
  exit "$count"
}

onboarding_log_disagreement() {
  echo "ONBOARDING fail reason=log_disagrees_with_pane smes=$1" >&2
  exit 6
}

redact_stream() {
  PROVIDER_SECRET="${PROVIDER_TOKEN:-}" API_SECRET="${API_TOKEN_CREATED:-}" python3 -c '
import os,sys
data=sys.stdin.read()
for secret in (os.environ.get("PROVIDER_SECRET"), os.environ.get("API_SECRET")):
    if secret:
        data=data.replace(secret,"<redacted>")
sys.stdout.write(data)
'
}

capture_evidence() {
  [ -n "$OUT" ] && [ -d "$OUT" ] || return 0
  mkdir -p "$OUT/panes"
  : >"$OUT/roster.txt"
  : >"$OUT/windows.tsv"
  : >"$OUT/custody.jsonl"
  for agent in "$ARCHITECT" "${SME_LIST[@]:-}"; do
    [ -n "$agent" ] && : >"$OUT/panes/$agent.txt"
  done
  [ "$OWNED" = 1 ] || return 0
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | grep -q . || return 0

  docker exec "$CONTAINER" redis-cli --raw HGETALL "pod:${POD}:tenant:${TENANT}:roster" \
    >"$OUT/roster.txt" 2>/dev/null || true
  docker exec "$CONTAINER" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux \
    list-windows -t "$TENANT" -F $'#{window_name}\t#{window_id}\t#{pane_pid}' \
    >"$OUT/windows.tsv" 2>/dev/null || true
  local resolved_map="" agent resolved_name
  for agent in "$ARCHITECT" "${SME_LIST[@]:-}"; do
    [ -n "$agent" ] || continue
    resolved_name="$(docker exec "$CONTAINER" redis-cli --raw GET \
      "pod:${POD}:tenant:${TENANT}:agent:${agent}:provider" 2>/dev/null || true)"
    resolved_map+="${resolved_map:+,}${agent}=${resolved_name}"
  done
  RESOLVED_MAP="$resolved_map" \
    RESOLVED_URL="$(docker exec "$CONTAINER" printenv "PROVIDER_${provider_upper}_URL" 2>/dev/null || true)" \
    RESOLVED_MODEL="$(docker exec "$CONTAINER" printenv "PROVIDER_${provider_upper}_MODEL" 2>/dev/null || true)" \
    python3 - "$OUT/provider.json" <<'PY'
import json,os,sys
path=sys.argv[1]
try: evidence=json.load(open(path,encoding="utf-8"))
except Exception: evidence={}
evidence["resolved"]={
  "agents":dict(pair.split("=",1) for pair in os.environ.get("RESOLVED_MAP","").split(",") if "=" in pair),
  "url":os.environ.get("RESOLVED_URL") or None,
  "model":os.environ.get("RESOLVED_MODEL") or None,
}
with open(path,"w",encoding="utf-8") as handle:
    json.dump(evidence,handle,separators=(",",":"))
    handle.write("\n")
PY
  for agent in "$ARCHITECT" "${SME_LIST[@]:-}"; do
    [ -n "$agent" ] || continue
    docker exec "$CONTAINER" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux \
      capture-pane -p -J -t "${TENANT}:${agent}" -S - 2>/dev/null \
      | redact_stream >"$OUT/panes/$agent.txt" || true
  done

  if [ -n "$WORK" ] && [ -f "$WORK/container.log" ]; then
    local summary="$WORK/final-summary.json"
    python3 container/scenarios/onboarding-custody.py "$WORK/container.log" \
      --after-line "$LOG_CURSOR" --source "$ARCHITECT" \
      --destination "${SME_LIST[0]}" --destination "${SME_LIST[1]}" >"$summary" 2>/dev/null || true
    python3 - "$summary" "$WORK/container.log" "$LOG_CURSOR" "$PROMPT_STREAM_ID" <<'PY' >"$OUT/custody.jsonl"
import json,sys
path,log_path,cursor,prompt=sys.argv[1:5]
try: summary=json.load(open(path,encoding="utf-8"))
except Exception: summary={"records":[]}
ids=set(summary.get("stream_ids",[]))
if prompt: ids.add(prompt)
try:
    lines=open(log_path,encoding="utf-8",errors="replace")
except Exception:
    lines=[]
for number,line in enumerate(lines,start=1):
    if number <= int(cursor) or not line.lstrip().startswith("{"): continue
    try: row=json.loads(line)
    except Exception: continue
    if row.get("stream_id") in ids: print(json.dumps(row,separators=(",",":")))
PY
  fi
}

print_teardown() {
  if [ "$OWNED" = 1 ]; then
    . container/flock-compose.sh 2>/dev/null || true
    flock_compose_args "$TENANT"
    printf 'TEARDOWN command='
    printf '%q ' docker compose -p "$PROJECT" --env-file "$TENANT_ENV_FILE" "${FLOCK_COMPOSE_ARGS[@]}" down -v
    echo
  elif [ -n "$PROJECT" ]; then
    echo "TEARDOWN unavailable reason=tenant_not_owned project=$PROJECT"
  else
    echo "TEARDOWN unavailable reason=tenant_required"
  fi
}

finalize() {
  local rc="$?"
  trap - EXIT INT TERM
  capture_evidence
  if [ "$OWNED" = 1 ] && [ "$KEEP" = 0 ]; then
    . container/flock-compose.sh 2>/dev/null || true
    flock_compose_args "$TENANT"
    docker compose -p "$PROJECT" --env-file "$TENANT_ENV_FILE" "${FLOCK_COMPOSE_ARGS[@]}" down -v >/dev/null 2>&1 || true
    rm -rf -- "$TENANT_DIR"
  fi
  print_teardown
  [ -n "$WORK" ] && rm -rf "$WORK"
  exit "$rc"
}
interrupted() { onboarding_incomplete interrupted; }
trap finalize EXIT
trap interrupted INT TERM

[ -n "$TENANT" ] || onboarding_incomplete tenant_required
[ -n "$OUT" ] || onboarding_incomplete output_dir_required
case "$KEEP" in 0|1) ;; *) onboarding_incomplete invalid_keep ;; esac
[[ "$ONBOARD_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || onboarding_incomplete invalid_timeout
[[ "$ONBOARD_CONTRADICTION_GRACE" =~ ^[1-9][0-9]*$ ]] \
  && [ "$ONBOARD_CONTRADICTION_GRACE" -le 30 ] \
  || onboarding_incomplete invalid_contradiction_grace
[ "$ONBOARD_CONTRADICTION_GRACE" -le "$ONBOARD_TIMEOUT" ] \
  || onboarding_incomplete contradiction_grace_exceeds_timeout
echo "ONBOARDING_TIMING timeout_seconds=$ONBOARD_TIMEOUT contradiction_grace_seconds=$ONBOARD_CONTRADICTION_GRACE effective_deadline_seconds=$((ONBOARD_TIMEOUT + ONBOARD_CONTRADICTION_GRACE))"
for value in "$POD" "$TENANT" "$ARCHITECT" "$PROVIDER_NAME"; do
  [[ "$value" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || onboarding_incomplete invalid_name
done
read -r -a SME_LIST <<<"$SMES"
[ "${#SME_LIST[@]}" -eq 2 ] || onboarding_incomplete expected_two_smes
[ "${SME_LIST[0]}" != "${SME_LIST[1]}" ] || onboarding_incomplete duplicate_smes
for sme in "${SME_LIST[@]}"; do
  [[ "$sme" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || onboarding_incomplete invalid_name
  [ "$sme" != "$ARCHITECT" ] || onboarding_incomplete duplicate_agents
done

OUT="$(realpath -m "$OUT")"
case "$OUT/" in "$ROOT/"*) onboarding_incomplete output_inside_repo;; esac
if [ -d "$OUT" ] && find "$OUT" -mindepth 1 -print -quit | grep -q .; then
  onboarding_incomplete output_not_empty
fi
mkdir -p "$OUT"
WORK="$(mktemp -d)"

provider_upper="$(printf '%s' "$PROVIDER_NAME" | tr '[:lower:]-' '[:upper:]_')"
url_var="PROVIDER_${provider_upper}_URL"
model_var="PROVIDER_${provider_upper}_MODEL"
token_var="PROVIDER_${provider_upper}_TOKEN"
small_var="PROVIDER_${provider_upper}_SMALL_MODEL"
PROVIDER_URL="${!url_var:-}"
PROVIDER_MODEL="${!model_var:-}"
PROVIDER_TOKEN="${!token_var:-}"
PROVIDER_SMALL_MODEL="${!small_var:-}"
[ -n "$PROVIDER_URL" ] || onboarding_incomplete provider_url_required
[ -n "$PROVIDER_MODEL" ] || onboarding_incomplete provider_model_required
for value in "$PROVIDER_URL" "$PROVIDER_MODEL" "$PROVIDER_TOKEN" "$PROVIDER_SMALL_MODEL"; do
  case "$value" in *$'\n'*|*$'\r'*) onboarding_incomplete invalid_provider_value;; esac
done
PROVIDER_URL="${PROVIDER_URL%/}"
PROVIDER_URL="${PROVIDER_URL%/v1}"

PROVIDER_URL="$PROVIDER_URL" PROVIDER_MODEL="$PROVIDER_MODEL" PROVIDER_NAME="$PROVIDER_NAME" \
  PROVIDER_HAS_TOKEN="$([ -n "$PROVIDER_TOKEN" ] && echo yes || echo no)" \
  PROVIDER_SMALL_MODEL="$PROVIDER_SMALL_MODEL" python3 - <<'PY' >"$OUT/provider.json"
import json,os
print(json.dumps({
  "name":os.environ["PROVIDER_NAME"], "url":os.environ["PROVIDER_URL"],
  "model":os.environ["PROVIDER_MODEL"],
  "small_model":os.environ.get("PROVIDER_SMALL_MODEL") or None,
  "token":"<redacted>" if os.environ["PROVIDER_HAS_TOKEN"] == "yes" else None,
},separators=(",",":")))
PY

PROVIDER_URL="$PROVIDER_URL" PROVIDER_MODEL="$PROVIDER_MODEL" PROVIDER_TOKEN="$PROVIDER_TOKEN" \
  python3 - <<'PY'
import json,os,urllib.request
url=os.environ["PROVIDER_URL"]+"/v1/models"
req=urllib.request.Request(url)
token=os.environ.get("PROVIDER_TOKEN")
if token: req.add_header("Authorization","Bearer "+token)
try:
    with urllib.request.urlopen(req,timeout=10) as response:
        data=json.load(response)
except Exception:
    raise SystemExit(1)
models={str(row.get("id")) for row in data.get("data",[]) if row.get("id") is not None}
raise SystemExit(0 if os.environ["PROVIDER_MODEL"] in models else 2)
PY
endpoint_rc="$?"
case "$endpoint_rc" in
  0) ;;
  2) onboarding_incomplete provider_model_not_served ;;
  *) onboarding_incomplete endpoint_unreachable ;;
esac

if [ -n "${AGENT_CLIS:-}" ]; then
  IFS=',' read -ra requested_clis <<<"$AGENT_CLIS"
  for pair in "${requested_clis[@]}"; do
    [ "${pair#*=}" = claude ] || onboarding_incomplete wrong_cli
  done
fi
command -v docker >/dev/null 2>&1 || onboarding_incomplete docker_required

existing="$({
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"
  docker network ls -q --filter "label=com.docker.compose.project=$PROJECT"
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT"
} 2>/dev/null | head -1)"
[ -z "$existing" ] || onboarding_incomplete tenant_exists
OWNED=1

session_port="$(python3 - <<'PY'
import socket
for port in range(8081,65536):
    sock=socket.socket()
    try: sock.bind(("127.0.0.1",port))
    except OSError: sock.close(); continue
    sock.close(); print(port); break
PY
)"
[ -n "$session_port" ] || onboarding_incomplete session_port_unavailable
API_TOKEN_CREATED="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')"
umask 077
. container/flock-compose.sh 2>/dev/null || onboarding_incomplete compose_helper_missing
flock_compose_args "$TENANT" || onboarding_incomplete invalid_tenant
mkdir -p "$TENANT_DIR"
{
  echo "POD=$POD"
  echo "TENANT=$TENANT"
  echo "AGENTS=$ARCHITECT:tmux,${SME_LIST[0]}:tmux,${SME_LIST[1]}:tmux"
  echo "FLOCK_ACCOUNTS=default"
  echo "AGENT_CLIS="
  echo "AGENT_PROVIDERS=$ARCHITECT=$PROVIDER_NAME,${SME_LIST[0]}=$PROVIDER_NAME,${SME_LIST[1]}=$PROVIDER_NAME"
  echo "API_TOKEN=$API_TOKEN_CREATED"
  echo "API_ENABLED=0"
  echo "API_HOST=127.0.0.1"
  echo "SESSION_HOST=127.0.0.1"
  echo "SESSION_PORT=$session_port"
  echo "PROVIDER_${provider_upper}_URL=$PROVIDER_URL"
  echo "PROVIDER_${provider_upper}_MODEL=$PROVIDER_MODEL"
  [ -n "$PROVIDER_TOKEN" ] && echo "PROVIDER_${provider_upper}_TOKEN=$PROVIDER_TOKEN"
  [ -n "$PROVIDER_SMALL_MODEL" ] && echo "PROVIDER_${provider_upper}_SMALL_MODEL=$PROVIDER_SMALL_MODEL"
  echo "PROVIDER_${provider_upper}_KIND=vllm"
} >"$TENANT_ENV_FILE"
chmod 600 "$TENANT_ENV_FILE"

. container/flock-image.sh 2>/dev/null || true
if declare -f flock_image_tag >/dev/null; then
  export FLOCK_IMAGE="$(flock_image_tag)"
  BUILD_FLAG="$(flock_build_flag)"
else
  BUILD_FLAG=--build
fi
docker compose -p "$PROJECT" --env-file "$TENANT_ENV_FILE" "${FLOCK_COMPOSE_ARGS[@]}" up -d ${BUILD_FLAG} \
  || onboarding_fail 1 tenant_start_failed

health=""
for _ in $(seq 1 90); do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)"
  [ "$health" = healthy ] && break
  [ "$health" = unhealthy ] && break
  sleep 1
done

FAILED=0
expect_value() {
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then echo "  ok $label"; else echo "  fail $label expected=$want got=${got:-missing}" >&2; FAILED=$((FAILED+1)); fi
}
expect_value tenant_health healthy "$health"
switch_count="$(docker exec "$CONTAINER" pgrep -f '[p]ython3 -m flock.switch' 2>/dev/null | wc -l | tr -d ' ')"
tmux_reconciler_count="$(docker exec "$CONTAINER" pgrep -f '[p]ython3 -m flock.tmux_reconciler' 2>/dev/null | wc -l | tr -d ' ')"
expect_value switch_count 1 "$switch_count"
expect_value tmux_reconciler_count 1 "$tmux_reconciler_count"

TMUX=(docker exec "$CONTAINER" env TMUX_TMPDIR=/home/ubuntu/.flock/tmux tmux)
ROSTER="pod:${POD}:tenant:${TENANT}:roster"
for agent in "$ARCHITECT" "${SME_LIST[@]}"; do
  expect_value "$agent roster" tmux "$(docker exec "$CONTAINER" redis-cli --raw HGET "$ROSTER" "$agent" 2>/dev/null || true)"
  window_count="$("${TMUX[@]}" list-windows -t "$TENANT" -F '#{window_name}' 2>/dev/null | awk -v a="$agent" '$0==a' | wc -l | tr -d ' ')"
  expect_value "$agent window_count" 1 "$window_count"
  launch="$(docker exec "$CONTAINER" redis-cli --raw GET "pod:${POD}:tenant:${TENANT}:agent:${agent}:launch" 2>/dev/null || true)"
  expect_value "$agent cli" claude "$launch"
  provider="$(docker exec "$CONTAINER" redis-cli --raw GET "pod:${POD}:tenant:${TENANT}:agent:${agent}:provider" 2>/dev/null || true)"
  expect_value "$agent provider" "$PROVIDER_NAME" "$provider"
done
expect_value provider_url "$PROVIDER_URL" "$(docker exec "$CONTAINER" printenv "PROVIDER_${provider_upper}_URL" 2>/dev/null || true)"
expect_value provider_model "$PROVIDER_MODEL" "$(docker exec "$CONTAINER" printenv "PROVIDER_${provider_upper}_MODEL" 2>/dev/null || true)"

PROHIBITED='^(API_TOKEN|REDIS_PASSWORD|REDISCLI_AUTH|REDIS_URL)='
credential_names="$("${TMUX[@]}" show-environment -g 2>/dev/null | grep -E "$PROHIBITED" | cut -d= -f1 || true)"
[ -z "$credential_names" ] || { echo "  fail tmux_global exposed_names=$(printf '%s' "$credential_names" | tr '\n' ',')" >&2; FAILED=$((FAILED+1)); }
for agent in "$ARCHITECT" "${SME_LIST[@]}"; do
  pane_pid="$("${TMUX[@]}" list-panes -t "${TENANT}:${agent}" -F '#{pane_pid}' 2>/dev/null | head -1)"
  [ -n "$pane_pid" ] || { echo "  fail $agent pane_pid missing" >&2; FAILED=$((FAILED+1)); continue; }
  credential_names="$(docker exec "$CONTAINER" sh -c "tr '\0' '\n' </proc/$pane_pid/environ" 2>/dev/null | grep -E "$PROHIBITED" | cut -d= -f1 || true)"
  [ -z "$credential_names" ] || { echo "  fail $agent exposed_names=$(printf '%s' "$credential_names" | tr '\n' ',')" >&2; FAILED=$((FAILED+1)); }
done
[ "$FAILED" = 0 ] || onboarding_fail "$FAILED" setup_or_plumbing

docker logs "$CONTAINER" >"$WORK/container.log" 2>&1 || onboarding_incomplete custody_unavailable
LOG_CURSOR="$(wc -l <"$WORK/container.log" | tr -d ' ')"
run_id="$(date +%s)-$$-$RANDOM"
marker="onboarding-${run_id}"
prompt="Read /workdir/${ARCHITECT}/AGENTS.md and onboard ${SME_LIST[0]} and ${SME_LIST[1]}. Compose one ordinary message for each SME and include this exact marker in each body: ${marker}. To keep each body out of shell parsing, write it to a file and send it with the tenant command office send -a NAME --file PATH, replacing NAME and PATH for that SME."
send_output="$(docker exec -e POD="$POD" -e TENANT="$TENANT" -e SOURCE="${SME_LIST[0]}" \
  -e DESTINATION="$ARCHITECT" -e PROMPT="$prompt" "$CONTAINER" python3 -c '
import contextlib,os,redis
from flock.bus.doors import send
r=redis.Redis.from_url(os.environ.get("REDIS_URL","redis://127.0.0.1:6379/0"))
with open("/proc/1/fd/1","w") as custody,contextlib.redirect_stdout(custody):
    sid=send(r,pod=os.environ["POD"],tenant=os.environ["TENANT"],source=os.environ["SOURCE"],destination=os.environ["DESTINATION"],kind="Message",payload={"text":os.environ["PROMPT"]},module="onboarding-integration")
print("STREAM_ID="+sid)
' 2>/dev/null || true)"
PROMPT_STREAM_ID="$(printf '%s\n' "$send_output" | sed -n 's/^STREAM_ID=//p' | tail -1)"
[ -n "$PROMPT_STREAM_ID" ] || onboarding_fail 1 prompt_send_failed

deadline=$((SECONDS + ONBOARD_TIMEOUT))
OBSERVED=0
OBSERVED_DESTINATIONS=()
PANE_DISAGREEMENTS=()
observe_onboarding() {
  docker logs "$CONTAINER" >"$WORK/container.log" 2>&1 || onboarding_incomplete custody_unavailable
  prompt_dead="$(python3 - "$WORK/container.log" "$LOG_CURSOR" "$PROMPT_STREAM_ID" <<'PY'
import json,sys
path,cursor,sid=sys.argv[1],int(sys.argv[2]),sys.argv[3]
dead=0
for number,line in enumerate(open(path,encoding="utf-8",errors="replace"),start=1):
    if number <= cursor or not line.lstrip().startswith("{"): continue
    try: row=json.loads(line)
    except Exception: continue
    dead += row.get("stream_id") == sid and row.get("event") == "dead_lettered"
print(dead)
PY
)"
  [ "$prompt_dead" = 0 ] || onboarding_fail "$prompt_dead" prompt_dead_lettered
  local marked_args=() previous_args=() sme pane previously_seen observed_sme
  for sme in "${SME_LIST[@]}"; do
    previously_seen=0
    for observed_sme in "${OBSERVED_DESTINATIONS[@]}"; do
      [ "$observed_sme" = "$sme" ] && previously_seen=1
    done
    if [ "$previously_seen" = 1 ]; then
      previous_args+=(--previously-observed "$sme")
      continue
    fi
    pane="$("${TMUX[@]}" capture-pane -p -J -t "${TENANT}:${sme}" -S - 2>/dev/null || true)"
    case "$pane" in *"$marker"*) marked_args+=(--marked-destination "$sme");; esac
  done
  RUN_SUMMARY="$(python3 container/scenarios/onboarding-custody.py "$WORK/container.log" \
    --after-line "$LOG_CURSOR" --source "$ARCHITECT" \
    --destination "${SME_LIST[0]}" --destination "${SME_LIST[1]}" \
    "${marked_args[@]}" "${previous_args[@]}")" \
    || onboarding_incomplete custody_unreadable
  parse_failures="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["parse_failures"])' <<<"$RUN_SUMMARY")"
  [ "$parse_failures" = 0 ] || onboarding_incomplete malformed_custody_json
  terminal_without_sent="$(python3 -c 'import json,sys;print(len(json.load(sys.stdin)["terminal_without_sent"]))' <<<"$RUN_SUMMARY")"
  [ "$terminal_without_sent" = 0 ] || onboarding_incomplete incomplete_custody_sequence
  dead_count="$(python3 -c 'import json,sys;print(len(json.load(sys.stdin)["dead_stream_ids"]))' <<<"$RUN_SUMMARY")"
  [ "$dead_count" = 0 ] || onboarding_fail "$dead_count" onboarding_dead_lettered

  mapfile -t OBSERVED_DESTINATIONS < <(python3 -c 'import json,sys;print("\n".join(json.load(sys.stdin)["observed_destinations"]))' <<<"$RUN_SUMMARY")
  OBSERVED="${#OBSERVED_DESTINATIONS[@]}"
  mapfile -t PANE_DISAGREEMENTS < <(python3 -c 'import json,sys;print("\n".join(json.load(sys.stdin)["pane_disagreements"]))' <<<"$RUN_SUMMARY")
}

while [ "$SECONDS" -lt "$deadline" ]; do
  observe_onboarding
  if [ "$OBSERVED" = 2 ]; then
    echo "ONBOARDING pass"
    exit 0
  fi
  sleep "$ONBOARD_POLL_SECONDS"
done

finish_onboarding_observation() {
  # Custody may precede pane rendering briefly, so disagreement is only a
  # verdict after one final observation at the deadline. At that point an
  # opened record without the run marker is an apparent contradiction between
  # the log and the real pane, not an unobserved model choice.
  observe_onboarding
  if [ "$OBSERVED" = 2 ]; then
    echo "ONBOARDING pass"
    exit 0
  fi
  if [ "${#PANE_DISAGREEMENTS[@]}" -gt 0 ]; then
    # Reserve one bounded last look for the strongest verdict. Ordinary silence
    # gets no deadline extension; only an apparent contradiction does. The
    # default is derived from the normal poll cadence so those windows agree.
    sleep "$ONBOARD_CONTRADICTION_GRACE"
    observe_onboarding
    if [ "$OBSERVED" = 2 ]; then
      echo "ONBOARDING pass"
      exit 0
    fi
  fi
  if [ "${#PANE_DISAGREEMENTS[@]}" -gt 0 ]; then
    disagreement_smes="$(IFS=,; echo "${PANE_DISAGREEMENTS[*]}")"
    onboarding_log_disagreement "$disagreement_smes"
  fi
  onboarding_incomplete onboarding_not_observed
}
finish_onboarding_observation
