#!/usr/bin/env bash
# Start one tenant's services in dependency order.
set -euo pipefail

# Shell lifecycle events need the same durable mirror as Python log records.
export FLOCK_EVENT_LOG_PATH="${FLOCK_EVENT_LOG_PATH:-/home/ubuntu/.flock/events/events.jsonl}"
event_log_dir="$(dirname "$FLOCK_EVENT_LOG_PATH")"

# The image is unprivileged; incompatible mount ownership is a deployment error.
if ! mkdir -p "$event_log_dir" || ! touch "$FLOCK_EVENT_LOG_PATH"; then
  echo "entrypoint: FLOCK_EVENT_LOG_PATH '$FLOCK_EVENT_LOG_PATH' is not writable" >&2
  exit 1
fi

# A runtime logging failure must not take the tenant down.
emit_event() {
  printf '%s\n' "$1"
  { printf '%s\n' "$1" >> "$FLOCK_EVENT_LOG_PATH"; } 2>/dev/null || true
}

validate_segment() {
  local var="$1"
  local val="${!var:-}"
  if [[ ! "$val" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]]; then
    echo "entrypoint: $var must be lowercase alphanumeric/hyphens (1-63 chars, starting with letter or digit)" >&2
    return 1
  fi
  if [[ "$val" =~ ^[0-9]+$ ]]; then
    echo "entrypoint: $var cannot be all digits" >&2
    return 1
  fi
  case "$val" in
    pod|tenant|agent|all)
      echo "entrypoint: $var cannot be reserved word '$val'" >&2
      return 1
      ;;
  esac
  return 0
}

require() {
  local missing=0
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      echo "entrypoint: $var is required" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || exit 1
}

# TENANT_ACCESS_TOKEN authenticates both network services. Keeping one required
# credential avoids a terminal process starting accidentally without protection.
require POD TENANT ROSTER_SEED TENANT_ACCESS_TOKEN
validate_segment POD
validate_segment TENANT

