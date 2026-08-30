#!/usr/bin/env bash
# Brings up one tenant. Holds no logic of its own — it starts the modules in
# dependency order and gets out of the way (LLD-container §5, §8).
set -euo pipefail

# ⚠ The custody log must outlive the container. Docker's json-file driver is
# deleted with it, so `docker compose down` used to destroy the only evidence a
# run happened. FLOCK_CUSTODY_FILE points at a mounted volume; `flock.bus.logging`
# mirrors every record it prints, and jlog does the same for the container's own
# lifecycle lines, which are shell echoes and never reach Python.
#
# ⚠ Set BEFORE the first jlog call and never unset — unlike FLOCK_LOG_FILE,
# which is unset at line ~294 because the switch TAILS that file and daemons
# writing to it would feed the tail loop back into itself. This file is tailed
# by nobody.
export FLOCK_CUSTODY_FILE="${FLOCK_CUSTODY_FILE:-/home/ubuntu/.flock/custody/custody.jsonl}"
custody_dir="$(dirname "$FLOCK_CUSTODY_FILE")"

# ⚠ Custody directory and file permissions:
# In cloned deployments (cp -r) or mounted volumes, file ownership may carry over
# from another user or root, preventing the container's unprivileged user from writing.
# Fix ownership/permissions via sudo if needed, and verify writability upfront.
if ! mkdir -p "$custody_dir" 2>/dev/null; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo mkdir -p "$custody_dir" 2>/dev/null || true
  fi
fi

if [ -d "$custody_dir" ]; then
  if [ ! -w "$custody_dir" ] || ([ -e "$FLOCK_CUSTODY_FILE" ] && [ ! -w "$FLOCK_CUSTODY_FILE" ]); then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      sudo chown -R "$(id -u):$(id -g)" "$custody_dir" 2>/dev/null || true
      sudo chmod 755 "$custody_dir" 2>/dev/null || true
      [ -e "$FLOCK_CUSTODY_FILE" ] && sudo chmod 644 "$FLOCK_CUSTODY_FILE" 2>/dev/null || true
    fi
  fi
fi

if ! touch "$FLOCK_CUSTODY_FILE" 2>/dev/null; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo touch "$FLOCK_CUSTODY_FILE" 2>/dev/null || true
    sudo chown "$(id -u):$(id -g)" "$FLOCK_CUSTODY_FILE" 2>/dev/null || true
    sudo chmod 644 "$FLOCK_CUSTODY_FILE" 2>/dev/null || true
  fi
fi

if [ ! -w "$FLOCK_CUSTODY_FILE" ]; then
  echo "entrypoint: FLOCK_CUSTODY_FILE '$FLOCK_CUSTODY_FILE' is not writable" >&2
  exit 1
fi

