#!/usr/bin/env bash
# Brings up one tenant. Holds no logic of its own — it starts the modules in
# dependency order and gets out of the way (LLD-container §5, §8).
set -euo pipefail

# ⚠ The event log must outlive the container. Docker's json-file driver is
# deleted with it, so `docker compose down` used to destroy the only evidence a
# run happened. FLOCK_EVENT_LOG_PATH points at a mounted volume; `flock.bus.logging`
# mirrors every record it prints, and emit_event does the same for the container's own
# lifecycle lines, which are shell echoes and never reach Python.
#
# ⚠ Set BEFORE the first emit_event call and never unset — unlike FLOCK_WINDOW_LOG_PATH,
# which is unset at line ~294 because the switch TAILS that file and daemons
# writing to it would feed the tail loop back into itself. This file is tailed
# by nobody.
export FLOCK_EVENT_LOG_PATH="${FLOCK_EVENT_LOG_PATH:-/home/ubuntu/.flock/events/events.jsonl}"
event_log_dir="$(dirname "$FLOCK_EVENT_LOG_PATH")"

# The image runs unprivileged. A mounted path with incompatible ownership is a
# deployment error; fail clearly instead of assuming an unavailable privilege path.
if ! mkdir -p "$event_log_dir" || ! touch "$FLOCK_EVENT_LOG_PATH"; then
  echo "entrypoint: FLOCK_EVENT_LOG_PATH '$FLOCK_EVENT_LOG_PATH' is not writable" >&2
  exit 1
fi

# Print one record to stdout and to the durable mirror. Never fails the caller:
# a full or unwritable volume at runtime must not take the tenant down.
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

# Hold it out of the inherited environment from here on. The tmux server is
# started below and every agent window inherits the server's environment, so an
# exported TENANT_ACCESS_TOKEN ends up readable in every pane — and with the Command kind
# that makes any agent able to run arbitrary code in any other agent's window.
# Only the API and terminal processes need it, so only those processes get it.
tenant_access_token="$TENANT_ACCESS_TOKEN"
unset TENANT_ACCESS_TOKEN

export TMUX_SESSION="${TMUX_SESSION:-$TENANT}"

# Socket access is total — anything that can reach it can send-keys into any
# pane. The directory permissions are the whole boundary (LLD-tmux-host §4).
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

# A real container stop still tears down every independent supervisor. Each
# supervisor forwards TERM to its current child before exiting.
shutdown() {
  local exit_code=$?
  trap - EXIT INT TERM
  emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"stopped\",\"reason\":\"exit=$exit_code\"}"
  kill "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
  exit "$exit_code"
}
trap shutdown EXIT INT TERM

# ⚠ A listen address is not an exposure. Both network services listen on all
# container interfaces by design; host-side port publication decides whether
# plaintext leaves the machine. Validate that separate publish configuration here
# and pass the result via FLOCK_PUBLISH_POLICY_VALIDATED (LLD-container §3.1).
#
# Unset means not published at all — a bare `docker run` with no -p — which is
# why the default is loopback rather than 0.0.0.0.
for service_prefix in API TERMINAL; do
  # A service that is not started cannot leak a token, so it is not judged. Keep
  # this in step with the API_SERVICE_ENABLED guard further down.
  [ "$service_prefix" = "API" ] && [ "${API_SERVICE_ENABLED:-0}" = "0" ] && continue
  publish_address_var="${service_prefix}_PUBLISH_ADDRESS"
  publish_address="${!publish_address_var:-}"
  [ -z "$publish_address" ] && continue
  # The API service's per-client HMAC/CORS enforcement (LLD-api §6) is judged
  # against the same fact this loop already computes: API_PUBLISH_ADDRESS set at
  # all, not just non-loopback. A loopback-published service is still reachable by
  # anything on the container host, not only the container. Told to the process
  # the same way FLOCK_PUBLISH_POLICY_VALIDATED is: exported here, not re-derived
  # in-container, because API_LISTEN_ADDRESS is hardcoded 0.0.0.0 in the image
  # (Dockerfile) and cannot tell the process whether it was published.
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
# Loopback only and never published. AOF persistence enabled for durable boards
# and streams; ephemeral transport queues are purged at boot (BUILD-63).
redis_listen_address="${REDIS_LISTEN_ADDRESS:-127.0.0.1}"
redis_password="${REDIS_PASSWORD:-}"
redis_data_dir="${REDIS_DATA_DIR:-/tmp}"

# Refuse a non-loopback bind without a password (LLD-container §3).
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

