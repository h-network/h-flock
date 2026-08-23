"""Openers for agent lifecycle control envelopes."""

import json
from collections.abc import Callable
from functools import wraps

from flock.bus import (
    AGENT_STATE_RESOURCES,
    SEGMENT_REGEX,
    available_profiles,
    log_record,
    prefix,
    port_type,
    tags_key,
)

_STARTABLE_VABS = {"tmux", "api"}
_FIXED_PARTICIPANTS = {"api", "host"}
_START_AGENT_KEYS = frozenset(
    {"agent", "port_type", "cli", "profile", "provider", "export", "import"}
)
_TARGET_ONLY_KEYS = frozenset({"agent"})


class _IncompleteControl(RuntimeError):
    """A desired or actual-state attempt has an UNKNOWN outcome."""


def _record_control(kind: str):
    """Record accepted, incomplete, or pre-mutation failure outcomes."""
    def decorate(opener):
        @wraps(opener)
        def recorded(r, *, pod, tenant, envelope, **kwargs):
            payload = envelope.get("payload", {}) if isinstance(envelope, dict) else {}
            agent = payload.get("agent") if isinstance(payload, dict) else None
            correlation_id = envelope.get("correlation_id") if isinstance(envelope, dict) else None
            try:
                result = opener(r, pod=pod, tenant=tenant, envelope=envelope, **kwargs)
            except _IncompleteControl as exc:
                log_record(
                    "control", f"{kind}_incomplete", correlation_id=correlation_id,
                    destination=agent if isinstance(agent, str) else None,
                    reason=str(exc),
                )
                raise exc.__cause__ from exc
            except Exception as exc:
                log_record(
                    "control", f"{kind}_failed", correlation_id=correlation_id,
                    destination=agent if isinstance(agent, str) else None,
                    reason=str(exc) or type(exc).__name__,
                )
                raise
            log_record(
                "control", f"{kind}_accepted", correlation_id=correlation_id,
                destination=agent if isinstance(agent, str) else None,
            )
            return result
        return recorded
    return decorate


def _write_desired(
    committed: list[str],
    committed_label: str,
    failure_label: str,
    mutation: Callable[[], object],
) -> object:
    """Run one desired-state write and preserve the observed commit boundary."""
    try:
        result = mutation()
    except Exception as exc:
        acknowledged = f"acknowledged: {', '.join(committed)}" if committed else "none acknowledged"
        raise _IncompleteControl(
            f"{acknowledged}; {failure_label} outcome UNKNOWN after {exc}"
        ) from exc
    committed.append(committed_label)
    return result


def _actual_unknown(
    committed: list[str],
    action: str,
    exc: Exception,
    *,
    actual_acknowledged: list[str] | None = None,
) -> _IncompleteControl:
    """Describe observed acknowledgements separately from an unanswered attempt."""
    parts = [f"acknowledged: {', '.join(committed)}"]
    if actual_acknowledged:
        parts.append(f"actual acknowledged: {', '.join(actual_acknowledged)}")
    parts.append(f"{action} outcome UNKNOWN after {exc}")
    return _IncompleteControl("; ".join(parts))


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


