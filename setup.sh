#!/usr/bin/env bash
# setup.sh — run this on the HOST. Asks for the tenant layout, writes
# container/.env, and brings the tenant up. Redis, the tmux windows, the router
# and both doors all run INSIDE the container; nothing runs on the host.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

command -v docker >/dev/null 2>&1 || { echo "error: docker is required" >&2; exit 1; }
slug() { echo "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '-'; }
check_bool() {
    local val="$1" def="$2"
    val="${val:-$def}"
    case "$val" in
        [Yy]|[Yy][Ee][Ss]) return 0 ;;
        [Nn]|[Nn][Oo])    return 1 ;;
        *) echo "error: expected yes or no, got '$val'" >&2; exit 2 ;;
    esac
}

echo "=== h-flock :: new tenant ==="

read -rp "Pod name [acme]: " POD;    POD="$(slug "${POD:-acme}")"
read -rp "Tenant name [hq]: " TENANT; TENANT="$(slug "${TENANT:-hq}")"

read -rp "How many agents? [3]: " N; N="${N:-3}"
[[ "$N" =~ ^[1-9][0-9]*$ ]] || { echo "error: expected a positive number, got '$N'" >&2; exit 2; }
# Window 1 is always the architect — the lead, by position rather than by
# configuration. Everything after it defaults to sme-N, a subject matter expert
# you are meant to rename.
#
# N follows the position you enter them in, so a fresh office reads
# architect, sme-2, sme-3 top to bottom. Same shape as h-office's `agent-$i`.
#
# ⚠ It is a naming convention, not a window index. tmux renumbers when a window
# is killed — measured: after `letGo sme-2`, sme-3 moved from index 3 to index 2.
# Never infer a window position from a name.
#
# Rename them. Agents are named for what they are responsible for, not for
# people: an agent told "you are backend, your peers are frontend and redis"
# knows what it is for and who to ask from its name alone. `sme-2` conveys
# nothing, and neither did `alice` — the placeholder at least admits it.
AGENTS=()
for i in $(seq 1 "$N"); do
    if [ "$i" -eq 1 ]; then def="architect"; else def="sme-$i"; fi
    read -rp "  Agent #$i name [$def]: " A
    A="$(slug "${A:-$def}")"
    [ -n "$A" ] || { echo "  error: an agent needs a name" >&2; exit 2; }
    AGENTS+=("$A")
done

# ── accounts ──────────────────────────────────────────────────────────────────
# A profile is an ACCOUNT — the email you log in with. work and private, or
# client1 and client2. The unit is the account, not the agent: a config dir is
# one interactive login, so a dir per agent would mean a browser flow per seat.
# Several agents share one profile.
#
# The profile named 'default' is the stock ~/.claude / ~/.codex — whatever this
# image is already logged into. Only the EXTRA profiles cost a new login.
PROFILES=(); PROFILE_MAP=(); CLI_MAP=()
# ⚠ A CREDENTIAL, SO IT IS READ SILENTLY. Every other prompt echoes because
# nothing typed before this point is secret — API_TOKEN is generated, never
# typed. A token echoed here would sit in scrollback, in whatever recorded the
# session, and in a `capture-pane` if setup were ever run inside a window.
#
# ⚠ BLANK KEEPS WHAT IS ALREADY THERE. setup.sh rewrites container/.env whole,
# so without carrying the old value across, re-running it to add one agent would
# silently delete every token — which is exactly how API_ENABLED=1 used to
# vanish. Same read-it-back trick API_TOKEN already uses.
TOKEN_VAR() { printf 'CLAUDE_OAUTH_TOKEN_%s' "$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"; }
ask_token() {
    local profile="$1" var existing prompt entered
    var="$(TOKEN_VAR "$profile")"
    existing="$(grep -s "^${var}=" container/.env | cut -d= -f2-)"
    if [ -n "$existing" ]; then
        prompt="  OAuth token for '$profile' [keep existing]: "
    else
        prompt="  OAuth token for '$profile' (blank to log in interactively later): "
    fi
    read -rsp "$prompt" entered; echo
    [ -n "$entered" ] || entered="$existing"
    eval "$var=\$entered"
    TOKEN_VARS="$TOKEN_VARS $var"
}
TOKEN_VARS=""

