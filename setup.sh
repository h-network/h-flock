#!/usr/bin/env bash
# setup.sh — run this on the HOST. Asks for the tenant layout, writes
# container/.env, and brings the tenant up. Redis, the tmux windows, the router
# and both doors all run INSIDE the container; nothing runs on the host.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

command -v docker >/dev/null 2>&1 || { echo "error: docker is required" >&2; exit 1; }
slug() { echo "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '-'; }

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
read -rp "Use more than one account in this tenant? [y/N]: " USE_PROFILES
case "$USE_PROFILES" in
  [Yy]*)
    read -rp "  How many accounts? [2]: " NP; NP="${NP:-2}"
    [[ "$NP" =~ ^[1-9][0-9]*$ ]] || { echo "  error: expected a positive number" >&2; exit 2; }
    for i in $(seq 1 "$NP"); do
        if [ "$i" -eq 1 ]; then pdef="default"; else pdef="account-$i"; fi
        read -rp "  Account #$i name [$pdef]: " P
        PROFILES+=("$(slug "${P:-$pdef}")")
    done
    ;;
esac

DEF_CLI=claude
declare -A AGENT_CLI_OF AGENT_PROFILE
for a in "${AGENTS[@]}"; do AGENT_CLI_OF["$a"]=claude; AGENT_PROFILE["$a"]=default; done

