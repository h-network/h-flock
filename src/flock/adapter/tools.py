import argparse
import os
import sys
import redis

from flock.bus import send as send_envelope, members, is_member, vab

OFFICE_TOOLS_STR = "sendMessage,sendBroadcast,peers,hire,letGo"


def send_message_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="sendMessage",
        description="Send a message to a specific agent.",
        add_help=True,
    )
    parser.add_argument("-a", "--agent", required=False, help="Target agent recipient")
    parser.add_argument("text", nargs="*", help="Message text")

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    producer = os.environ.get("AGENT_NAME")
    if not producer:
        sys.stderr.write("Error: AGENT_NAME environment variable not set.\n")
        sys.exit(1)

    if not args.agent:
        sys.stderr.write("Error: Recipient agent required (-a <agent>).\n")
        sys.exit(1)

    if not args.text:
        sys.stderr.write("Error: Message text required.\n")
        sys.exit(1)

    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    r = redis.Redis.from_url(redis_url)
    recipient = args.agent
    message_text = " ".join(args.text)

    if not is_member(r, pod=pod, tenant=tenant, agent=recipient):
        sys.stderr.write(f"Error: Unknown recipient agent '{recipient}'.\n")
        sys.exit(1)

    send_envelope(
        r,
        pod=pod,
        tenant=tenant,
        producer=producer,
        recipient=recipient,
        payload={"text": message_text},
        kind="Message",
        module="adapter",
    )
    sys.exit(0)


def send_broadcast_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="sendBroadcast",
        description="Send a broadcast message to all peer tmux agents.",
        add_help=True,
    )
    parser.add_argument("text", nargs="*", help="Broadcast message text")

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    producer = os.environ.get("AGENT_NAME")
    if not producer:
        sys.stderr.write("Error: AGENT_NAME environment variable not set.\n")
        sys.exit(1)

    if not args.text:
        sys.stderr.write("Error: Message text required.\n")
        sys.exit(1)

    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    r = redis.Redis.from_url(redis_url)
    message_text = " ".join(args.text)

    all_members = members(r, pod=pod, tenant=tenant)
    recipients = sorted([
        m for m in all_members
        if m != producer and vab(r, pod=pod, tenant=tenant, agent=m) == "tmux"
    ])

    for target in recipients:
        send_envelope(
            r,
            pod=pod,
            tenant=tenant,
            producer=producer,
            recipient=target,
            payload={"text": message_text},
            kind="Message",
            module="adapter",
        )
    sys.exit(0)


def peers_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="peers",
        description="List peer tmux agents in this office.",
        add_help=True,
    )

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    producer = os.environ.get("AGENT_NAME")
    if not producer:
        sys.stderr.write("Error: AGENT_NAME environment variable not set.\n")
        sys.exit(1)

    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    r = redis.Redis.from_url(redis_url)

    all_members = members(r, pod=pod, tenant=tenant)
    peer_list = sorted([
        m for m in all_members
        if m != producer and vab(r, pod=pod, tenant=tenant, agent=m) == "tmux"
    ])

    print(", ".join(peer_list))
    sys.exit(0)