read -rp "Use more than one account in this tenant? [y/N]: " USE_PROFILES
if check_bool "$USE_PROFILES" "n"; then
    read -rp "  How many accounts? [2]: " NP; NP="${NP:-2}"
    [[ "$NP" =~ ^[1-9][0-9]*$ ]] || { echo "  error: expected a positive number" >&2; exit 2; }
    for i in $(seq 1 "$NP"); do
        if [ "$i" -eq 1 ]; then pdef="default"; else pdef="account-$i"; fi
        read -rp "  Account #$i name [$pdef]: " P
        P="$(slug "${P:-$pdef}")"
        PROFILES+=("$P")
        ask_token "$P"
    done
else
    # One account still has a name — `default` — and still wants a token.
    ask_token default
fi

DEF_CLI=claude
# ⚠ No associative arrays. macOS ships bash 3.2 and `declare -A` is a syntax
# error there — measured on a stock MacBook, where this installer died on its
# first prompt. Agent names are already slugged to [a-z0-9-], so one shell
# variable per key is a safe encoding.
_mk() { printf 'M_%s_%s' "$1" "$(printf '%s' "$2" | tr -c 'A-Za-z0-9' '_')"; }
mset() { eval "$(_mk "$1" "$2")=\$3"; }
mget() { eval "printf '%s' \"\${$(_mk "$1" "$2"):-}\""; }

for a in "${AGENTS[@]}"; do mset CLI "$a" claude; mset PROF "$a" default; done

# ⚠ WHICH CLI IS ASKED ALWAYS. IT USED TO BE INSIDE THE ACCOUNTS BRANCH, so a
# single-account tenant silently got claude for every agent with no way to say
# otherwise — the only route through was writing AGENT_CLIS= into container/.env
# by hand. Measured twice in two days while standing up offices that wanted
# codex and agy. Accounts and frameworks are independent questions and are now
# asked independently.
read -rp "  Default CLI (claude/codex/agy) [claude]: " DEF_CLI
DEF_CLI="$(slug "${DEF_CLI:-claude}")"
for a in "${AGENTS[@]}"; do mset CLI "$a" "$DEF_CLI"; done

if [ "${#PROFILES[@]}" -gt 0 ]; then
    echo "  Accounts: ${PROFILES[*]}"
    read -rp "  Default account for every agent [${PROFILES[0]}]: " DEF_PROFILE
    DEF_PROFILE="$(slug "${DEF_PROFILE:-${PROFILES[0]}}")"
    for a in "${AGENTS[@]}"; do mset PROF "$a" "$DEF_PROFILE"; done
fi

