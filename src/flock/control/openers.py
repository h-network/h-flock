"""Openers for agent lifecycle control envelopes."""

from collections.abc import Callable

from flock.bus import prefix, purge_agent, port_type

_STARTABLE_VABS = {"tmux", "api"}
_FIXED_PARTICIPANTS = {"api", "host"}
_START_AGENT_KEYS = frozenset({"agent", "port_type", "cli", "profile", "provider"})
_TARGET_ONLY_KEYS = frozenset({"agent"})


def _target(envelope: dict, allowed_keys: frozenset[str]) -> tuple[str, dict]:
    payload = envelope["payload"]
    unknown_keys = sorted(set(payload) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"unknown payload key {unknown_keys[0]!r}")
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
    replace_window: Callable[[str], object],
) -> None:
    """Publish desired state; tmuxhost is the one implementation that creates windows."""
    agent, payload = _target(envelope, _START_AGENT_KEYS)
    agent_port_type = payload.get("port_type", "tmux")
    if agent_port_type not in _STARTABLE_VABS:
        raise ValueError("StartAgent payload.port_type must be 'tmux' or 'api'")

    roster_key = prefix(pod, tenant, resource="roster")
    if agent_port_type == "api":
        r.hset(roster_key, agent, agent_port_type)
        return

    cli = payload.get("cli", "claude")
    if not isinstance(cli, str) or not cli:
        raise ValueError("StartAgent payload.cli must be a non-empty string")

    profile = payload.get("profile")
    if profile:
        prefix("check", "check", agent=profile, resource="profile")
    elif profile not in (None, ""):
        raise ValueError("StartAgent payload.profile must be a segment string")

    provider = payload.get("provider")
    if provider:
        prefix("check", "check", agent=provider, resource="provider")
    elif provider not in (None, ""):
        raise ValueError("StartAgent payload.provider must be a segment string")

    existing_port_type = port_type(r, pod=pod, tenant=tenant, agent=agent)
    old_launch = r.get(prefix(pod, tenant, agent=agent, resource="launch")) if existing_port_type == "tmux" else None
    old_launch = old_launch.decode() if isinstance(old_launch, bytes) else old_launch

    config_changed = existing_port_type == "tmux" and old_launch != cli
    if profile:
        # A profile becomes part of a config-directory path. Validate it before
        # any state mutation, then persist it before roster visibility: tmuxhost
        # may reconcile as soon as the row appears and must see the right account.
        profile_key = prefix(pod, tenant, agent=agent, resource="profile")
        old_profile = r.get(profile_key) if existing_port_type == "tmux" else None
        old_profile = old_profile.decode() if isinstance(old_profile, bytes) else old_profile
        config_changed = config_changed or (existing_port_type == "tmux" and old_profile != profile)
        r.set(profile_key, profile)

    if provider:
        # Same ordering rule as profile: published before roster visibility, or
        # tmuxhost builds the window against the vendor's provider instead.
        provider_key = prefix(pod, tenant, agent=agent, resource="provider")
        old_provider = r.get(provider_key) if existing_port_type == "tmux" else None
        old_provider = old_provider.decode() if isinstance(old_provider, bytes) else old_provider
        config_changed = config_changed or (existing_port_type == "tmux" and old_provider != provider)
        r.set(provider_key, provider)

    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    # Publish all launch state before roster membership: tmuxhost reconciles on
    # that row and an early window cannot be corrected by name-idempotent create.
    r.set(launch_key, cli)
    r.hset(roster_key, agent, agent_port_type)
    if config_changed:
        # Remove only stale actual state. tmuxhost observes the roster row and
        # recreates the window through its canonical lead/profile/provider path.
        replace_window(agent)


def stop_agent(
    r,
    *,
    pod: str,
    tenant: str,
    envelope: dict,
    kill_window: Callable[[str], object],
) -> None:
    """Remove desired state, then any port_type-specific state or actual window."""
    agent, _ = _target(envelope, _TARGET_ONLY_KEYS)
    if agent in _FIXED_PARTICIPANTS:
        raise ValueError(f"cannot stop fixed participant: {agent}")
    roster_key = prefix(pod, tenant, resource="roster")
    agent_port_type = port_type(r, pod=pod, tenant=tenant, agent=agent)
    r.hdel(roster_key, agent)
    purge_agent(r, pod=pod, tenant=tenant, agent=agent)
    if agent_port_type != "api":
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
    agent, _ = _target(envelope, _TARGET_ONLY_KEYS)
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
    agent, _ = _target(envelope, _TARGET_ONLY_KEYS)
    r.delete(prefix(pod, tenant, agent=agent, resource="paused"))
    resume_window(agent)
    depth = r.llen(prefix(pod, tenant, agent=agent, resource="ingress"))
    for _ in range(depth):
        kick_agent(agent)
