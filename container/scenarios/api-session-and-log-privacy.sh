#!/usr/bin/env bash
# container/scenarios/api-session-and-log-privacy.sh
# Tests session WebSocket door auth, query parameter token support, close codes, and stdout log privacy.

SESSION_HOST="${SESSION_HOST:-localhost:8111}"
TOKEN="${API_TOKEN:-7af3ad5eb2cac57e9ca97a953908ef09}"
CONTAINER_NAME="${CONTAINER_NAME:-api-lab-tenant-1}"

echo "=== Scenario: Session WebSocket Door & Log Privacy ==="
echo "Target Session Host: ${SESSION_HOST}"
echo "Target Container: ${CONTAINER_NAME}"

echo "[1] Testing WebSocket connection with invalid token query parameter..."
docker exec "${CONTAINER_NAME}" /opt/flock/bin/python3 -c "
import asyncio, websockets

async def main():
    uri = 'ws://127.0.0.1:8081/session?token=wrong_token'
    try:
        async with websockets.connect(uri) as ws:
            print('Connected unexpectedly!')
    except websockets.exceptions.InvalidStatusCode as e:
        print(f'Handshake status code: {e.status_code}')
    except websockets.exceptions.ConnectionClosed as e:
        print(f'Connection closed: code={e.rcvd.code}, reason=\"{e.rcvd.reason}\"')
    except Exception as e:
        print(f'Observed exception: {type(e).__name__}: {e}')

asyncio.run(main())
"

echo -e "\n[2] Testing WebSocket connection with valid token query parameter..."
docker exec "${CONTAINER_NAME}" /opt/flock/bin/python3 -c "
import asyncio, json, websockets

async def main():
    uri = 'ws://127.0.0.1:8081/session?token=${TOKEN}'
    try:
        async with websockets.connect(uri) as ws:
            print('Successfully connected to session socket!')
            sub_msg = json.dumps({'subscribe': ['architect']})
            await ws.send(sub_msg)
            reply = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f'Received frame: {reply[:100]}...')
    except Exception as e:
        print(f'Observed exception: {type(e).__name__}: {e}')

asyncio.run(main())
"

echo -e "\n[3] Verification: Checking container logs for API token leakage..."
FOUND_TOKEN=$(docker logs "${CONTAINER_NAME}" 2>&1 | grep "${TOKEN}" | wc -l)
echo "Occurrences of token '${TOKEN}' in docker logs for ${CONTAINER_NAME}: ${FOUND_TOKEN}"

echo -e "\n=== Scenario Complete ==="