# Defaults plus exceptions, not a question per agent: eleven agents times
# framework-and-account is twenty-two answers for what is usually uniform.
echo "  Agents: ${AGENTS[*]}"
read -rp "  Any agents differing from that? (space-separated, blank for none): " EXC
for want in ${EXC//,/ }; do
        want="$(slug "$want")"
        printf '%s\n' "${AGENTS[@]}" | grep -qx "$want" || { echo "  (skipping '$want' — not an agent)"; continue; }
        read -rp "    $want — CLI [$DEF_CLI]: " C; mset CLI "$want" "$(slug "${C:-$DEF_CLI}")"
        # Only ask which account when there is more than one to choose from.
        if [ "${#PROFILES[@]}" -gt 0 ]; then
            read -rp "    $want — account [$DEF_PROFILE]: " P; P="$(slug "${P:-$DEF_PROFILE}")"
            if printf '%s\n' "${PROFILES[@]}" | grep -qx "$P"; then mset PROF "$want" "$P"
            else echo "    (no account '$P' — keeping $(mget PROF "$want"))"; fi
        fi
done

# ⚠ agy keeps its state in ~/.gemini/antigravity-cli and exposes no equivalent of
# CLAUDE_CONFIG_DIR / CODEX_HOME, so it cannot be pointed at a second account.
for a in "${AGENTS[@]}"; do
    if [ "$(mget CLI "$a")" = "agy" ] && [ "$(mget PROF "$a")" != "default" ]; then
        echo "  warning: $a runs agy, which supports only one account — ignoring account '$(mget PROF "$a")'" >&2
        mset PROF "$a" default
    fi
done

# A local model provider. An agent pointed at one uses NO account credential —
# claude talks to the server directly — so it needs no login and the watchdog's
# credential check does not apply to it.
PROVIDER_MAP=(); LOCAL_URL=""; LOCAL_MODEL=""; LOCAL_TOKEN="local"
read -rp "Point any agent at a local model provider? [y/N]: " USE_PROVIDER
if check_bool "$USE_PROVIDER" "n"; then
    # ⚠ No default. There is no sensible one — an address here was this
    # developer's own box, which is meaningless on anyone else's network.
    # The kind decides the usual port and, more importantly, whether claude can
    # use it at all — see the probe below.
    read -rp "  Endpoint type — vllm or ollama [vllm]: " EP_KIND
    EP_KIND="$(slug "${EP_KIND:-vllm}")"
    case "$EP_KIND" in
        vllm)   EP_HINT="http://10.0.0.5:8000" ;;
        ollama) EP_HINT="http://10.0.0.5:11434" ;;
        *)      echo "  unknown type '$EP_KIND' — treating it as vllm"; EP_KIND=vllm; EP_HINT="http://10.0.0.5:8000" ;;
    esac
    read -rp "  Endpoint base URL, e.g. $EP_HINT (NO trailing /v1): " LOCAL_URL
    while [ -z "$LOCAL_URL" ]; do
        read -rp "  An provider needs an address. URL (blank to skip providers): " LOCAL_URL
        [ -z "$LOCAL_URL" ] && break
    done
    LOCAL_URL="${LOCAL_URL%/}"
    # ⚠ claude appends /v1/messages itself; a base carrying /v1 gives /v1/v1.
    LOCAL_URL="${LOCAL_URL%/v1}"

    # ⚠ The id must match the served id byte for byte. Offer what is served
    # rather than asking someone to type it: ollama ids carry a tag
    # (gpt-oss:20b) and are easy to mistype as gpt-oss-20b.
    SERVED="$(curl -s --max-time 5 "${LOCAL_URL}/v1/models" 2>/dev/null \
              | python3 -c 'import sys,json;print(" ".join(m["id"] for m in json.load(sys.stdin).get("data",[])))' 2>/dev/null || true)"
    if [ -z "$SERVED" ] && [ "$EP_KIND" = "ollama" ]; then
        SERVED="$(curl -s --max-time 5 "${LOCAL_URL}/api/tags" 2>/dev/null \
                  | python3 -c 'import sys,json;print(" ".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null || true)"
    fi
    [ -n "$SERVED" ] && echo "  served by that provider: $SERVED"
    read -rp "  Model id [${SERVED%% *}]: " LOCAL_MODEL
    LOCAL_MODEL="${LOCAL_MODEL:-${SERVED%% *}}"

    # ⚠ ASK, THEN VERIFY — and probe with a REAL model id. claude talks to
    # /v1/messages, and an provider that does not answer there makes it report
    # "issue with the selected model", which reads as a model problem and is
    # not one. So ask the provider rather than assuming anything about it.
    #
    # ⚠ A 404 alone does not mean the route is missing: vLLM answers an unknown
    # model with 404 and {"type":"error","error":{"type":"NotFoundError"}}.
    # Probing with a made-up id therefore condemns a working provider — measured.
    # Use a served id and read the body.
    if [ -n "$LOCAL_URL" ] && [ -n "$LOCAL_MODEL" ]; then
        # ⚠ 90s, not 8. A local model that has to load answers in tens of
        # seconds the first time and under one second afterwards — measured on
        # ollama: the same provider gave nothing at 8s while cold and 0.5s once
        # warm. A short timeout turns a cold start into a verdict about the
        # provider, which is how the previous probe condemned a working vLLM.
        PROBE="$(curl -s --max-time 90 -H 'Content-Type: application/json' -X POST \
                 -d "{\"model\":\"${LOCAL_MODEL}\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" \
                 "${LOCAL_URL}/v1/messages" 2>/dev/null || true)"
        if echo "$PROBE" | grep -q '"type"[[:space:]]*:[[:space:]]*"message"'; then
            echo "  ✓ /v1/messages answered — claude can use this provider"
        elif [ -z "$PROBE" ]; then
            echo "  ⚠ ${LOCAL_URL}/v1/messages did not answer within 90s."
            echo "    That is 'no answer', not 'not served' — a model still loading"
            echo "    looks the same from here. Try again once it is warm; if it stays"
            echo "    silent, claude talks to that path and will not work against this"
            echo "    provider as it stands. codex and agy speak the OpenAI shape."
        else
            echo "  ⚠ /v1/messages answered, but not with a message:"
            echo "    $(echo "$PROBE" | head -c 160)"
        fi
    fi
    read -rp "  Endpoint name [local]: " EP_NAME; EP_NAME="$(slug "${EP_NAME:-local}")"
    read -rp "  Which agents use it? (space-separated, blank for none): " EPS
    for want in $EPS; do
        for a in "${AGENTS[@]}"; do
            [ "$a" = "$(slug "$want")" ] && mset EP "$a" "$EP_NAME"
        done
    done