# ⚠ redis-cli prints "NOAUTH Authentication required." and STILL EXITS 0, so a
# readiness probe passes while every command after it silently fails — a tenant
# that starts with an empty roster and no error. Every call goes through this.
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
# Ephemeral queues (ingress, egress, dead) and locks must not survive a restart.
# At-most-once delivery permits loss, and a stale envelope from an old wire
# version is worse than a lost one (DESIGN-layers §7, BUILD-63). Boards and
# streams survive via AOF; transport queues are purged here before anything
# starts consuming.
# ⚠ Through emit_event, not printed directly. This record is the proof that a restart
# discarded in-flight transport rather than replaying it, which is the whole
# argument that AOF persistence does not break at-most-once — so it is exactly
# the record that must survive teardown.
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
# Boot configuration seeds the roster before services start. Runtime membership
# changes use the control plane described in LLD-bus-and-switch §3.2. The roster
# is the MAC table: a HASH of participant -> port_type. HSET is idempotent, so
# bringing the container up twice converges (LLD-container §5).
#
# ROSTER_SEED is name:port_type pairs — ROSTER_SEED=backend:tmux,frontend:tmux,systems:tmux
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

# Fixed participants are roster rows like any other. `control` receives
# StartAgent/StopAgent messages and routes them to flock.control; it has no tmux
# window. `api` represents the API service.
roster_fields+=("api" "api")
roster_fields+=("control" "control")

redis_cli HSET "$roster_key" "${roster_fields[@]}" >/dev/null
# The HASH loses ROSTER_SEED ordering. Preserve authority while the ordered source is
# still in hand; no later command or override writes this derived value.
redis_cli SET "pod:${POD}:tenant:${TENANT}:lead" "${initial_agents[0]}" >/dev/null
emit_event "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"roster_seeded\",\"count\":$(( ${#roster_fields[@]} / 2 ))}"

# setup.sh is the authority for accounts. Persist the complete list rather than
# inferring it from derivative config directories or only assigned accounts.
if [ -n "${ACCOUNT_NAMES:-}" ]; then
  accounts_key="pod:${POD}:tenant:${TENANT}:accounts"
  redis_cli DEL "$accounts_key" >/dev/null
  IFS=',' read -ra _accounts <<< "$ACCOUNT_NAMES"
  for _account in "${_accounts[@]}"; do
    [ -n "$_account" ] && redis_cli SADD "$accounts_key" "$_account" >/dev/null
  done
fi

# Per-agent CLI and account, as exceptions only — "backend=codex", "frontend=work".
# Both land as agent resources rather than roster values: the roster is the MAC
# table and holds membership plus port_type, nothing else (LLD-bus-and-switch §3.2).
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
# ⚠ Default every tmux agent to claude BEFORE the exception maps are applied.
# setup.sh writes AGENT_CLIS only for agents that differ from the default, so a
# plain single-account install writes no AGENT_CLIS at all. Without this, no
# agent gets a launch key, tmuxhost builds every window as a bare shell, and the
# whole office comes up as three bash prompts with presence 'unknown'. Measured
# on a from-scratch install taking every default.
for _i in "${!initial_agents[@]}"; do
  [ "${roster_fields[$(( _i * 2 + 1 ))]}" = "tmux" ] || continue
  redis_cli SET "pod:${POD}:tenant:${TENANT}:agent:${initial_agents[$_i]}:launch" claude >/dev/null
done

map_agent_resources "${AGENT_CLIS:-}" launch
map_agent_resources "${AGENT_ACCOUNTS:-}" account
map_agent_resources "${AGENT_PROVIDERS:-}" provider

# An account is a config dir, and a fresh one is not an empty one — unseeded, an
# agent loses every default the image carries. Copy what the stock account has
# and write the first-run marker INSIDE the dir, because $HOME/.claude.json
# covers the default account only (PLAN-profiles.md §3).
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

# Held out of the environment for the same reason as ROSTER_SEED: the tmux server
# inherits it and every window inherits that.
unset AGENT_CLIS AGENT_ACCOUNTS AGENT_PROVIDERS ACCOUNT_NAMES

# Seeding is the only use of ROSTER_SEED. Hold it out of the environment from here:
# the tmux server is started below and every agent window inherits its
# environment, so an exported ROSTER_SEED put the raw seed string — VABs included,
# and the agent itself in the list — in front of every agent. Asked where its
# peers were, one read that, found it confusing, and went to redis-cli for a
# better answer. Peers reach a window as AGENT_PEERS, derived from the roster.
unset ROSTER_SEED