# Print one record to stdout and to the durable mirror. Never fails the caller:
# a full or unwritable volume at runtime must not take the tenant down.
jlog() {
  printf '%s\n' "$1"
  { printf '%s\n' "$1" >> "$FLOCK_CUSTODY_FILE"; } 2>/dev/null || true
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

# API_TOKEN is not optional: the api is the only mapped port and therefore the
# entire attack surface (LLD-container §3).
require POD TENANT AGENTS API_TOKEN
validate_segment POD
validate_segment TENANT

IFS=',' read -ra _agent_entries <<< "$AGENTS"
[ "${#_agent_entries[@]}" -gt 0 ] || { echo "entrypoint: AGENTS cannot be empty" >&2; exit 1; }
for _entry in "${_agent_entries[@]}"; do
  _name="${_entry%%:*}"
  _port_type="${_entry#*:}"
  if [ "$_name" = "$_entry" ] || [ -z "$_port_type" ]; then
    echo "entrypoint: AGENTS entry '$_entry' is not name:port_type" >&2
    exit 1
  fi
  if [[ ! "$_name" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || [[ "$_name" =~ ^[0-9]+$ ]] || [ "$_name" = "pod" ] || [ "$_name" = "tenant" ] || [ "$_name" = "agent" ] || [ "$_name" = "all" ]; then
    echo "entrypoint: AGENTS entry name '$_name' must be lowercase alphanumeric/hyphens (not all digits or reserved)" >&2
    exit 1
  fi
done

# Hold it out of the inherited environment from here on. The tmux server is
# started below and every agent window inherits the server's environment, so an
# exported API_TOKEN ends up readable in every pane — and with the Command kind
# that makes any agent able to run arbitrary code in any other agent's window.
# Only the api process needs it, so only the api process gets it.
api_token="$API_TOKEN"
unset API_TOKEN

export TMUX_SESSION="${TMUX_SESSION:-$TENANT}"

# Socket access is total — anything that can reach it can send-keys into any
# pane. The directory permissions are the whole boundary (LLD-tmux-reconciler §4).
mkdir -p "$TMUX_TMPDIR"
chmod 700 "$TMUX_TMPDIR"

pids=()
critical_pid=""
start_critical() {
  local name="$1"; shift
  "$@" &
  critical_pid=$!
  pids+=("$critical_pid")
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"critical_service_started\",\"service\":\"$name\",\"pid\":$critical_pid}"
}

start() {
  local name="$1"; shift
  /usr/local/bin/supervise-service.sh "$name" "$@" &
  local pid=$!
  pids+=("$pid")
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"supervisor_started\",\"service\":\"$name\",\"pid\":$pid}"
}

start_client() {
  local name="$1"; shift
  (
    "$@" || {
      local code=$?
      jlog "{\"module\":\"client\",\"writer\":\"$name\",\"event\":\"failed\",\"reason\":\"exit=$code\"}"
    }
  ) &
  local pid=$!
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"started\",\"reason\":\"client $name pid=$pid\"}"
}

# A real container stop still tears down every independent supervisor. Each
# supervisor forwards TERM to its current child before exiting.
shutdown() {
  local code=$?
  trap - EXIT INT TERM
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"stopped\",\"reason\":\"exit=$code\"}"
  kill "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
  exit "$code"
}
trap shutdown EXIT INT TERM

# ⚠ A bind is not an exposure. Both doors bind 0.0.0.0 *inside* the container by
# design (Dockerfile) — what decides whether plaintext leaves this machine is the
# port mapping, which the door process cannot see. So the judgement is made here,
# once, from the published host compose passes in, and the doors are told the
# answer via FLOCK_ALLOW_PLAINTEXT (LLD-container §3.1).
#
# Unset means not published at all — a bare `docker run` with no -p — which is
# why the default is loopback rather than 0.0.0.0.
for door in API SESSION; do
  # A door that is not started cannot leak a token, so it is not judged. Keep
  # this in step with the API_ENABLED guard further down.
  [ "$door" = "API" ] && [ "${API_ENABLED:-0}" = "0" ] && continue
  eval "published=\"\${${door}_HOST:-}\""
  [ -z "$published" ] && continue
  # The api door's per-client HMAC/CORS enforcement (LLD-api §6) is judged
  # against the same fact this loop already computes: API_HOST set at all,
  # not just non-loopback — a loopback-published door is still reachable by
  # anything on the docker host, not only the container. Told to the process
  # the same way FLOCK_ALLOW_PLAINTEXT is: exported here, not re-derived
  # in-container, because API_BIND is hardcoded 0.0.0.0 in the image
  # (Dockerfile) and cannot tell the process whether it was published.
  [ "$door" = "API" ] && export API_PUBLISHED=1
  eval "cert=\"\${${door}_TLS_CERT:-}\""
  eval "key=\"\${${door}_TLS_KEY:-}\""
  [ "$door" = "SESSION" ] && [ -z "$cert" ] && cert="${API_TLS_CERT:-}" && key="${API_TLS_KEY:-}"
  loopback=$(python3 -c '
import ipaddress, sys
host = sys.argv[1].strip("[]")
try:
    print("1" if ipaddress.ip_address(host).is_loopback else "0")
except ValueError:
    print("1" if host.lower() == "localhost" else "0")
' "$published")
  if [ "$loopback" = "0" ] && [ -z "$cert$key" ] && [ "${ALLOW_PLAINTEXT_PUBLISH:-0}" != "1" ]; then
    echo "entrypoint: the $(echo "$door" | tr 'A-Z' 'a-z') door is published on '$published' without TLS." >&2
    echo "  The bearer token would cross the network in clear text. Either set" >&2
    echo "  ${door}_TLS_CERT and ${door}_TLS_KEY, or publish to 127.0.0.1 only," >&2
    echo "  or set ALLOW_PLAINTEXT_PUBLISH=1 in this tenant's .env to accept it." >&2
    exit 1
  fi
done
export FLOCK_ALLOW_PLAINTEXT=1

# ── redis ─────────────────────────────────────────────────────────────────────
# Loopback only and never published. AOF persistence enabled for durable boards
# and streams; ephemeral transport queues are purged at boot (BUILD-63).
redis_bind="${REDIS_BIND:-127.0.0.1}"
redis_password="${REDIS_PASSWORD:-}"
redis_dir="${REDIS_DIR:-/tmp}"

# Refuse a non-loopback bind without a password (LLD-container §3).
is_loopback=$(python3 -c '
import ipaddress, sys
host = sys.argv[1]
try:
    print("1" if ipaddress.ip_address(host).is_loopback else "0")
except ValueError:
    print("1" if host in ("localhost", "127.0.0.1", "::1") else "0")
' "$redis_bind")

if [ "$is_loopback" = "0" ] && [ -z "$redis_password" ]; then
  echo "entrypoint: REDIS_PASSWORD is required when REDIS_BIND is not loopback ('$redis_bind')" >&2
  exit 1
fi

redis_cmd=(redis-server --bind "$redis_bind" --port 6379 --save '' --appendonly yes --appendfsync everysec --dir "$redis_dir")
if [ -n "$redis_password" ]; then
  redis_cmd+=(--requirepass "$redis_password")
  export REDISCLI_AUTH="$redis_password"
  if [ -z "${REDIS_URL:-}" ]; then
    export REDIS_URL="$(python3 -c 'from flock.bus.connection import local_redis_url; import sys; print(local_redis_url(sys.argv[1]))' "$redis_password")"
  fi
fi

# ⚠ redis-cli prints "NOAUTH Authentication required." and STILL EXITS 0, so a
# readiness probe passes while every command after it silently fails — a tenant
# that starts with an empty roster and no error. Every call goes through this.
rcli() {
  if [ -n "$redis_password" ]; then
    redis-cli -h 127.0.0.1 -a "$redis_password" --no-auth-warning "$@"
  else
    redis-cli -h 127.0.0.1 "$@"
  fi
}

start_critical redis "${redis_cmd[@]}"
redis_deadline=$((SECONDS + ${REDIS_READY_SECONDS:-30}))
until [ "$(rcli ping 2>/dev/null)" = "PONG" ]; do
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
# ⚠ Through jlog, not printed directly. This record is the proof that a restart
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
jlog "$purge_record"


# ── seed the roster ───────────────────────────────────────────────────────────
# Boot configuration, not the write path LLD-bus-and-switch §7 defers. The roster
# is the MAC table: a HASH of agent -> port_type (§3.2). HSET is idempotent, so
# bringing the container up twice converges (LLD-container §5).
#
# AGENTS is name:port_type pairs — AGENTS=backend:tmux,frontend:tmux,systems:tmux
roster_key="pod:${POD}:tenant:${TENANT}:roster"
IFS=',' read -ra entries <<< "$AGENTS"
agents=()
fields=()
for entry in "${entries[@]}"; do
  name="${entry%%:*}"
  port_type="${entry#*:}"
  if [ "$name" = "$entry" ] || [ -z "$port_type" ]; then
    echo "entrypoint: AGENTS entry '$entry' is not name:port_type" >&2
    exit 1
  fi
  agents+=("$name")
  fields+=("$name" "$port_type")
done

# Fixed agents. Roster rows like any other — the switch special-cases nothing
# (LLD-bus-and-switch §3.2). `host` is what StartAgent/StopAgent are addressed
# to; its port_type routes delivery to flock.control rather than to a tmux window, so
# it has no window and the tmux reconciler filters it out.
fields+=("api" "api")
fields+=("host" "control")

rcli HSET "$roster_key" "${fields[@]}" >/dev/null
# The HASH loses AGENTS ordering. Preserve authority while the ordered source is
# still in hand; no later command or override writes this derived value.
rcli SET "pod:${POD}:tenant:${TENANT}:lead" "${agents[0]}" >/dev/null
jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"roster_seeded\",\"count\":$(( ${#fields[@]} / 2 ))}"

# setup.sh is the authority for accounts. Persist the complete list rather than
# inferring it from derivative config directories or only assigned profiles.
if [ -n "${FLOCK_ACCOUNTS:-}" ]; then
  accounts_key="pod:${POD}:tenant:${TENANT}:accounts"
  rcli DEL "$accounts_key" >/dev/null
  IFS=',' read -ra _accounts <<< "$FLOCK_ACCOUNTS"
  for _account in "${_accounts[@]}"; do
    [ -n "$_account" ] && rcli SADD "$accounts_key" "$_account" >/dev/null
  done
fi

# Per-agent CLI and account, as exceptions only — "backend=codex", "frontend=work".
# Both land as agent resources rather than roster values: the roster is the MAC
# table and holds membership plus port_type, nothing else (LLD-bus-and-switch §3.2).
map_each() {   # $1=map  $2=resource ; SETs pod:…:agent:<name>:<resource>
  local pair name value
  IFS=',' read -ra pairs <<< "${1:-}"
  for pair in "${pairs[@]:-}"; do
    [ -n "$pair" ] || continue
    name="${pair%%=*}"; value="${pair#*=}"
    [ -n "$name" ] && [ -n "$value" ] && [ "$name" != "$pair" ] || continue
    rcli SET "pod:${POD}:tenant:${TENANT}:agent:${name}:$2" "$value" >/dev/null
  done
}
# ⚠ Default every tmux agent to claude BEFORE the exception maps are applied.
# setup.sh writes AGENT_CLIS only for agents that differ from the default, so a
# plain single-account install writes no AGENT_CLIS at all. Without this, no
# agent gets a launch key, tmux_reconciler builds every window as a bare shell, and the
# whole office comes up as three bash prompts with presence 'unknown'. Measured
# on a from-scratch install taking every default.
for _i in "${!agents[@]}"; do
  [ "${fields[$(( _i * 2 + 1 ))]}" = "tmux" ] || continue
  rcli SET "pod:${POD}:tenant:${TENANT}:agent:${agents[$_i]}:launch" claude >/dev/null
done

map_each "${AGENT_CLIS:-}"     launch
map_each "${AGENT_PROFILES:-}" profile
map_each "${AGENT_PROVIDERS:-}" provider

# An account is a config dir, and a fresh one is not an empty one — unseeded, an
# agent loses every default the image carries. Copy what the stock profile has
# and write the first-run marker INSIDE the dir, because $HOME/.claude.json
# covers the default account only (PLAN-profiles.md §3).
seed_profile_dir() {
  local prof="$1" c="/home/ubuntu/.claude-$1" x="/home/ubuntu/.codex-$1"
  [ "$prof" = "default" ] && return 0
  mkdir -p "$c" "$x"
  for item in settings.json skills agents CLAUDE.md; do
    [ -e "/home/ubuntu/.claude/$item" ] && [ ! -e "$c/$item" ] && cp -r "/home/ubuntu/.claude/$item" "$c/" 2>/dev/null
  done
  for item in config.toml AGENTS.md; do
    [ -e "/home/ubuntu/.codex/$item" ] && [ ! -e "$x/$item" ] && cp -r "/home/ubuntu/.codex/$item" "$x/" 2>/dev/null
  done
  [ -f "$c/.claude.json" ] || printf '{\n  "hasCompletedOnboarding": true\n}\n' > "$c/.claude.json"
  jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"profile_seeded\",\"reason\":\"$prof\"}"
}
IFS=',' read -ra _profpairs <<< "${AGENT_PROFILES:-}"
for _pair in "${_profpairs[@]:-}"; do
  [ -n "$_pair" ] && seed_profile_dir "${_pair#*=}"
done

# Held out of the environment for the same reason as AGENTS: the tmux server
# inherits it and every window inherits that.
unset AGENT_CLIS AGENT_PROFILES AGENT_PROVIDERS FLOCK_ACCOUNTS

# Seeding is the only use of AGENTS. Hold it out of the environment from here:
# the tmux server is started below and every agent window inherits its
# environment, so an exported AGENTS put the raw seed string — VABs included,
# and the agent itself in the list — in front of every agent. Asked where its
# peers were, one read that, found it confusing, and went to redis-cli for a
# better answer. Peers reach a window as AGENT_PEERS, derived from the roster.
unset AGENTS

# Redis credentials belong to infrastructure processes, not agent windows.
# Keep the URL in a shell variable for explicit process handoff, then remove
# every credential-bearing variable before tmux_reconciler creates the tmux server.
# tmux_reconciler consumes REDIS_URL from its own environment before its first tmux
# call, so the server cannot inherit it either.
redis_url="${REDIS_URL:-redis://127.0.0.1:6379/0}"
unset REDIS_PASSWORD REDISCLI_AUTH REDIS_URL

# ── tmux reconciler ─────────────────────────────────────────────────────────────────
# The tmux server inherits this and passes it to every agent window. tmux_reconciler
# itself has no AGENT_NAME, so FLOCK_LOG_FILE_AGENT_ONLY keeps its already-
# central lifecycle records out of the file and prevents duplicates.
export FLOCK_LOG_FILE=/home/ubuntu/.flock/window.log.jsonl
export FLOCK_LOG_FILE_AGENT_ONLY=1
start tmux_reconciler env REDIS_URL="$redis_url" python3 -m flock.tmux_reconciler

# Windows lead routes. LLD-bus-and-switch §3.2 names the one roster case that is
# not harmless: the switch routing to an agent whose window does not exist yet,
# whose first envelopes are then dead-lettered into nothing. Waiting here is the
# cheapest possible answer — the host is already ahead, so nothing can race it.
deadline=$((SECONDS + 30))
for agent in "${agents[@]}"; do
  until tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
     && tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "entrypoint: timed out waiting for window '$agent'" >&2
      exit 1
    fi
    sleep 0.3
  done
done
jlog "{\"module\":\"container\",\"writer\":\"container\",\"event\":\"windows_ready\",\"count\":${#agents[@]}}"

# Only the tmux server and its windows retain these. Processes started below
# already write directly to container stdout and must not enter the tail file.
unset FLOCK_LOG_FILE FLOCK_LOG_FILE_AGENT_ONLY

# ── the rest ──────────────────────────────────────────────────────────────────
start switch  env REDIS_URL="$redis_url" python3 -m flock.switch
# ⚠ ALWAYS started. WATCHDOG_ENABLED silences alerting, and the process decides
# that for itself — it also hosts ActivityTailer, PresenceSampler and
# DeliveryVerifier, which the api door, the web console and the Telegram bot all
# read. Gating the start here is what made the flag switch off telemetry three
# clients depend on.
start watchdog env REDIS_URL="$redis_url" python3 -m flock.watchdog
# No adapter here. It is not a service — the switch kicks `flock.port <agent>`
# per delivery and it exits (LLD-adapter-tmux §2). Starting one at boot would be
# the daemon this build exists to remove.
# The doors last, so neither is reachable before the tenant behind it is up
# (§5). The token is handed to these two processes and nothing else — it must
# not reach a tmux window, where the Command kind would make it root on every
# peer (§3).
# ⚠ The api door is OPT-IN. It is the widest surface the tenant has — one shared
# bearer token, and `as` on a post is a declaration rather than a credential
# (`api/app.py:617`), so any token holder can post as any enrolled client. A
# tenant whose agents only talk to each other over the bus does not need it, and
# a door nobody opened cannot be walked through. Set API_ENABLED=1 to publish it.
if [ "${API_ENABLED:-0}" != "0" ]; then
  start api   env API_TOKEN="$api_token" python3 -m flock.api
else
  jlog '{"module":"container","writer":"container","event":"api_disabled","reason":"API_ENABLED is not 1"}'
fi
start session env API_TOKEN="$api_token" python3 -m flock.session

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
  if [ "${API_ENABLED:-0}" = "0" ]; then
    jlog '{"module":"container","writer":"container","event":"client_skipped","reason":"telegram configured but API_ENABLED is 0"}'
  else
    tg_args=(
      python3 -m clients.telegram.bot
      --api-url "http://127.0.0.1:8080"
      --api-token "$api_token"
      --bot-token "$TELEGRAM_BOT_TOKEN"
      --cursor-file "/home/ubuntu/.flock/telegram.cursor.json"
    )
    [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg_args+=(--chat-id "$TELEGRAM_CHAT_ID")
    # ⚠ Unset means no button, not a broken one — clients/web itself is not
    # started here (comment above); MINI_APP_URL only ever names a URL the
    # operator started that server at themselves, elsewhere. See
    # clients/web/README.md's Mini App section for how that's set up.
    [ -n "${MINI_APP_URL:-}" ] && tg_args+=(--mini-app-url "$MINI_APP_URL")
    start_client telegram "${tg_args[@]}"
  fi
fi

# Redis is deliberately the critical exception. Its exit ends the entrypoint so
# the container restart path can purge transport before any switch reconnects.
# Every other core service restarts behind its own independent supervisor.
wait "$critical_pid"