fi

# ── which doors, and on which host ports ──────────────────────────────────────
# ⚠ Two tenants on one host collide unless the PUBLISHED ports differ. The
# compose project is already per-tenant (`h-flock-<tenant>`), but this script
# used to write 8080/8081 unconditionally, so the second tenant on a box came up
# with a working door nobody could reach — the failure `container/compose.yaml`
# records as "measured while running a second tenant beside the first".
#
# ⚠ The doors ALWAYS bind 8080/8081 INSIDE the container. These choose the host
# side of the mapping only.
# ⚠ A port probe that cannot see the ports is a check that can never fail, and
# it would report "free" for every port on the box. So the probe is chosen once,
# up front, and its absence is SAID rather than swallowed. Python is already a
# hard dependency of everything else here.
port_busy() {
    python3 - "$1" <<'PROBE'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(0)          # in use
finally:
    s.close()
sys.exit(1)              # free
PROBE
}

free_port() {
    # First free port at or above $1. Checked on the host, where the collision is.
    local p="$1"
    while port_busy "$p"; do p=$((p+1)); done
    echo "$p"
}

echo
echo
API_ENABLED=0; API_PORT=""; API_PUBLISH=0; TELEGRAM=0; TELEGRAM_VOICE=0
TELEGRAM_BOT_TOKEN=""; TELEGRAM_CHAT_ID=""
read -rp "Start the REST API door inside the tenant? [y/N]: " WANT_API
if check_bool "$WANT_API" "n"; then API_ENABLED=1; fi

read -rp "Run the Telegram bot in this tenant? [y/N]: " WANT_TG
if check_bool "$WANT_TG" "n"; then
    if [ "$API_ENABLED" = "0" ]; then
        echo "  (the Telegram bot talks to the REST API, so that service is enabled inside the container)"
        API_ENABLED=1
    fi
    existing_tg_token="$(grep -s '^TELEGRAM_BOT_TOKEN=' container/.env 2>/dev/null | cut -d= -f2- || true)"
    existing_tg_chat="$(grep -s '^TELEGRAM_CHAT_ID=' container/.env 2>/dev/null | cut -d= -f2- || true)"
    existing_tg_voice="$(grep -s '^TELEGRAM_VOICE=' container/.env 2>/dev/null | cut -d= -f2- || true)"
    if [ -n "$existing_tg_token" ]; then
        read -rsp "  Telegram Bot Token [keep existing]: " TG_TOKEN; echo
    else
        read -rsp "  Telegram Bot Token (required, blank to skip): " TG_TOKEN; echo
    fi
    [ -n "$TG_TOKEN" ] || TG_TOKEN="$existing_tg_token"

    if [ -n "$existing_tg_chat" ]; then
        read -rp "  Telegram Chat ID [$existing_tg_chat]: " TG_CHAT
    else
        read -rp "  Telegram Chat ID (required, blank to skip): " TG_CHAT
    fi
    [ -n "$TG_CHAT" ] || TG_CHAT="$existing_tg_chat"

    if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
        TELEGRAM=1
        TELEGRAM_BOT_TOKEN="$TG_TOKEN"
        TELEGRAM_CHAT_ID="$TG_CHAT"
        if [ "$existing_tg_voice" = "1" ]; then
            read -rp "  Enable spoken voice replies? [Y/n]: " WANT_VOICE
            if check_bool "$WANT_VOICE" "y"; then TELEGRAM_VOICE=1; else TELEGRAM_VOICE=0; fi
        else
            read -rp "  Enable spoken voice replies? [y/N]: " WANT_VOICE
            if check_bool "$WANT_VOICE" "n"; then TELEGRAM_VOICE=1; else TELEGRAM_VOICE=0; fi
        fi
    else
        echo "  ⚠ Both Telegram Bot Token and Chat ID are required — Telegram bot is not enabled."
        TELEGRAM=0
        TELEGRAM_BOT_TOKEN=""
        TELEGRAM_CHAT_ID=""
        TELEGRAM_VOICE=0
    fi
