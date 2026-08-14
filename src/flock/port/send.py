import os
import sys
import json
import argparse
from flock.bus import send
from flock.bus import resp as redis


def main() -> None:
    agent_name = os.environ.get("AGENT_NAME")
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    if not agent_name:
        sys.stderr.write("Error: AGENT_NAME environment variable not set.\n")
        sys.exit(1)

    parser = argparse.ArgumentParser(prog="send", description="Send an envelope on the flock bus.", add_help=False)
    parser.add_argument("--kind", default="Message", help="Envelope kind")
    parser.add_argument("--payload", help="JSON payload string")
    parser.add_argument("--help", "-h", action="store_true", help="Show help")

    args, positional = parser.parse_known_args()

    if args.help or (not positional and not args.payload):
        sys.stderr.write("Usage: send <recipient> <text>...\n       send --kind <kind> <recipient> --payload '<json>'\n")
        sys.exit(0 if args.help else 1)

    if args.payload is not None:
        if not positional:
            sys.stderr.write("Error: Missing recipient argument.\n")
            sys.exit(1)
        recipient = positional[0]
        try:
            payload = json.loads(args.payload)
        except Exception as e:
            sys.stderr.write(f"Error: Invalid payload JSON: {e}\n")
            sys.exit(1)
        kind = args.kind
    else:
        recipient = positional[0]
        text_words = positional[1:]
        text_content = " ".join(text_words)
        kind = args.kind
        payload = {"text": text_content}

    try:
        r = redis.Redis.from_url(redis_url)
        send(
            r,
            pod=pod,
            tenant=tenant,
            producer=agent_name,
            recipient=recipient,
            payload=payload,
            kind=kind,
        )
    except Exception as e:
        sys.stderr.write(f"Error sending message: {e}\n")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