@_record_control("start_agent")
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
    policy = {}
    policy_supplied = any(side in payload for side in ("export", "import"))
    for side in ("export", "import"):
        values = payload.get(side)
        if values is None:
            continue
        if (
            not isinstance(values, list)
            or not all(isinstance(value, str) and SEGMENT_REGEX.fullmatch(value) for value in values)
        ):
            raise ValueError(f"StartAgent payload.{side} must be a list of tag names")
        policy[side] = sorted(set(values))

    agent_port_type = payload.get("port_type", "tmux")
    if agent_port_type not in _STARTABLE_VABS:
        raise ValueError("StartAgent payload.port_type must be 'tmux' or 'api'")

    roster_key = prefix(pod, tenant, resource="roster")
    committed: list[str] = []
    if agent_port_type == "api":
        if policy_supplied:
            policy_key = tags_key(pod, tenant, agent)
            _write_desired(
                committed, "policy reset", "policy reset", lambda: r.delete(policy_key)
            )
            for side, values in policy.items():
                _write_desired(
                    committed, f"{side} policy published", f"{side} policy publish",
                    lambda side=side, values=values: r.hset(
                        policy_key, side, json.dumps(values, separators=(",", ":"))
                    ),
                )
        _write_desired(
            committed, "roster row published", "roster row publish",
            lambda: r.hset(roster_key, agent, agent_port_type),
        )
        return

    cli = payload.get("cli", "claude")
    if not isinstance(cli, str) or not cli:
        raise ValueError("StartAgent payload.cli must be a non-empty string")

    profile = payload.get("profile")
    if profile:
        prefix("check", "check", agent=profile, resource="profile")
        profiles = available_profiles(r, pod=pod, tenant=tenant)
        if profiles is not None and profile not in profiles:
            raise ValueError(
                f"unknown account {profile!r}; available accounts: {', '.join(profiles)}"
            )
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
        _write_desired(
            committed, "profile published", "profile publish",
            lambda: r.set(profile_key, profile),
        )

    if provider:
        # Same ordering rule as profile: published before roster visibility, or
        # tmuxhost builds the window against the vendor's provider instead.
        provider_key = prefix(pod, tenant, agent=agent, resource="provider")
        old_provider = r.get(provider_key) if existing_port_type == "tmux" else None
        old_provider = old_provider.decode() if isinstance(old_provider, bytes) else old_provider
        config_changed = config_changed or (existing_port_type == "tmux" and old_provider != provider)
        _write_desired(
            committed, "provider published", "provider publish",
            lambda: r.set(provider_key, provider),
        )

    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    # Publish all launch state before roster membership: tmuxhost reconciles on
    # that row and an early window cannot be corrected by name-idempotent create.
    _write_desired(
        committed, "launch published", "launch publish", lambda: r.set(launch_key, cli)
    )
    if policy_supplied:
        policy_key = tags_key(pod, tenant, agent)
        _write_desired(
            committed, "policy reset", "policy reset", lambda: r.delete(policy_key)
        )
        for side, values in policy.items():
            _write_desired(
                committed, f"{side} policy published", f"{side} policy publish",
                lambda side=side, values=values: r.hset(
                    policy_key, side, json.dumps(values, separators=(",", ":"))
                ),
            )
    _write_desired(
        committed, "roster row published", "roster row publish",
        lambda: r.hset(roster_key, agent, agent_port_type),
    )
    if config_changed:
        # Remove only stale actual state. tmuxhost observes the roster row and
        # recreates the window through its canonical lead/profile/provider path.
        try:
            replace_window(agent)
        except Exception as exc:
            raise _actual_unknown(committed, "replacing the stale window", exc) from exc


@_record_control("stop_agent")
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
    committed: list[str] = []
    _write_desired(
        committed, "roster row removed", "roster row removal",
        lambda: r.hdel(roster_key, agent),
    )
    state_keys = [
        prefix(pod, tenant, agent=agent, resource=resource)
        for resource in sorted(AGENT_STATE_RESOURCES)
    ]
    _write_desired(
        committed, "agent resources purged", "agent resource purge",
        lambda: r.delete(*state_keys),
    )
    _write_desired(
        committed, "delivery lock cleared", "delivery lock clear",
        lambda: r.hdel(prefix(pod, tenant, resource="delivering"), agent),
    )
    if agent_port_type != "api":
        try:
            kill_window(agent)
        except Exception as exc:
            raise _actual_unknown(committed, "killing the window", exc) from exc


@_record_control("pause_agent")
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
    committed: list[str] = []
    _write_desired(
        committed, "paused marker published", "paused marker publish",
        lambda: r.set(prefix(pod, tenant, agent=agent, resource="paused"), 1),
    )
    try:
        interrupt_window(agent)
    except Exception as exc:
        raise _actual_unknown(committed, "interrupting the window", exc) from exc


@_record_control("resume_agent")
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
    committed: list[str] = []
    _write_desired(
        committed, "paused marker removed", "paused marker removal",
        lambda: r.delete(prefix(pod, tenant, agent=agent, resource="paused")),
    )
    actual_acknowledged: list[str] = []
    try:
        resume_window(agent)
        actual_acknowledged.append("window resumed")
    except Exception as exc:
        raise _actual_unknown(committed, "resuming the window", exc) from exc
    try:
        depth = r.llen(prefix(pod, tenant, agent=agent, resource="ingress"))
    except Exception as exc:
        raise _actual_unknown(
            committed, "reading ingress depth", exc,
            actual_acknowledged=actual_acknowledged,
        ) from exc
    for index in range(depth):
        try:
            kick_agent(agent)
            actual_acknowledged.append(f"kick {index + 1}")
        except Exception as exc:
            raise _actual_unknown(
                committed, f"kick {index + 1}", exc,
                actual_acknowledged=actual_acknowledged,
            ) from exc