fi

if [ "$API_ENABLED" = "1" ]; then
    read -rp "Reach the REST API from outside the container (0.0.0.0, every host interface)? [y/N]: " WANT_PUB_API
    if check_bool "$WANT_PUB_API" "n"; then
        API_PUBLISH=1
        DEF_API="$(free_port 8080)"
        read -rp "  Host port for the REST API [${DEF_API}]: " API_PORT
        API_PORT="${API_PORT:-$DEF_API}"
        [[ "$API_PORT" =~ ^[1-9][0-9]*$ ]] || { echo "error: expected a valid port number, got '$API_PORT'" >&2; exit 2; }
    else
        API_PUBLISH=0
        API_PORT=""
    fi
fi

SESSION_PUBLISH=0; SESSION_PORT=""
read -rp "Reach the session console from outside the container (0.0.0.0, every host interface)? [Y/n]: " WANT_PUB_SESSION
if check_bool "$WANT_PUB_SESSION" "y"; then
    SESSION_PUBLISH=1
    DEF_SESSION="$(free_port 8081)"
    read -rp "  Host port for the session console [${DEF_SESSION}]: " SESSION_PORT
    SESSION_PORT="${SESSION_PORT:-$DEF_SESSION}"
    [[ "$SESSION_PORT" =~ ^[1-9][0-9]*$ ]] || { echo "error: expected a valid port number, got '$SESSION_PORT'" >&2; exit 2; }
else
    SESSION_PUBLISH=0
    SESSION_PORT=""
fi

for pair in "api:${API_PORT}" "session:${SESSION_PORT}"; do
    name="${pair%%:*}"; port="${pair#*:}"
    [ -n "$port" ] || continue
    if port_busy "$port"; then
        echo "error: port ${port} is already listening; the ${name} door would map onto nothing" >&2
        echo "  and the tenant would come up unhealthy with a door nobody can reach." >&2
        exit 2
    fi
done

# ── how the doors are published ───────────────────────────────────────────────
# The console and the api carry a bearer token. Published beyond loopback with
# no TLS it crosses the network in clear text, so the tenant refuses to start
# unless that is an answered question rather than a default nobody saw.
TLS_CERT_HOST=""; TLS_KEY_HOST=""; TLS_CERT_CONTAINER=""; TLS_KEY_CONTAINER=""
TLS_STAGE=""; ALLOW_PLAINTEXT=0; DOOR_HOST=""
API_HOST=""; SESSION_HOST=""

if [ "$API_PUBLISH" = "1" ] || [ "$SESSION_PUBLISH" = "1" ]; then
    echo
    read -rp "Reach published doors from another machine (bind 0.0.0.0 instead of 127.0.0.1)? [Y/n]: " REMOTE
    if check_bool "$REMOTE" "y"; then
        DOOR_HOST="0.0.0.0"
        read -rp "  Path to a TLS certificate (blank for more choices): " TLS_CERT_HOST
        if [ -n "$TLS_CERT_HOST" ]; then
            [ -f "$TLS_CERT_HOST" ] || { echo "  error: TLS certificate not found: $TLS_CERT_HOST" >&2; exit 2; }
            read -rp "  Path to its key: " TLS_KEY_HOST
            [ -n "$TLS_KEY_HOST" ] || { echo "  error: a TLS certificate requires its key" >&2; exit 2; }
            [ -f "$TLS_KEY_HOST" ] || { echo "  error: TLS key not found: $TLS_KEY_HOST" >&2; exit 2; }
        else
            read -rp "  Generate a self-signed certificate? [y/N]: " SELF_SIGNED
            if check_bool "$SELF_SIGNED" "n"; then
                command -v openssl >/dev/null 2>&1 || { echo "  error: openssl is required to generate a certificate" >&2; exit 2; }
                echo "  ⚠ Self-signed TLS encrypts traffic, but clients that verify certificates"
                echo "    will reject it unless they are explicitly configured to trust it."
                TLS_STAGE="$(mktemp -d)"
                trap 'rm -rf "$TLS_STAGE"' EXIT
                TLS_CERT_HOST="$TLS_STAGE/tls.crt"
                TLS_KEY_HOST="$TLS_STAGE/tls.key"
                openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
                    -subj "/CN=${TENANT}" -addext "subjectAltName=DNS:${TENANT},IP:127.0.0.1" \
                    -keyout "$TLS_KEY_HOST" -out "$TLS_CERT_HOST" >/dev/null 2>&1 \
                    || { echo "  error: could not generate the self-signed certificate" >&2; exit 2; }
                chmod 0644 "$TLS_CERT_HOST" "$TLS_KEY_HOST"
            else
                echo "  ⚠ Plain HTTP: the api token and everything typed into a terminal"
                echo "    cross the network unencrypted. Fine on a trusted LAN, not on one"
                echo "    you share. Recorded as ALLOW_PLAINTEXT_PUBLISH=1 in container/.env."
                ALLOW_PLAINTEXT=1
            fi
        fi
    else
        DOOR_HOST="127.0.0.1"   # published to this host only; plaintext never leaves it
    fi
