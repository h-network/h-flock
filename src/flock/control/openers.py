"""Openers for agent lifecycle control envelopes."""

from collections.abc import Callable

from flock.bus import prefix


def _target(envelope: dict) -> tuple[str, dict]:
    payload = envelope["payload"]
    agent = payload.get("agent")
    if not isinstance(agent, str):
        raise ValueError("control payload.agent must be a string")
    # Constructing an agent key validates the target before any state changes.
    prefix("check", "check", agent=agent, resource="launch")
    return agent, payload


def start_agent(
    r,
    *,
    pod: str,
    tenant: str,
    envelope: dict,
    create_window: Callable[[str, str], object],
) -> None:
    """Enrol a tmux agent, store its launch command, then create its window."""
    agent, payload = _target(envelope)
    cli = payload.get("cli", "claude")
    if not isinstance(cli, str) or not cli:
        raise ValueError("StartAgent payload.cli must be a non-empty string")

    roster_key = prefix(pod, tenant, resource="roster")
    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    r.hset(roster_key, agent, "tmux")
    r.set(launch_key, cli)
    create_window(agent, cli)


def stop_agent(
    r,
    *,
    pod: str,
    tenant: str,
    envelope: dict,
    kill_window: Callable[[str], object],
) -> None:
    """Remove desired state before removing the agent's actual tmux window."""
    agent, _ = _target(envelope)
    roster_key = prefix(pod, tenant, resource="roster")
    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    r.hdel(roster_key, agent)
    r.delete(launch_key)
    kill_window(agent)


def pause_agent(
    r,
    *,
    pod: str,
    tenant: str,
    envelope: dict,
    interrupt_window: Callable[[str], object],
) -> None:
    """Mark an agent paused, then interrupt its CLI without changing membership."""
    agent, _ = _target(envelope)
    r.set(prefix(pod, tenant, agent=agent, resource="paused"), 1)
    interrupt_window(agent)


def resume_agent(
    r,
    *,
    pod: str,
    tenant: str,
    envelope: dict,
    resume_window: Callable[[str], object],
) -> None:
    """Clear an agent's pause marker, then resume its CLI in the existing window."""
    agent, _ = _target(envelope)
    r.delete(prefix(pod, tenant, agent=agent, resource="paused"))
    resume_window(agent)
