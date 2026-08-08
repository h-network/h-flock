"""Focused office operations behind one collision-resistant command name."""

import argparse
import os
import sys
from collections.abc import Sequence

import redis

from flock.bus import is_member, members, send, vab

_REDIS_URL = "redis://127.0.0.1:6379/0"
_COMMANDS = ("send", "broadcast", "peers", "hire", "letGo", "pause", "resume")


class OfficeError(ValueError):
    """A user-facing command error."""


def _root_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="office",
        description="Message peers and manage agents in this office.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    descriptions = {
        "send": "send a message to one agent",
        "broadcast": "send a message to every peer agent",
        "peers": "list peer agents",
        "hire": "enrol a new agent",
        "letGo": "retire an agent",
        "pause": "pause an agent's CLI",
        "resume": "resume an agent's CLI and inbox",
    }
    for name in _COMMANDS:
        subcommands.add_parser(name, help=descriptions[name], add_help=False)
    return parser


def _operation_parser(command: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"office {command}", description=description)


def _context():
    producer = os.environ.get("AGENT_NAME")
    if not producer:
        raise OfficeError("AGENT_NAME environment variable not set")
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    return redis.Redis.from_url(_REDIS_URL), pod, tenant, producer


def _message(r, *, pod: str, tenant: str, producer: str, recipient: str, text: str) -> str:
    return send(
        r,
        pod=pod,
        tenant=tenant,
        producer=producer,
        recipient=recipient,
        payload={"text": text},
        kind="Message",
        module="adapter",
    )


def _send_command(argv: list[str]) -> None:
    parser = _operation_parser("send", "Send a message to one agent.")
    parser.add_argument("-a", "--agent", metavar="AGENT", help="recipient agent")
    parser.add_argument("text", nargs=argparse.REMAINDER, help="message text")
    if argv in (["-h"], ["--help"]):
        parser.parse_args(argv)

    # Parse only the recipient prefix. Everything after it is message data, not
    # CLI syntax; an inner `-a` must survive when explaining office commands.
    if len(argv) < 2 or argv[0] not in ("-a", "--agent"):
        raise OfficeError("office send requires -a <agent>")
    recipient = argv[1]
    words = argv[2:]
    if not words:
        raise OfficeError("office send requires message text")

    r, pod, tenant, producer = _context()
    if not is_member(r, pod=pod, tenant=tenant, agent=recipient):
        raise OfficeError(f"unknown recipient agent {recipient!r}")
    print(_message(r, pod=pod, tenant=tenant, producer=producer, recipient=recipient, text=" ".join(words)))


def _broadcast_command(argv: list[str]) -> None:
    parser = _operation_parser("broadcast", "Send a message to every peer agent.")
    parser.add_argument("text", nargs=argparse.REMAINDER, help="message text")
    if argv in (["-h"], ["--help"]):
        parser.parse_args(argv)
    if not argv:
        raise OfficeError("office broadcast requires message text")

    r, pod, tenant, producer = _context()
    recipients = sorted(
        agent
        for agent in members(r, pod=pod, tenant=tenant)
        if agent != producer and vab(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    )
    for recipient in recipients:
        print(_message(r, pod=pod, tenant=tenant, producer=producer, recipient=recipient, text=" ".join(argv)))


def _peers_command(argv: list[str]) -> None:
    parser = _operation_parser("peers", "List peer agents in this office.")
    parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    peer_names = sorted(
        agent
        for agent in members(r, pod=pod, tenant=tenant)
        if agent != producer and vab(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    )
    print(", ".join(peer_names))


def _control_command(command: str, argv: list[str]) -> None:
    descriptions = {
        "hire": "Enrol a new agent.",
        "letGo": "Retire an agent.",
        "pause": "Pause an agent's CLI while preserving its state.",
        "resume": "Resume an agent's CLI and queued inbox.",
    }
    kinds = {
        "hire": "StartAgent",
        "letGo": "StopAgent",
        "pause": "PauseAgent",
        "resume": "ResumeAgent",
    }
    parser = _operation_parser(command, descriptions[command])
    parser.add_argument("agent", help="target agent")
    if command == "hire":
        parser.add_argument("--cli", default="claude", help="CLI to start (default: claude)")
    args = parser.parse_args(argv)
    payload = {"agent": args.agent}
    if command == "hire":
        payload["cli"] = args.cli

    r, pod, tenant, producer = _context()
    stream_id = send(
        r,
        pod=pod,
        tenant=tenant,
        producer=producer,
        recipient="host",
        payload=payload,
        kind=kinds[command],
        module="adapter",
    )
    print(stream_id)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = _root_parser()
    if not args:
        parser.print_help()
        return
    if args[0] in ("-h", "--help"):
        parser.parse_args(args)
        return

    command, remainder = args[0], args[1:]
    try:
        if command == "send":
            _send_command(remainder)
        elif command == "broadcast":
            _broadcast_command(remainder)
        elif command == "peers":
            _peers_command(remainder)
        elif command in ("hire", "letGo", "pause", "resume"):
            _control_command(command, remainder)
        else:
            parser.error(f"unknown command: {command}")
    except OfficeError as exc:
        print(f"office: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