fi

if [ -n "$TLS_CERT_HOST" ]; then
    TLS_CERT_CONTAINER="/home/ubuntu/tlscerts/tls.crt"
    TLS_KEY_CONTAINER="/home/ubuntu/tlscerts/tls.key"
    if [ -z "$TLS_STAGE" ]; then
        TLS_STAGE="$(mktemp -d)"
        trap 'rm -rf "$TLS_STAGE"' EXIT
        install -m 0644 "$TLS_CERT_HOST" "$TLS_STAGE/tls.crt"
        # The container is the security boundary; every agent inside it is a
        # colleague with code execution. docker cp makes files root-owned, so
        # the door's ubuntu process needs the staged key to be readable.
        install -m 0644 "$TLS_KEY_HOST" "$TLS_STAGE/tls.key"
    fi
fi

if [ "$API_PUBLISH" = "1" ] || [ "$SESSION_PUBLISH" = "1" ]; then
    API_HOST="${DOOR_HOST}"
    SESSION_HOST="${DOOR_HOST}"
    {
        echo "services:"
        echo "  tenant:"
        echo "    ports:"
        [ "$API_PUBLISH" = "1" ] && [ -n "$API_PORT" ] && echo "      - \"${API_HOST}:${API_PORT}:8080\""
        [ "$SESSION_PUBLISH" = "1" ] && [ -n "$SESSION_PORT" ] && echo "      - \"${SESSION_HOST}:${SESSION_PORT}:8081\""
    } > container/compose.ports.yaml
else
    rm -f container/compose.ports.yaml
fi

# Only exceptions travel, so the env stays small and readable.
for a in "${AGENTS[@]}"; do
    [ -n "$(mget EP "$a")" ] && PROVIDER_MAP+=("${a}=$(mget EP "$a")")
done
for a in "${AGENTS[@]}"; do
    [ "$(mget PROF "$a")" != "default" ] && PROFILE_MAP+=("${a}=$(mget PROF "$a")")
    [ "$(mget CLI "$a")"  != "claude"  ] && CLI_MAP+=("${a}=$(mget CLI "$a")")
done

echo
printf '  %-16s %-8s %-10s %s\n' AGENT CLI ACCOUNT MODEL
for a in "${AGENTS[@]}"; do
    ep="$(mget EP "$a")"
    printf '  %-16s %-8s %-10s %s\n' "$a" "$(mget CLI "$a")" "$(mget PROF "$a")" \
        "${ep:+$LOCAL_MODEL (local)}"
done
echo

# Every agent is a tmux agent; api and host are added by the entrypoint.
AGENTS_CSV=""
for a in "${AGENTS[@]}"; do AGENTS_CSV+="${a}:tmux,"; done
AGENTS_CSV="${AGENTS_CSV%,}"

TOKEN="$(grep -s '^API_TOKEN=' container/.env | cut -d= -f2)"
[ -n "$TOKEN" ] || TOKEN="$(openssl rand -hex 16)"

