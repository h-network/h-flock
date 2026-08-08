"""Openers for agent lifecycle control envelopes."""

from collections.abc import Callable

from flock.bus import prefix, vab

_STARTABLE_VABS = {"tmux", "api"}


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
    """Enrol a tmux agent or API client, creating only the state its VAB needs."""
    agent, payload = _target(envelope)
    agent_vab = payload.get("vab", "tmux")
    if agent_vab not in _STARTABLE_VABS:
        raise ValueError("StartAgent payload.vab must be 'tmux' or 'api'")

    roster_key = prefix(pod, tenant, resource="roster")
    if agent_vab == "api":
        r.hset(roster_key, agent, agent_vab)
        return

    cli = payload.get("cli", "claude")
    if not isinstance(cli, str) or not cli:
        raise ValueError("StartAgent payload.cli must be a non-empty string")

    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    r.hset(roster_key, agent, agent_vab)
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
    """Remove desired state, then any VAB-specific state or actual window."""
    agent, _ = _target(envelope)
    roster_key = prefix(pod, tenant, resource="roster")
    agent_vab = vab(r, pod=pod, tenant=tenant, agent=agent)
    if agent_vab == "api":
        r.hdel(roster_key, agent)
        r.delete(prefix(pod, tenant, agent=agent, resource="inbox"))
        return

    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    profile_key = prefix(pod, tenant, agent=agent, resource="profile")
    paused_key = prefix(pod, tenant, agent=agent, resource="paused")
    r.hdel(roster_key, agent)
    r.delete(launch_key, profile_key, paused_key)
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
    kick_agent: Callable[[str], object],
) -> None:
    """Clear pause, resume the CLI, then kick once per queued ingress envelope."""
    agent, _ = _target(envelope)
    r.delete(prefix(pod, tenant, agent=agent, resource="paused"))
    resume_window(agent)
    depth = r.llen(prefix(pod, tenant, agent=agent, resource="ingress"))
    for _ in range(depth):
        kick_agent(agent)
