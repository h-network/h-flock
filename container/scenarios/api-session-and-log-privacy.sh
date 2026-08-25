#!/usr/bin/env bash
# api-session-and-log-privacy — does the session door refuse a bad token, and
# does it keep the token out of anything it writes down?
#
#   CONTAINER=<name> bash container/scenarios/api-session-and-log-privacy.sh
#
# ⚠ This replaces a script that connected with a wrong token and, on success,
# printed "Connected unexpectedly!" — which IS the failure, reported as prose and
# returning 0. Nothing could ever have gone red.
set -uo pipefail
. "$(dirname "$0")/_lib.sh"

C="${CONTAINER:?set CONTAINER}"
TOKEN="${API_TOKEN:-$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)}"
[ -n "${TOKEN:-}" ] || incomplete api-privacy "no_api_token container=$C"

echo "== api session and log privacy · $C =="

# Ask the door, inside the container, what it does with each token. `refused` and
# `accepted` are the only two answers that mean anything; anything else is the
# script failing to ask, which must not read as a pass.
ask() {                              # ask <token> -> refused|accepted|error:...
  docker exec "$C" /opt/flock/bin/python3 -c "
import asyncio, sys, websockets
async def main():
    try:
        async with websockets.connect('ws://127.0.0.1:8081/session?token=' + sys.argv[1]):
            print('accepted')
    # ⚠ InvalidHandshake is the BASE both variants derive from. Catching
    # InvalidStatusCode by name silently stopped working at websockets 15, where
    # it became a deprecated alias that is NOT a superclass of the InvalidStatus
    # actually raised — so a door that correctly refused a bad token reported
    # `error:InvalidStatus` and the check failed against working behaviour.
    except websockets.exceptions.InvalidHandshake:
        print('refused')
    except websockets.exceptions.ConnectionClosed:
        print('refused')
    except Exception as exc:
        print('error:' + type(exc).__name__)
asyncio.run(main())
" "$1" 2>/dev/null | tail -1
}

expect "a wrong token is refused"  refused  "$(ask wrong_token)"
expect "the real token is accepted" accepted "$(ask "$TOKEN")"

# ⚠ THE PRIVACY HALF, AND IT IS THE ONE THAT MATTERS. A door that authenticates
# correctly and then writes the credential into a log has leaked it to everyone
# who can read the log — which on a container is everyone.
leaked_log="$(docker logs "$C" 2>&1 | grep -c -- "$TOKEN" || true)"
expect "the token is absent from container logs" 0 "$leaked_log"

# argv is world-readable on the container for the life of the process.
leaked_argv="$(docker exec "$C" sh -c 'cat /proc/[0-9]*/cmdline 2>/dev/null | tr "\0" " "' 2>/dev/null | grep -c -- "$TOKEN" || true)"
expect "the token is absent from process argv" 0 "$leaked_argv"

finish api-privacy
