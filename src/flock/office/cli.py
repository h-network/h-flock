"""Focused office operations behind one collision-resistant command name."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from flock.bus import is_member, log_record, members, prefix, record_task_event, resp as redis, send, port_type

# ⚠ A tenant with a Redis password exports REDIS_URL carrying it. Without one
# this is unchanged, and an agent window still has no REDIS_URL to find.
_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_WORKDIR_ROOT = Path("/workdir")
_COMMANDS = (
    "send",
    "broadcast",
    "peers",
    "status",
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
    "cloneToAll",
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
        "status": "show agent presence and open work",
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
        "cloneToAll": "clone a repository into agent workspaces",
    }
    for name in _COMMANDS:
        subcommands.add_parser(name, help=descriptions[name], add_help=False)
    return parser


def _operation_parser(command: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"office {command}", description=description)


def _context():
    source = os.environ.get("AGENT_NAME")
    if not source:
        raise OfficeError("AGENT_NAME environment variable not set")
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    return redis.Redis.from_url(_REDIS_URL), pod, tenant, source


def _message(r, *, pod: str, tenant: str, source: str, destination: str, text: str) -> str:
    return send(
        r,
        pod=pod,
        tenant=tenant,
        source=source,
        destination=destination,
        payload={"text": text},
        kind="Message",
        module="port",
    )


def _send_command(argv: list[str]) -> None:
    parser = _operation_parser("send", "Send a message to one agent.")
    parser.add_argument("-a", "--agent", metavar="AGENT", help="destination agent")
    parser.add_argument("text", nargs=argparse.REMAINDER, help="message text")
    if argv in (["-h"], ["--help"]):
        parser.parse_args(argv)

    # Parse only the destination prefix. Everything after it is message data, not
    # CLI syntax; an inner `-a` must survive when explaining office commands.
    if len(argv) < 2 or argv[0] not in ("-a", "--agent"):
        raise OfficeError("office send requires -a <agent>")
    destination = argv[1]
    words = argv[2:]
    if not words:
        raise OfficeError("office send requires message text")

    r, pod, tenant, source = _context()
    if not is_member(r, pod=pod, tenant=tenant, agent=destination):
        raise OfficeError(f"unknown destination agent {destination!r}")
    print(_message(r, pod=pod, tenant=tenant, source=source, destination=destination, text=" ".join(words)))


def _broadcast_command(argv: list[str]) -> None:
    parser = _operation_parser("broadcast", "Send a message to every peer agent.")
    parser.add_argument("text", nargs=argparse.REMAINDER, help="message text")
    if argv in (["-h"], ["--help"]):
        parser.parse_args(argv)
    if not argv:
        raise OfficeError("office broadcast requires message text")

    r, pod, tenant, source = _context()
    recipients = sorted(
        agent
        for agent in members(r, pod=pod, tenant=tenant)
        if agent != source and port_type(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    )
    for destination in recipients:
        print(_message(r, pod=pod, tenant=tenant, source=source, destination=destination, text=" ".join(argv)))


def _peers_command(argv: list[str]) -> None:
    parser = _operation_parser("peers", "List peer agents in this office.")
    parser.parse_args(argv)
    r, pod, tenant, source = _context()
    raw_lead = r.get(prefix(pod, tenant, resource="lead"))
    lead = raw_lead.decode() if isinstance(raw_lead, bytes) else str(raw_lead) if raw_lead else None
    all_agents = sorted(members(r, pod=pod, tenant=tenant))
    peer_names = [
        agent
        for agent in all_agents
        if agent != source and port_type(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    ]
    formatted = [f"{agent} (lead)" if agent == lead else agent for agent in peer_names]
    print(", ".join(formatted))


def _timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age(value, *, now: datetime) -> str | None:
    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    seconds = max(0, int((now - timestamp).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 60 * 60:
        return f"{seconds // 60}m"
    if seconds < 24 * 60 * 60:
        return f"{seconds // (60 * 60)}h"
    return f"{seconds // (24 * 60 * 60)}d"


def _status_row(r, *, pod: str, tenant: str, agent: str, now: datetime) -> str:
    presence = r.hgetall(prefix(pod, tenant, agent=agent, resource="presence")) or {}
    decoded_presence = {_text(field): _text(value) for field, value in presence.items()}

    # The watchdog owns this key. Status only observes it, and absence before
    # build 27 is the normal case.
    #
    # ⚠ It is a HASH — {since, stream_id} — and this must not crash if it is
    # anything else. Reading it with GET raised WRONGTYPE against a hash and
    # took the whole command down, which is a poor way for a read-only status
    # view to behave. A key it cannot make sense of means "not blocked".
    try:
        blocked = r.hgetall(prefix(pod, tenant, agent=agent, resource="blocked")) or None
    except Exception:
        blocked = None
    presence_state = decoded_presence.get("state") or "unknown"
    state = "blocked" if blocked is not None else presence_state

    doing_key = prefix(pod, tenant, agent=agent, resource="tasks.doing")
    raw_ticket = next(iter(r.lrange(doing_key, 0, 0)), None)
    if raw_ticket is None:
        task = "—"
    else:
        ticket = _ticket(raw_ticket, state="doing")
        opened = _age(ticket.get("started_ts"), now=now)
        task = f'"{ticket["title"]}"' + (f" {opened}" if opened else "")

    if presence_state == "unknown":
        activity = "no activity feed"
    else:
        last = _age(decoded_presence.get("last_activity"), now=now)
        activity = f"last activity {last} ago" if last else "no activity yet"
    return f"  {agent:<12}{state:<10}{task:<35}{activity}"


def _status_command(argv: list[str]) -> None:
    parser = _operation_parser("status", "Show agent presence and open work.")
    parser.add_argument("agent", nargs="?", help="one tmux agent (default: all)")
    args = parser.parse_args(argv)
    r, pod, tenant, _ = _context()
    tmux_agents = sorted(
        agent
        for agent in members(r, pod=pod, tenant=tenant)
        if port_type(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    )
    if args.agent is not None:
        if args.agent not in tmux_agents:
            raise OfficeError(f"unknown tmux agent {args.agent!r}")
        tmux_agents = [args.agent]
    now = datetime.now(timezone.utc)
    for agent in tmux_agents:
        print(_status_row(r, pod=pod, tenant=tenant, agent=agent, now=now))


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

    r, pod, tenant, source = _context()
    stream_id = send(
        r,
        pod=pod,
        tenant=tenant,
        source=source,
        destination="host",
        payload=payload,
        kind=kinds[command],
        module="port",
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
    log_record("office", event, destination=agent, task_id=ticket["id"])


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
    r, pod, tenant, source = _context()
    if args.all:
        agents = sorted(agent for agent in members(r, pod=pod, tenant=tenant) if port_type(r, pod=pod, tenant=tenant, agent=agent) == "tmux")
    else:
        agents = [args.agent or source]
    for index, agent in enumerate(agents):
        if index:
            print()
        _list_one(r, pod=pod, tenant=tenant, agent=agent, heading=args.all)


def _take_command(argv: list[str]) -> None:
    parser = _operation_parser("take", "Move a todo or held task into doing.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, source = _context()
    keys = _task_keys(pod, tenant, source)
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
    record_task_event("take", id=ticket["id"], title=ticket["title"], agent=source, actor=source)
    _log_task("task_taken", agent=source, ticket=ticket)
    print(_serialized(ticket))


def _done_command(argv: list[str]) -> None:
    _finish_command("done", argv)


def _finish_command(action: str, argv: list[str]) -> None:
    parser = _operation_parser(action, f"{action.title()} your open task.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, source = _context()
    keys = _task_keys(pod, tenant, source)
    _, raw, ticket = _select(r, keys, ("doing",), args.id)
    _remove(r, keys["doing"], raw)
    ticket["status"] = "done" if action == "done" else "cancelled"
    ticket["done_ts"] = _now()
    r.rpush(keys["done"], _serialized(ticket))
    record_task_event(action, id=ticket["id"], title=ticket["title"], agent=source, actor=source)
    log_event = "task_done" if action == "done" else "task_cancelled"
    _log_task(log_event, agent=source, ticket=ticket)
    print(_serialized(ticket))


def _hold_command(argv: list[str]) -> None:
    parser = _operation_parser("hold", "Put your open task on hold.")
    parser.add_argument("id", nargs="?", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, source = _context()
    keys = _task_keys(pod, tenant, source)
    _, raw, ticket = _select(r, keys, ("doing",), args.id)
    _remove(r, keys["doing"], raw)
    ticket["status"] = "hold"
    r.rpush(keys["hold"], _serialized(ticket))
    record_task_event("hold", id=ticket["id"], title=ticket["title"], agent=source, actor=source)
    _log_task("task_held", agent=source, ticket=ticket)
    print(_serialized(ticket))


def _delete_command(argv: list[str]) -> None:
    parser = _operation_parser("delete", "Permanently remove a task.")
    parser.add_argument("id", help="ticket id or unique prefix")
    args = parser.parse_args(argv)
    r, pod, tenant, source = _context()
    keys = _task_keys(pod, tenant, source)
    state, raw, ticket = _select(r, keys, ("todo", "doing", "hold", "done"), args.id)
    _remove(r, keys[state], raw)
    record_task_event("delete", id=ticket["id"], title=ticket["title"], agent=source, actor=source)
    _log_task("task_deleted", agent=source, ticket=ticket)
    print(_serialized(ticket))


def _add_command(argv: list[str]) -> None:
    parser = _operation_parser("add", "Add a task to another agent's board.")
    parser.add_argument("-a", "--agent", required=True, metavar="AGENT")
    parser.add_argument("-t", "--title", required=True, metavar="TITLE")
    parser.add_argument("-d", "--description", required=True, metavar="DESCRIPTION")
    parser.add_argument("-p", "--priority", metavar="PRIORITY")
    args = parser.parse_args(argv)

    r, pod, tenant, source = _context()
    if not is_member(r, pod=pod, tenant=tenant, agent=args.agent):
        raise OfficeError(f"unknown destination agent {args.agent!r}")
    payload = {"title": args.title, "description": args.description, "priority": args.priority}
    stream_id = send(
        r,
        pod=pod,
        tenant=tenant,
        source=source,
        destination=args.agent,
        payload=payload,
        kind="AddTicket",
        module="port",
    )
    print(stream_id)


def _repo_name(repo_url: str) -> str:
    tail = repo_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    if not tail or tail in (".", ".."):
        raise OfficeError(f"cannot determine repository name from {repo_url!r}")
    return tail


def _clone_agents(r, *, pod: str, tenant: str, requested: str | None) -> list[str]:
    tmux_agents = {
        agent
        for agent in members(r, pod=pod, tenant=tenant)
        if port_type(r, pod=pod, tenant=tenant, agent=agent) == "tmux"
    }
    if requested is None:
        return sorted(tmux_agents)

    selected = list(dict.fromkeys(name.strip() for name in requested.split(",") if name.strip()))
    if not selected:
        raise OfficeError("-a requires at least one agent")
    invalid = [name for name in selected if name not in tmux_agents]
    if invalid:
        raise OfficeError(f"not a tmux agent: {', '.join(invalid)}")
    return selected


def _git_clone(source: str, target: Path, upstream: str) -> tuple[bool, str]:
    try:
        clone = subprocess.run(
            ["git", "clone", source, str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if clone.returncode:
            detail = clone.stderr.strip() or clone.stdout.strip() or "git clone failed"
            return False, detail
        remote = subprocess.run(
            ["git", "-C", str(target), "remote", "set-url", "origin", upstream],
            capture_output=True,
            text=True,
            check=False,
        )
        if remote.returncode:
            detail = remote.stderr.strip() or remote.stdout.strip() or "could not set origin"
            return False, detail
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _clone_to_all_command(argv: list[str]) -> None:
    parser = _operation_parser("cloneToAll", "Clone one repository into agent workspaces.")
    parser.add_argument("repo_url", metavar="REPO-URL")
    parser.add_argument("-a", "--agents", metavar="AGENT,...", help="comma-separated tmux agents")
    parser.add_argument("--dry-run", action="store_true", help="show actions without writing")
    args = parser.parse_args(argv)

    r, pod, tenant, _ = _context()
    agents = _clone_agents(r, pod=pod, tenant=tenant, requested=args.agents)
    repo_name = _repo_name(args.repo_url)
    targets = [(agent, _WORKDIR_ROOT / agent / repo_name) for agent in agents]

    if args.dry_run:
        skipped = 0
        for agent, target in targets:
            if target.exists():
                skipped += 1
                print(f"{agent}: exists, would skip")
            else:
                print(f"{agent}: would clone")
        print(f"summary: cloned=0 skipped={skipped} failed=0")
        return

    cloned = skipped = failed = 0
    local_source = next((target for _, target in targets if target.exists()), None)
    for agent, target in targets:
        if target.exists():
            skipped += 1
            print(f"{agent}: exists, skipped")
            continue

        source = str(local_source) if local_source is not None else args.repo_url
        ok, detail = _git_clone(source, target, args.repo_url)
        if ok:
            cloned += 1
            local_source = local_source or target
            print(f"{agent}: cloned")
        else:
            failed += 1
            if target.exists():
                shutil.rmtree(target)
            print(f"{agent}: failed: {detail}")
    print(f"summary: cloned={cloned} skipped={skipped} failed={failed}")
    if failed:
        raise OfficeError(f"{failed} clone operation(s) failed")


def main(argv: Sequence[str] | None = None) -> None:
    # ⚠ Scoped, not global. This command runs inside an agent's window, so its
    # stdout is a pane and bus telemetry printed there is a signpost the agent
    # does not need. Restore the previous value afterwards: main() is called
    # in-process by the tests, and leaking the flag silences unrelated
    # components' logging for the rest of the run.
    previous_quiet = os.environ.get("FLOCK_LOG_QUIET")
    os.environ["FLOCK_LOG_QUIET"] = "1"
    try:
        _run(list(sys.argv[1:] if argv is None else argv))
    finally:
        if previous_quiet is None:
            os.environ.pop("FLOCK_LOG_QUIET", None)
        else:
            os.environ["FLOCK_LOG_QUIET"] = previous_quiet


def _run(args: list[str]) -> None:
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
        elif command == "status":
            _status_command(remainder)
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
        elif command == "cloneToAll":
            _clone_to_all_command(remainder)
        else:
            parser.error(f"unknown command: {command}")
    except OfficeError as exc:
        print(f"office: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
