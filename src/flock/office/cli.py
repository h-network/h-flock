"""Focused office operations behind one collision-resistant command name."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

import redis

from flock.bus import is_member, log_record, members, prefix, record_task_event, send, vab

_REDIS_URL = "redis://127.0.0.1:6379/0"
_COMMANDS = (
    "send",
    "broadcast",
    "peers",
    "hire",
    "letGo",
    "pause",
    "resume",
    "list",
    "take",
    "done",
    "cancel",
    "hold",
    "delete",
    "add",
)


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
        "list": "show a task board",
        "take": "take your next todo task",
        "done": "finish your open task",
        "cancel": "cancel your open task",
        "hold": "put your open task on hold",
        "delete": "permanently remove a task",
        "add": "add a task to another agent's board",
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


def _task_keys(pod: str, tenant: str, agent: str) -> dict[str, str]:
    return {
        state: prefix(pod, tenant, agent=agent, resource=f"tasks.{state}")
        for state in ("todo", "doing", "hold", "done")
    }


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ticket(raw, *, state: str) -> dict:
    try:
        ticket = json.loads(_text(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise OfficeError("board entry is not a valid ticket") from exc
    if not isinstance(ticket, dict):
        raise OfficeError("board entry is not a valid ticket")
    task_id = ticket.get("id")
    title = ticket.get("title")
    if not isinstance(task_id, str) or not task_id:
        raise OfficeError("board entry has no valid task id")
    if not isinstance(title, str):
        raise OfficeError("board entry has no valid title")
    normalized = {
        "v": ticket.get("v", 1),
        "id": task_id,
        "title": title,
        "description": ticket.get("description", ""),
        "created_by": ticket.get("created_by", ticket.get("from", "unknown")),
        "status": ticket.get("status", state),
        "created_ts": ticket.get("created_ts", ticket.get("created_at", "")),
        "started_ts": ticket.get("started_ts"),
        "done_ts": ticket.get("done_ts"),
    }
    if ticket.get("priority") is not None:
        normalized["priority"] = ticket["priority"]
    return normalized


def _serialized(ticket: dict) -> str:
    return json.dumps(ticket, separators=(",", ":"))


def _entries(r, keys: dict[str, str], states: Sequence[str]):
    for state in states:
        for raw in r.lrange(keys[state], 0, -1):
            yield state, raw, _ticket(raw, state=state)


def _select(r, keys: dict[str, str], states: Sequence[str], reference: str | None):
    entries = list(_entries(r, keys, states))
    if reference is None:
        if not entries:
            raise OfficeError("you have no open task")
        if len(entries) != 1:
            raise OfficeError("more than one task matches; specify an id")
        return entries[0]
    matches = [entry for entry in entries if entry[2]["id"].startswith(reference)]
    if not matches:
        raise OfficeError(f"no task matches id {reference!r}")
    if len(matches) != 1:
        raise OfficeError(f"task id {reference!r} is ambiguous")
    return matches[0]


def _remove(r, key: str, raw) -> None:
    if not r.lrem(key, 1, raw):
        raise OfficeError("task changed while the command was running; try again")


def _log_task(event: str, *, agent: str, ticket: dict) -> None:
    log_record("office", event, recipient=agent, task_id=ticket["id"])


def _list_one(r, *, pod: str, tenant: str, agent: str, heading: bool) -> None:
    if heading:
        print(f"{agent}:")
    keys = _task_keys(pod, tenant, agent)
    indent = "  " if heading else ""
    for state in ("todo", "doing", "hold", "done"):
        print(f"{indent}{state}:")
        tickets = [_ticket(raw, state=state) for raw in r.lrange(keys[state], 0, -1)]
        if tickets:
            for ticket in tickets:
                print(f"{indent}  {ticket['id'][:8]}  {ticket['title']}")
        else:
            print(f"{indent}  (empty)")


def _list_command(argv: list[str]) -> None:
    parser = _operation_parser("list", "Show task-board titles.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("-a", "--agent", metavar="AGENT")
    target.add_argument("--all", action="store_true", help="show every agent board")
    args = parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    if args.all:
        agents = sorted(agent for agent in members(r, pod=pod, tenant=tenant) if vab(r, pod=pod, tenant=tenant, agent=agent) == "tmux")
    else:
        agents = [args.agent or producer]
    for index, agent in enumerate(agents):
        if index:
            print()
        _list_one(r, pod=pod, tenant=tenant, agent=agent, heading=args.all)


def _take_command(argv: list[str]) -> None:
    parser = _operation_parser("take", "Move a todo or held task into doing.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    keys = _task_keys(pod, tenant, producer)
    if r.llen(keys["doing"]):
        raise OfficeError("you already have one open task")
    if args.id is None:
        raw = r.lpop(keys["todo"])
        if raw is None:
            raise OfficeError("your todo is empty")
        ticket = _ticket(raw, state="todo")
    else:
        state, raw, ticket = _select(r, keys, ("todo", "hold"), args.id)
        _remove(r, keys[state], raw)
    ticket["status"] = "doing"
    ticket["started_ts"] = _now()
    ticket["done_ts"] = None
    r.rpush(keys["doing"], _serialized(ticket))
    record_task_event("take", id=ticket["id"], title=ticket["title"], agent=producer, actor=producer)
    _log_task("task_taken", agent=producer, ticket=ticket)
    print(_serialized(ticket))


def _done_command(argv: list[str]) -> None:
    _finish_command("done", argv)


def _finish_command(action: str, argv: list[str]) -> None:
    parser = _operation_parser(action, f"{action.title()} your open task.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    keys = _task_keys(pod, tenant, producer)
    _, raw, ticket = _select(r, keys, ("doing",), args.id)
    _remove(r, keys["doing"], raw)
    ticket["status"] = "done" if action == "done" else "cancelled"
    ticket["done_ts"] = _now()
    r.rpush(keys["done"], _serialized(ticket))
    record_task_event(action, id=ticket["id"], title=ticket["title"], agent=producer, actor=producer)
    log_event = "task_done" if action == "done" else "task_cancelled"
    _log_task(log_event, agent=producer, ticket=ticket)
    print(_serialized(ticket))


def _hold_command(argv: list[str]) -> None:
    parser = _operation_parser("hold", "Put your open task on hold.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    keys = _task_keys(pod, tenant, producer)
    _, raw, ticket = _select(r, keys, ("doing",), args.id)
    _remove(r, keys["doing"], raw)
    ticket["status"] = "hold"
    r.rpush(keys["hold"], _serialized(ticket))
    record_task_event("hold", id=ticket["id"], title=ticket["title"], agent=producer, actor=producer)
    _log_task("task_held", agent=producer, ticket=ticket)
    print(_serialized(ticket))


def _delete_command(argv: list[str]) -> None:
    parser = _operation_parser("delete", "Permanently remove a task.")
    parser.add_argument("id", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, producer = _context()
    keys = _task_keys(pod, tenant, producer)
    state, raw, ticket = _select(r, keys, ("todo", "doing", "hold", "done"), args.id)
    _remove(r, keys[state], raw)
    record_task_event("delete", id=ticket["id"], title=ticket["title"], agent=producer, actor=producer)
    _log_task("task_deleted", agent=producer, ticket=ticket)
    print(_serialized(ticket))


def _add_command(argv: list[str]) -> None:
    parser = _operation_parser("add", "Add a task to another agent's board.")
    parser.add_argument("-a", "--agent", required=True, metavar="AGENT")
    parser.add_argument("-t", "--title", required=True, metavar="TITLE")
    parser.add_argument("-d", "--description", required=True, metavar="DESCRIPTION")
    parser.add_argument("-p", "--priority", metavar="PRIORITY")
    args = parser.parse_args(argv)

    r, pod, tenant, producer = _context()
    if not is_member(r, pod=pod, tenant=tenant, agent=args.agent):
        raise OfficeError(f"unknown recipient agent {args.agent!r}")
    payload = {"title": args.title, "description": args.description, "priority": args.priority}
    stream_id = send(
        r,
        pod=pod,
        tenant=tenant,
        producer=producer,
        recipient=args.agent,
        payload=payload,
        kind="AddTicket",
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
        elif command == "list":
            _list_command(remainder)
        elif command == "take":
            _take_command(remainder)
        elif command == "done":
            _done_command(remainder)
        elif command == "cancel":
            _finish_command("cancel", remainder)
        elif command == "hold":
            _hold_command(remainder)
        elif command == "delete":
            _delete_command(remainder)
        elif command == "add":
            _add_command(remainder)
        else:
            parser.error(f"unknown command: {command}")
    except OfficeError as exc:
        print(f"office: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