IFS=',' read -ra _agent_entries <<< "$ROSTER_SEED"
[ "${#_agent_entries[@]}" -gt 0 ] || { echo "entrypoint: ROSTER_SEED cannot be empty" >&2; exit 1; }
for _entry in "${_agent_entries[@]}"; do
  _name="${_entry%%:*}"
  _port_type="${_entry#*:}"
  if [ "$_name" = "$_entry" ] || [ -z "$_port_type" ]; then
    echo "entrypoint: ROSTER_SEED entry '$_entry' is not name:port_type" >&2
    exit 1
  fi
  if [[ ! "$_name" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || [[ "$_name" =~ ^[0-9]+$ ]] \
    || [ "$_name" = "pod" ] || [ "$_name" = "tenant" ] || [ "$_name" = "agent" ] \
    || [ "$_name" = "all" ] || [ "$_name" = "api" ] || [ "$_name" = "control" ]; then
    echo "entrypoint: ROSTER_SEED entry name '$_name' must be lowercase alphanumeric/hyphens (not all digits or reserved)" >&2
    exit 1
  fi
done

# Keep the credential out of the tmux server environment inherited by agents.
tenant_access_token="$TENANT_ACCESS_TOKEN"
unset TENANT_ACCESS_TOKEN

export TMUX_SESSION="${TMUX_SESSION:-$TENANT}"

# Socket access permits send-keys into every pane, so its directory is private.
mkdir -p "$TMUX_TMPDIR"
chmod 700 "$TMUX_TMPDIR"

pids=()
critical_pid=""
start_critical_service() {
  local service_name="$1"; shift
  "$@" &
  critical_pid=$!
  pids+=("$critical_pid")
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"critical_service_started\",\"service\":\"$service_name\",\"pid\":$critical_pid}"
}

start_supervised_service() {
  local service_name="$1"; shift
  /usr/local/bin/supervise-service.sh "$service_name" "$@" &
  local supervisor_pid=$!
  pids+=("$supervisor_pid")
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"supervisor_started\",\"service\":\"$service_name\",\"pid\":$supervisor_pid}"
}

start_optional_client() {
  local client_name="$1"; shift
  (
    "$@" || {
      local exit_code=$?
      emit_event "{\"module\":\"client\",\"writer\":\"$client_name\",\"event\":\"failed\",\"reason\":\"exit=$exit_code\"}"
    }
  ) &
  local client_pid=$!
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"started\",\"reason\":\"client $client_name pid=$client_pid\"}"
}

# Each supervisor forwards TERM to its current child.
shutdown() {
  local exit_code=$?
  trap - EXIT INT TERM
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"stopped\",\"reason\":\"exit=$exit_code\"}"
  kill "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
  exit "$exit_code"
}
trap shutdown EXIT INT TERM

# Validate host-side publication separately from container listen addresses.
for service_prefix in API TERMINAL; do
  # Disabled services have no publication surface.
  [ "$service_prefix" = "API" ] && [ "${API_SERVICE_ENABLED:-0}" = "0" ] && continue
  publish_address_var="${service_prefix}_PUBLISH_ADDRESS"
  publish_address="${!publish_address_var:-}"
  [ -z "$publish_address" ] && continue
  # The process cannot infer publication from its container listen address.
  [ "$service_prefix" = "API" ] && export API_IS_PUBLISHED=1
  tls_cert_var="${service_prefix}_TLS_CERT"
  tls_key_var="${service_prefix}_TLS_KEY"
  tls_cert="${!tls_cert_var:-}"
  tls_key="${!tls_key_var:-}"
  [ "$service_prefix" = "TERMINAL" ] && [ -z "$tls_cert" ] && tls_cert="${API_TLS_CERT:-}" && tls_key="${API_TLS_KEY:-}"
  loopback=$(python3 -c '
import ipaddress, sys
host = sys.argv[1].strip("[]")
try:
    print("1" if ipaddress.ip_address(host).is_loopback else "0")
except ValueError:
    print("1" if host.lower() == "localhost" else "0")
' "$publish_address")
  if [ "$loopback" = "0" ] && [ -z "$tls_cert$tls_key" ] && [ "${ALLOW_INSECURE_PUBLISH:-0}" != "1" ]; then
    echo "entrypoint: the ${service_prefix,,} service is published on '$publish_address' without TLS." >&2
    echo "  The bearer token would cross the network in clear text. Either set" >&2
    echo "  ${service_prefix}_TLS_CERT and ${service_prefix}_TLS_KEY, or publish to 127.0.0.1 only," >&2
    echo "  or set ALLOW_INSECURE_PUBLISH=1 in this tenant's .env to accept it." >&2
    exit 1
  fi
done
export FLOCK_PUBLISH_POLICY_VALIDATED=1

# ── redis ─────────────────────────────────────────────────────────────────────
# AOF persists durable state; boot separately purges ephemeral transport keys.
redis_listen_address="${REDIS_LISTEN_ADDRESS:-127.0.0.1}"
redis_password="${REDIS_PASSWORD:-}"
redis_data_dir="${REDIS_DATA_DIR:-/tmp}"

is_loopback=$(python3 -c '
import ipaddress, sys
host = sys.argv[1]
try:
    print("1" if ipaddress.ip_address(host).is_loopback else "0")
except ValueError:
    print("1" if host in ("localhost", "127.0.0.1", "::1") else "0")
' "$redis_listen_address")

if [ "$is_loopback" = "0" ] && [ -z "$redis_password" ]; then
  echo "entrypoint: REDIS_PASSWORD is required when REDIS_LISTEN_ADDRESS is not loopback ('$redis_listen_address')" >&2
  exit 1
fi

redis_connection_host="$redis_listen_address"
case "$redis_connection_host" in
  0.0.0.0) redis_connection_host=127.0.0.1 ;;
  ::) redis_connection_host=::1 ;;
esac

redis_cmd=(redis-server --bind "$redis_listen_address" --port 6379 --save '' --appendonly yes --appendfsync everysec --dir "$redis_data_dir")
if [ -n "$redis_password" ]; then
  redis_cmd+=(--requirepass "$redis_password")
  export REDISCLI_AUTH="$redis_password"
fi
if [ -z "${REDIS_URL:-}" ]; then
  export REDIS_URL="$(python3 -c '
import ipaddress, sys
from urllib.parse import quote

password, host = sys.argv[1:]
try:
    rendered_host = f"[{host}]" if ipaddress.ip_address(host).version == 6 else host
except ValueError:
    rendered_host = host
auth = f":{quote(password, safe="")}@" if password else ""
print(f"redis://{auth}{rendered_host}:6379/0")
' "$redis_password" "$redis_connection_host")"
fi

# redis-cli exits zero on NOAUTH, so readiness must also require PONG.
redis_cli() {
  if [ -n "$redis_password" ]; then
    redis-cli -h "$redis_connection_host" -a "$redis_password" --no-auth-warning "$@"
  else
    redis-cli -h "$redis_connection_host" "$@"
  fi
}

start_critical_service redis "${redis_cmd[@]}"
redis_deadline=$((SECONDS + ${REDIS_STARTUP_TIMEOUT_SECONDS:-30}))
until [ "$(redis_cli ping 2>/dev/null)" = "PONG" ]; do
  if [ "$SECONDS" -ge "$redis_deadline" ]; then
    echo "entrypoint: timed out waiting for Redis readiness" >&2
    exit 1
  fi
  sleep 0.2
done

# ── purge ephemeral transport keys ───────────────────────────────────────────
# At-most-once transport queues and locks must not survive a restart; durable
# boards and streams remain in AOF. Mirror the purge record to the event log.
purge_record=$(python3 -c '
import os, sys, redis
from flock.bus.resources import purge_transport
from flock.bus.connection import local_redis_url

url = os.environ.get("REDIS_URL")
if not url:
    pwd = os.environ.get("REDIS_PASSWORD", "")
    url = local_redis_url(pwd) if pwd else "redis://127.0.0.1:6379/0"

r = redis.from_url(url)
count = purge_transport(r, pod=os.environ["POD"], tenant=os.environ["TENANT"])
print(f"{{\"module\":\"container\",\"writer\":\"container\",\"event\":\"transport_purged\",\"count\":{count}}}")
')
emit_event "$purge_record"


# ── seed the roster ───────────────────────────────────────────────────────────
# HSET makes boot seeding idempotent; runtime membership uses the control plane.
roster_key="pod:${POD}:tenant:${TENANT}:roster"
IFS=',' read -ra roster_entries <<< "$ROSTER_SEED"
initial_agents=()
roster_fields=()
for roster_entry in "${roster_entries[@]}"; do
  participant_name="${roster_entry%%:*}"
  port_type="${roster_entry#*:}"
  if [ "$participant_name" = "$roster_entry" ] || [ -z "$port_type" ]; then
    echo "entrypoint: ROSTER_SEED entry '$roster_entry' is not name:port_type" >&2
    exit 1
  fi
  initial_agents+=("$participant_name")
  roster_fields+=("$participant_name" "$port_type")
done

# `control` receives lifecycle messages and has no tmux window.
roster_fields+=("api" "api")
roster_fields+=("control" "control")

redis_cli HSET "$roster_key" "${roster_fields[@]}" >/dev/null
# Preserve the lead before the roster hash loses seed ordering.
redis_cli SET "pod:${POD}:tenant:${TENANT}:lead" "${initial_agents[0]}" >/dev/null
emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"roster_seeded\",\"count\":$(( ${#roster_fields[@]} / 2 ))}"

# Persist setup's complete account list, including unassigned accounts.
if [ -n "${ACCOUNT_NAMES:-}" ]; then
  accounts_key="pod:${POD}:tenant:${TENANT}:accounts"
  redis_cli DEL "$accounts_key" >/dev/null
  IFS=',' read -ra _accounts <<< "$ACCOUNT_NAMES"
  for _account in "${_accounts[@]}"; do
    [ -n "$_account" ] && redis_cli SADD "$accounts_key" "$_account" >/dev/null
  done
fi

# Per-agent CLI, account, and provider are resources rather than roster fields.
map_agent_resources() {   # $1=map  $2=resource ; SETs pod:…:agent:<name>:<resource>
  local pair participant_name value
  IFS=',' read -ra pairs <<< "${1:-}"
  for pair in "${pairs[@]:-}"; do
    [ -n "$pair" ] || continue
    participant_name="${pair%%=*}"; value="${pair#*=}"
    [ -n "$participant_name" ] && [ -n "$value" ] && [ "$participant_name" != "$pair" ] || continue
    redis_cli SET "pod:${POD}:tenant:${TENANT}:agent:${participant_name}:$2" "$value" >/dev/null
  done
}
# AGENT_CLIS contains exceptions only, so seed the default before applying it.
for _i in "${!initial_agents[@]}"; do
  [ "${roster_fields[$(( _i * 2 + 1 ))]}" = "tmux" ] || continue
  redis_cli SET "pod:${POD}:tenant:${TENANT}:agent:${initial_agents[$_i]}:launch" claude >/dev/null
done

map_agent_resources "${AGENT_CLIS:-}" launch
map_agent_resources "${AGENT_ACCOUNTS:-}" account
map_agent_resources "${AGENT_PROVIDERS:-}" provider

# Non-default accounts need the image defaults and their own onboarding marker.
seed_account_dir() {
  local account_name="$1" c="/home/ubuntu/.claude-$1" x="/home/ubuntu/.codex-$1"
  [ "$account_name" = "default" ] && return 0
  mkdir -p "$c" "$x"
  for item in settings.json skills agents CLAUDE.md; do
    [ -e "/home/ubuntu/.claude/$item" ] && [ ! -e "$c/$item" ] && cp -r "/home/ubuntu/.claude/$item" "$c/" 2>/dev/null
  done
  for item in config.toml AGENTS.md; do
    [ -e "/home/ubuntu/.codex/$item" ] && [ ! -e "$x/$item" ] && cp -r "/home/ubuntu/.codex/$item" "$x/" 2>/dev/null
  done
  [ -f "$c/.claude.json" ] || printf '{\n  "hasCompletedOnboarding": true\n}\n' > "$c/.claude.json"
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"account_seeded\",\"reason\":\"$account_name\"}"
}
IFS=',' read -ra _account_pairs <<< "${AGENT_ACCOUNTS:-}"
for _pair in "${_account_pairs[@]:-}"; do
  [ -n "$_pair" ] && seed_account_dir "${_pair#*=}"
done

unset AGENT_CLIS AGENT_ACCOUNTS AGENT_PROVIDERS ACCOUNT_NAMES

# Agent windows receive derived AGENT_PEERS, not raw boot configuration.
unset ROSTER_SEED

# Hand Redis credentials only to infrastructure processes, never agent windows.
redis_url="${REDIS_URL:-redis://127.0.0.1:6379/0}"
unset REDIS_PASSWORD REDISCLI_AUTH REDIS_URL

# ── tmux host ─────────────────────────────────────────────────────────────────
# The tmux server passes this to windows; agent-only mode avoids host duplicates.
export FLOCK_WINDOW_LOG_PATH=/home/ubuntu/.flock/window.log.jsonl
export FLOCK_WINDOW_LOG_AGENT_ONLY=1
start_supervised_service tmuxhost env REDIS_URL="$redis_url" python3 -m flock.tmuxhost

# Wait for windows before the switch can dead-letter their first envelopes.
deadline=$((SECONDS + 30))
for agent in "${initial_agents[@]}"; do
  until tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
     && tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "entrypoint: timed out waiting for window '$agent'" >&2
      exit 1
    fi
    sleep 0.3
  done
done
emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"windows_ready\",\"count\":${#initial_agents[@]}}"

# Later services log directly to stdout and must not feed the tailed window log.
unset FLOCK_WINDOW_LOG_PATH FLOCK_WINDOW_LOG_AGENT_ONLY

# ── the rest ──────────────────────────────────────────────────────────────────
start_supervised_service switch env REDIS_URL="$redis_url" python3 -m flock.switch
# WATCHDOG_ENABLED controls alerts, not the telemetry hosted by this process.
start_supervised_service watchdog env REDIS_URL="$redis_url" python3 -m flock.watchdog
# Network services start last and receive the token by explicit handoff only.
# The API is opt-in because its shared token permits acting as any participant.
if [ "${API_SERVICE_ENABLED:-0}" != "0" ]; then
  start_supervised_service api env TENANT_ACCESS_TOKEN="$tenant_access_token" python3 -m flock.api
else
  emit_event '{"module":"container","writer":"container","event":"api_disabled","reason":"API_SERVICE_ENABLED is not 1"}'
fi
start_supervised_service terminal env TENANT_ACCESS_TOKEN="$tenant_access_token" python3 -m flock.session

# ── bundled clients ───────────────────────────────────────────────────────────
# The unattended Telegram client is optional and non-critical. The web client is
# operator-run because it has a separate security boundary.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  if [ "${API_SERVICE_ENABLED:-0}" = "0" ]; then
    emit_event '{"module":"container","writer":"container","event":"client_skipped","reason":"telegram configured but API_SERVICE_ENABLED is 0"}'
  else
    tg_args=(
      python3 -m clients.telegram.bot
      --api-url "http://127.0.0.1:${API_LISTEN_PORT:-8080}"
      --api-token "$tenant_access_token"
      --bot-token "$TELEGRAM_BOT_TOKEN"
      --cursor-file "/home/ubuntu/.flock/telegram.cursor.json"
    )
    [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg_args+=(--chat-id "$TELEGRAM_CHAT_ID")
    # Unset means the Dashboard button is absent.
    [ -n "${MINI_APP_URL:-}" ] && tg_args+=(--mini-app-url "$MINI_APP_URL")
    start_optional_client telegram "${tg_args[@]}"
  fi
fi

# Redis failure restarts the container so transport is purged before reconnect.
wait "$critical_pid"