if [ "${#PROFILES[@]}" -gt 0 ]; then
    # Defaults plus exceptions, not a question per agent: eleven agents times
    # framework-and-account is twenty-two answers for what is usually uniform.
    echo "  Accounts: ${PROFILES[*]}"
    read -rp "  Default account for every agent [${PROFILES[0]}]: " DEF_PROFILE
    DEF_PROFILE="$(slug "${DEF_PROFILE:-${PROFILES[0]}}")"
    read -rp "  Default CLI (claude/codex/agy) [claude]: " DEF_CLI
    DEF_CLI="$(slug "${DEF_CLI:-claude}")"
    for a in "${AGENTS[@]}"; do AGENT_CLI_OF["$a"]="$DEF_CLI"; AGENT_PROFILE["$a"]="$DEF_PROFILE"; done

    echo "  Agents: ${AGENTS[*]}"
    read -rp "  Any agents differing from that? (space-separated, blank for none): " EXC
    for want in ${EXC//,/ }; do
        want="$(slug "$want")"
        printf '%s\n' "${AGENTS[@]}" | grep -qx "$want" || { echo "  (skipping '$want' — not an agent)"; continue; }
        read -rp "    $want — CLI [$DEF_CLI]: " C; AGENT_CLI_OF["$want"]="$(slug "${C:-$DEF_CLI}")"
        read -rp "    $want — account [$DEF_PROFILE]: " P; P="$(slug "${P:-$DEF_PROFILE}")"
        if printf '%s\n' "${PROFILES[@]}" | grep -qx "$P"; then AGENT_PROFILE["$want"]="$P"
        else echo "    (no account '$P' — keeping ${AGENT_PROFILE[$want]})"; fi
    done
fi

# ⚠ agy keeps its state in ~/.gemini/antigravity-cli and exposes no equivalent of
# CLAUDE_CONFIG_DIR / CODEX_HOME, so it cannot be pointed at a second account.
for a in "${AGENTS[@]}"; do
    if [ "${AGENT_CLI_OF[$a]}" = "agy" ] && [ "${AGENT_PROFILE[$a]}" != "default" ]; then
        echo "  warning: $a runs agy, which supports only one account — ignoring account '${AGENT_PROFILE[$a]}'" >&2
        AGENT_PROFILE["$a"]=default
    fi
done

# A local model endpoint. An agent pointed at one uses NO account credential —
# claude talks to the server directly — so it needs no login and the watchdog's
# credential check does not apply to it.
declare -A AGENT_ENDPOINT_OF
ENDPOINT_MAP=(); LOCAL_URL=""; LOCAL_MODEL=""; LOCAL_TOKEN="local"
read -rp "Point any agent at a local model endpoint? [y/N]: " USE_ENDPOINT
if [[ "${USE_ENDPOINT:-n}" =~ ^[Yy] ]]; then
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
        read -rp "  An endpoint needs an address. URL (blank to skip endpoints): " LOCAL_URL
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
    [ -n "$SERVED" ] && echo "  served by that endpoint: $SERVED"
    read -rp "  Model id [${SERVED%% *}]: " LOCAL_MODEL
    LOCAL_MODEL="${LOCAL_MODEL:-${SERVED%% *}}"

    # ⚠ ASK, THEN VERIFY — and probe with a REAL model id. claude speaks only
    # the Anthropic Messages API; ollama is OpenAI-shaped and has no
    # /v1/messages, so pointing claude at a bare one yields "issue with the
    # selected model", which reads as a model problem and is not one.
    #
    # ⚠ A 404 alone does not mean the route is missing: vLLM answers an unknown
    # model with 404 and {"type":"error","error":{"type":"NotFoundError"}}.
    # Probing with a made-up id therefore condemns a working endpoint — measured.
    # Use a served id and read the body.
    if [ -n "$LOCAL_URL" ] && [ -n "$LOCAL_MODEL" ]; then
        PROBE="$(curl -s --max-time 8 -H 'Content-Type: application/json' -X POST \
                 -d "{\"model\":\"${LOCAL_MODEL}\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" \
                 "${LOCAL_URL}/v1/messages" 2>/dev/null || true)"
        if echo "$PROBE" | grep -q '"type"[[:space:]]*:[[:space:]]*"message"'; then
            echo "  ✓ /v1/messages answered — claude can use this endpoint"
        elif [ -z "$PROBE" ]; then
            echo "  ⚠ ${LOCAL_URL}/v1/messages returned nothing."
            echo "    claude speaks only the Anthropic Messages API. ollama does not serve it."
            echo "    Put a translating proxy in front, or point codex/agy here instead."
        else
            echo "  ⚠ /v1/messages answered, but not with a message:"
            echo "    $(echo "$PROBE" | head -c 160)"
        fi
    fi
    read -rp "  Endpoint name [local]: " EP_NAME; EP_NAME="$(slug "${EP_NAME:-local}")"
    read -rp "  Which agents use it? (space-separated, blank for none): " EPS
    for want in $EPS; do
        for a in "${AGENTS[@]}"; do
            [ "$a" = "$(slug "$want")" ] && AGENT_ENDPOINT_OF["$a"]="$EP_NAME"
        done
    done
fi

# ── how the doors are published ───────────────────────────────────────────────
# The console and the api carry a bearer token. Published beyond loopback with
# no TLS it crosses the network in clear text, so the tenant refuses to start
# unless that is an answered question rather than a default nobody saw.
TLS_CERT=""; TLS_KEY=""; ALLOW_PLAINTEXT=0; DOOR_HOST="0.0.0.0"
echo
read -rp "Reach the console from another machine? [Y/n]: " REMOTE
if [ "${REMOTE:-y}" = "n" ] || [ "${REMOTE:-y}" = "N" ]; then
    DOOR_HOST="127.0.0.1"   # published to this host only; plaintext never leaves it
else
    read -rp "  Path to a TLS certificate (blank for plain HTTP): " TLS_CERT
    if [ -n "$TLS_CERT" ]; then
        read -rp "  Path to its key: " TLS_KEY
    else
        echo "  ⚠ Plain HTTP: the api token and everything typed into a terminal"
        echo "    cross the network unencrypted. Fine on a trusted LAN, not on one"
        echo "    you share. Recorded as ALLOW_PLAINTEXT_PUBLISH=1 in container/.env."
        ALLOW_PLAINTEXT=1
    fi
fi

# Only exceptions travel, so the env stays small and readable.
for a in "${AGENTS[@]}"; do
    [ -n "${AGENT_ENDPOINT_OF[$a]:-}" ] && ENDPOINT_MAP+=("${a}=${AGENT_ENDPOINT_OF[$a]}")
done
for a in "${AGENTS[@]}"; do
    [ "${AGENT_PROFILE[$a]}" != "default" ] && PROFILE_MAP+=("${a}=${AGENT_PROFILE[$a]}")
    [ "${AGENT_CLI_OF[$a]}"  != "claude"  ] && CLI_MAP+=("${a}=${AGENT_CLI_OF[$a]}")
done

echo
printf '  %-16s %-8s %-10s %s\n' AGENT CLI ACCOUNT MODEL
for a in "${AGENTS[@]}"; do
    printf '  %-16s %-8s %-10s %s\n' "$a" "${AGENT_CLI_OF[$a]}" "${AGENT_PROFILE[$a]}" \
        "${AGENT_ENDPOINT_OF[$a]:+$LOCAL_MODEL (local)}"
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
    echo "API_TOKEN=${TOKEN}"
    echo "API_PORT=8080"
    echo "SESSION_PORT=8081"
    echo "API_HOST=${DOOR_HOST}"
    echo "SESSION_HOST=${DOOR_HOST}"
    [ "$ALLOW_PLAINTEXT" = "1" ] && echo "ALLOW_PLAINTEXT_PUBLISH=1"
    if [ -n "$TLS_CERT" ]; then
        echo "API_TLS_CERT=${TLS_CERT}"
        echo "API_TLS_KEY=${TLS_KEY}"
        echo "SESSION_TLS_CERT=${TLS_CERT}"
        echo "SESSION_TLS_KEY=${TLS_KEY}"
    fi
    [ "${#CLI_MAP[@]}"     -gt 0 ] && echo "AGENT_CLIS=$(IFS=,; echo "${CLI_MAP[*]}")"
    [ "${#PROFILE_MAP[@]}" -gt 0 ] && echo "AGENT_PROFILES=$(IFS=,; echo "${PROFILE_MAP[*]}")"
    if [ "${#ENDPOINT_MAP[@]}" -gt 0 ]; then
        echo "AGENT_ENDPOINTS=$(IFS=,; echo "${ENDPOINT_MAP[*]}")"
        EP_UPPER="$(echo "$EP_NAME" | tr '[:lower:]-' '[:upper:]_')"
        echo "ENDPOINT_${EP_UPPER}_URL=${LOCAL_URL}"
        echo "ENDPOINT_${EP_UPPER}_MODEL=${LOCAL_MODEL}"
        echo "ENDPOINT_${EP_UPPER}_TOKEN=${LOCAL_TOKEN}"
        echo "ENDPOINT_${EP_UPPER}_KIND=${EP_KIND}"
    fi
} > container/.env
chmod 600 container/.env
echo "wrote container/.env"

echo "Building and starting tenant '${TENANT}'..."
docker compose -p "h-flock-${TENANT}" --env-file container/.env -f container/compose.yaml up -d --build || exit 1

CONTAINER="h-flock-${TENANT}-tenant-1"
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

echo
echo "Tenant '${TENANT}' up."
SCHEME=http; [ -n "$TLS_CERT" ] && SCHEME=https
echo "  api      ${SCHEME}://127.0.0.1:8080   token in container/.env"
echo "  session  ws://127.0.0.1:8081/session"
echo "  attach   docker exec -it -e TMUX_TMPDIR=/home/ubuntu/.flock/tmux $CONTAINER tmux attach -t ${TENANT}"
echo
echo "Accounts still needing a login:"
./container/seed-home.sh check "$CONTAINER"
echo
echo "  Log in inside an agent's window, then save it so the next rebuild keeps it:"
echo "    ./container/seed-home.sh out $CONTAINER"