# Redis credentials belong to infrastructure processes, not agent windows.
# Keep the URL in a shell variable for explicit process handoff, then remove
# every credential-bearing variable before tmuxhost creates the tmux server.
# tmuxhost consumes REDIS_URL from its own environment before its first tmux
# call, so the server cannot inherit it either.
redis_url="${REDIS_URL:-redis://127.0.0.1:6379/0}"
unset REDIS_PASSWORD REDISCLI_AUTH REDIS_URL

# ── tmux host ─────────────────────────────────────────────────────────────────
# The tmux server inherits this and passes it to every agent window. tmuxhost
# itself has no AGENT_NAME, so FLOCK_WINDOW_LOG_AGENT_ONLY keeps its already-
# central lifecycle records out of the file and prevents duplicates.
export FLOCK_WINDOW_LOG_PATH=/home/ubuntu/.flock/window.log.jsonl
export FLOCK_WINDOW_LOG_AGENT_ONLY=1
start_supervised_service tmuxhost env REDIS_URL="$redis_url" python3 -m flock.tmuxhost

# Windows lead routes. LLD-bus-and-switch §3.2 names the one roster case that is
# not harmless: the switch routing to an agent whose window does not exist yet,
# whose first envelopes are then dead-lettered into nothing. Waiting here is the
# cheapest possible answer — the tmux service is already ahead, so nothing can race it.
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

# Only the tmux server and its windows retain these. Processes started below
# already write directly to container stdout and must not enter the tail file.
unset FLOCK_WINDOW_LOG_PATH FLOCK_WINDOW_LOG_AGENT_ONLY

# ── the rest ──────────────────────────────────────────────────────────────────
start_supervised_service switch env REDIS_URL="$redis_url" python3 -m flock.switch
# ⚠ ALWAYS started. WATCHDOG_ENABLED silences alerting, and the process decides
# that for itself — it also hosts ActivityTailer, PresenceSampler and
# DeliveryVerifier, which the API service, web console and Telegram bot all
# read. Gating the start here is what made the flag switch off telemetry three
# clients depend on.
start_supervised_service watchdog env REDIS_URL="$redis_url" python3 -m flock.watchdog
# No adapter here. It is not a service — the switch kicks `flock.port <agent>`
# per delivery and it exits (LLD-adapter-tmux §2). Starting one at boot would be
# the daemon this build exists to remove.
# Network services start last, so neither is reachable before the tenant is up
# (§5). The token is handed to these two processes and nothing else — it must
# not reach a tmux window, where the Command kind would make it root on every
# peer (§3).
# ⚠ The API service is OPT-IN. It is the widest surface the tenant has — one shared
# bearer token, and `as` on a post is a declaration rather than a credential
# (`api/app.py:617`), so any token holder can post as any enrolled client. A
# tenant whose agents only talk to each other over the bus does not need it, and
# an unpublished service is unreachable outside the container. Set
# API_SERVICE_ENABLED=1 to enable it.
if [ "${API_SERVICE_ENABLED:-0}" != "0" ]; then
  start_supervised_service api env TENANT_ACCESS_TOKEN="$tenant_access_token" python3 -m flock.api
else
  emit_event '{"module":"container","writer":"container","event":"api_disabled","reason":"API_SERVICE_ENABLED is not 1"}'
fi
start_supervised_service terminal env TENANT_ACCESS_TOKEN="$tenant_access_token" python3 -m flock.session

# ── bundled clients ───────────────────────────────────────────────────────────
# The Telegram bot is the one bundled client: unattended, so it belongs in the
# tenant, reaching the local REST API on 127.0.0.1:8080. It starts only when
# configured, and a client failure does not take down the tenant.
#
# clients/web is deliberately NOT started here — it is an operator tool with
# its own security boundary (shared secret, TLS, audit log) that a human starts
# deliberately, not a background process with a safe unattended default
# (docs/SPEC-bundled-clients-and-exposure.md).
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
    # ⚠ Unset means no button, not a broken one — clients/web itself is not
    # started here (comment above); MINI_APP_URL only ever names a URL the
    # operator started that server at themselves, elsewhere. See
    # clients/web/README.md's Mini App section for how that's set up.
    [ -n "${MINI_APP_URL:-}" ] && tg_args+=(--mini-app-url "$MINI_APP_URL")
    start_optional_client telegram "${tg_args[@]}"
  fi
fi

# Redis is deliberately the critical exception. Its exit ends the entrypoint so
# the container restart path can purge transport before any switch reconnects.
# Every other core service restarts behind its own independent supervisor.
wait "$critical_pid"