# env is what persists; the roster is derived from it at every container start.
{
    echo "POD=${POD}"
    echo "TENANT=${TENANT}"
    echo "AGENTS=${AGENTS_CSV}"
    if [ "${#PROFILES[@]}" -gt 0 ]; then
        echo "FLOCK_ACCOUNTS=$(IFS=,; echo "${PROFILES[*]}")"
    else
        echo "FLOCK_ACCOUNTS=default"
    fi
    echo "API_TOKEN=${TOKEN}"
    # ⚠ One per account, and only the ones that have a value. An empty
    # CLAUDE_OAUTH_TOKEN_X= would reach the container as an empty string, which
    # is NOT the same as absent — the CLI would see the variable set and treat
    # it as a credential. Absent means "log in interactively", which is the
    # existing path and must keep working.
    for tv in $TOKEN_VARS; do
        eval "tval=\${$tv:-}"
        [ -n "$tval" ] && echo "${tv}=${tval}"
    done
    echo "API_ENABLED=${API_ENABLED}"
    [ -n "$API_PORT" ] && echo "API_PORT=${API_PORT}"
    [ -n "$SESSION_PORT" ] && echo "SESSION_PORT=${SESSION_PORT}"
    [ -n "$API_HOST" ] && echo "API_HOST=${API_HOST}"
    [ -n "$SESSION_HOST" ] && echo "SESSION_HOST=${SESSION_HOST}"
    [ "$ALLOW_PLAINTEXT" = "1" ] && echo "ALLOW_PLAINTEXT_PUBLISH=1"
    if [ -n "$TLS_CERT_CONTAINER" ]; then
        echo "API_TLS_CERT=${TLS_CERT_CONTAINER}"
        echo "API_TLS_KEY=${TLS_KEY_CONTAINER}"
        echo "SESSION_TLS_CERT=${TLS_CERT_CONTAINER}"
        echo "SESSION_TLS_KEY=${TLS_KEY_CONTAINER}"
    fi
    [ -n "$TELEGRAM_BOT_TOKEN" ] && echo "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}"
    [ -n "$TELEGRAM_CHAT_ID" ] && echo "TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}"
    [ "$TELEGRAM_VOICE" = "1" ] && echo "TELEGRAM_VOICE=1"
    [ "${#CLI_MAP[@]}"     -gt 0 ] && echo "AGENT_CLIS=$(IFS=,; echo "${CLI_MAP[*]}")"
    [ "${#PROFILE_MAP[@]}" -gt 0 ] && echo "AGENT_PROFILES=$(IFS=,; echo "${PROFILE_MAP[*]}")"
    if [ "${#PROVIDER_MAP[@]}" -gt 0 ]; then
        echo "AGENT_PROVIDERS=$(IFS=,; echo "${PROVIDER_MAP[*]}")"
        PR_UPPER="$(echo "$EP_NAME" | tr '[:lower:]-' '[:upper:]_')"
        echo "PROVIDER_${PR_UPPER}_URL=${LOCAL_URL}"
        echo "PROVIDER_${PR_UPPER}_MODEL=${LOCAL_MODEL}"
        echo "PROVIDER_${PR_UPPER}_TOKEN=${LOCAL_TOKEN}"
        echo "PROVIDER_${PR_UPPER}_KIND=${EP_KIND}"
    fi
} > container/.env
chmod 600 container/.env
echo "wrote container/.env"

CONTAINER="h-flock-${TENANT}-tenant-1"
. container/flock-compose.sh 2>/dev/null || true
flock_compose_args
COMPOSE=(docker compose -p "h-flock-${TENANT}" --env-file container/.env "${FLOCK_COMPOSE_ARGS[@]}")
# ⚠ Build only when there is no image for THIS commit. The tag carries the SHA,
# so an existing one is proof it matches the source; rebuilding it produces a
# byte-identical result and used to happen on every tenant, five times in a full
# test sweep. See container/flock-image.sh.
. container/flock-image.sh 2>/dev/null || true
if declare -f flock_image_tag >/dev/null; then
  export FLOCK_IMAGE="${FLOCK_IMAGE:-$(flock_image_tag)}"
  BUILD_FLAG="$(flock_build_flag)"
else
  BUILD_FLAG="--build"
fi

