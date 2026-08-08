"""Agent-facing commands for hiring and letting go."""

import argparse
import os
from collections.abc import Sequence

import redis

from flock.tmux import create_window, kill_window, run_tmux

from .openers import pause_agent, resume_agent, start_agent, stop_agent

_REDIS_URL = "redis://127.0.0.1:6379/0"


def _context() -> tuple[object, str, str, str, str | None]:
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    session_name = os.environ.get("TMUX_SESSION", tenant)
    socket = os.environ.get("TMUX_SOCKET")
    return redis.Redis.from_url(_REDIS_URL), pod, tenant, session_name, socket


def _check_tmux(operation: str, result: tuple[int, str, str]) -> None:
    code, _, stderr = result
    if code != 0:
        raise RuntimeError(f"{operation} failed: {stderr}")


def hire_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hire",
        description="Enrol a new agent and start its CLI in a new window.",
    )
    parser.add_argument("agent", help="name for the new agent")
    parser.add_argument("--cli", default="claude", help="CLI to start (default: claude)")
    args = parser.parse_args(argv)

    r, pod, tenant, session_name, socket = _context()

    def create(agent: str, cli: str) -> None:
        _check_tmux(
            "create-window",
            create_window(
                session_name,
                agent,
                command=["env", f"AGENT_NAME={agent}", cli],
                socket=socket,
            ),
        )

    try:
        start_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope={"payload": {"agent": args.agent, "cli": args.cli}},
            create_window=create,
        )
    except Exception as exc:
        parser.exit(1, f"hire: error: {exc}\n")


def let_go_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="letGo",
        description="Remove an agent and stop its window.",
    )
    parser.add_argument("agent", help="agent to remove")
    args = parser.parse_args(argv)

    r, pod, tenant, session_name, socket = _context()

    def kill(agent: str) -> None:
        _check_tmux("kill-window", kill_window(session_name, agent, socket=socket))

    try:
        stop_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope={"payload": {"agent": args.agent}},
            kill_window=kill,
        )
    except Exception as exc:
        parser.exit(1, f"letGo: error: {exc}\n")


def pause_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pause",
        description="Pause an agent's CLI while keeping its membership and window.",
    )
    parser.add_argument("agent", help="agent to pause")
    args = parser.parse_args(argv)

    r, pod, tenant, session_name, socket = _context()

    def interrupt(agent: str) -> None:
        _check_tmux(
            "pause send-keys",
            run_tmux("send-keys", "-t", f"{session_name}:{agent}", "C-c", socket=socket),
        )

    try:
        pause_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope={"payload": {"agent": args.agent}},
            interrupt_window=interrupt,
        )
    except Exception as exc:
        parser.exit(1, f"pause: error: {exc}\n")


def resume_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="resume",
        description="Resume an agent's CLI in its existing window.",
    )
    parser.add_argument("agent", help="agent to resume")
    args = parser.parse_args(argv)

    r, pod, tenant, session_name, socket = _context()

    def resume_window(agent: str) -> None:
        _check_tmux(
            "resume send-keys",
            run_tmux(
                "send-keys",
                "-t",
                f"{session_name}:{agent}",
                "startAgent --resume",
                "Enter",
                socket=socket,
            ),
        )

    try:
        resume_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope={"payload": {"agent": args.agent}},
            resume_window=resume_window,
        )
    except Exception as exc:
        parser.exit(1, f"resume: error: {exc}\n")