if [ -n "$TLS_CERT_CONTAINER" ]; then
    echo "Building and creating tenant '${TENANT}'..."
    "${COMPOSE[@]}" create ${BUILD_FLAG} || exit 1
    # ⚠ mktemp -d makes the directory 0700, and docker cp preserves both the
    # mode and the host uid. On this lab the operator is uid 1000, which is
    # `ubuntu` inside the container, so the door could traverse it — by luck.
    # Any other host uid leaves a 0700 directory the door cannot enter, and the
    # tenant fails with a permission error rather than a missing file.
    chmod 0755 "$TLS_STAGE"
    echo "Copying TLS certificate into the stopped tenant..."
    docker cp "$TLS_STAGE" "$CONTAINER:/home/ubuntu/tlscerts" || exit 1
    "${COMPOSE[@]}" start || exit 1
else
    echo "Building and starting tenant '${TENANT}'..."
    "${COMPOSE[@]}" up -d ${BUILD_FLAG} || exit 1
fi

for _ in $(seq 1 60); do
    docker exec "$CONTAINER" redis-cli ping >/dev/null 2>&1 && break
    sleep 1
done

# Dotfiles, ssh keys and any saved logins — copied in, never baked into the image.
if [ -d container/home ]; then
    ./container/seed-home.sh in "$CONTAINER"

    # ⚠ Restart, or every agent that boots with a CLI is unauthenticated.
    # The entrypoint creates windows and starts the CLIs as soon as the
    # container comes up — before this seeding could possibly have happened, so
    # each CLI read an empty config dir and sat at a login prompt while
    # credentials existed on disk beside it.
    #
    # Measured: sme-2 and sme-3 both showed "Not logged in · Run /login" while
    # seed-home check reported all three CLIs logged in.
    #
    # docker restart keeps the filesystem, so the credentials stay; only the
    # processes come back, and the entrypoint recreates the windows. Cheap here
    # because the tenant is seconds old and holds no work yet.
    docker restart "$CONTAINER" >/dev/null || exit 1
    for _ in $(seq 1 60); do
        docker exec "$CONTAINER" redis-cli ping >/dev/null 2>&1 && break
        sleep 1
    done
fi

HEALTH=""
for _ in $(seq 1 90); do
    HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)"
    [ "$HEALTH" = "healthy" ] && break
    [ "$HEALTH" = "unhealthy" ] && break
    sleep 1
done
if [ "$HEALTH" != "healthy" ]; then
    echo "error: tenant '${TENANT}' did not become healthy (status: ${HEALTH:-unknown})" >&2
    docker logs --tail 40 "$CONTAINER" >&2 || true
    exit 1
fi

echo
echo "Tenant '${TENANT}' is healthy."
SCHEME=http; SESSION_SCHEME=ws
if [ -n "$TLS_CERT_CONTAINER" ]; then SCHEME=https; SESSION_SCHEME=wss; fi
# ⚠ Print only doors that are actually running. Printing a URL for a door the
# entrypoint declined to start is how "why is nothing listening" becomes a hunt.
if [ "$API_ENABLED" = "1" ]; then
    if [ "$API_PUBLISH" = "1" ]; then
        echo "  api      ${SCHEME}://${API_HOST:-127.0.0.1}:${API_PORT}   token in container/.env"
    else
        echo "  api      enabled inside tenant (not published to host)   token in container/.env"
    fi
else
    echo "  api      not enabled (API_ENABLED=0) — set it in container/.env to open it"
fi
if [ "$SESSION_PUBLISH" = "1" ]; then
    echo "  session  ${SESSION_SCHEME}://${SESSION_HOST:-127.0.0.1}:${SESSION_PORT}/session"
else
    echo "  session  enabled inside tenant (not published to host)"
fi
if [ "$TELEGRAM" = "1" ]; then
    voice_suffix=""
    [ "$TELEGRAM_VOICE" = "1" ] && voice_suffix=" (voice replies enabled)"
    echo "  telegram bot running in tenant (chat id: ${TELEGRAM_CHAT_ID})${voice_suffix}"
fi
echo "  attach   docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux $CONTAINER tmux attach -t ${TENANT}"
if [ -n "$TLS_CERT_CONTAINER" ]; then
    echo
    echo "  ⚠ The shipped browser console cannot reach TLS tenant doors."
    echo "    Use a TLS-capable app, or publish the doors on loopback behind a TLS proxy."
    echo "    See clients/web/README.md."
fi
echo
echo "Accounts still needing a login:"
./container/seed-home.sh check "$CONTAINER"
echo
echo "  Log in inside an agent's window, then save it so the next rebuild keeps it:"
echo "    ./container/seed-home.sh out $CONTAINER"
