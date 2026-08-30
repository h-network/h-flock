"""Openers for agent lifecycle control envelopes."""

import json
import time
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

_STARTABLE_VABS = {"tmux", "api", "openshell"}
_FIXED_PARTICIPANTS = {"api", "host"}
_START_AGENT_KEYS = frozenset(
    {
        "agent", "port_type", "cli", "profile", "provider", "export", "import", "resume",
        "skip_permissions", "claude_tools", "hmac_secret", "kid", "revoke_kid",
    }
)
_MIN_HMAC_SECRET_LEN = 16
_TARGET_ONLY_KEYS = frozenset({"agent"})

_PUBLISH_WINDOW_CAUSE_LUA = """
redis.call('HSET', KEYS[2], ARGV[2], ARGV[3])
redis.call('SET', KEYS[1], ARGV[1])
return 1
"""


class _IncompleteControl(RuntimeError):
    """A desired or actual-state attempt has an UNKNOWN outcome."""


class ProvableActualFailure(RuntimeError):
    """An actual-state action was observably rejected and did not occur."""


class _PartialControl(RuntimeError):
    """Some work was acknowledged before a later action provably failed."""


def _record_control(kind: str):
    """Record accepted, partially failed, incomplete, or pre-mutation failure outcomes."""
    def decorate(opener):
        @wraps(opener)
        def recorded(r, *, pod, tenant, envelope, **kwargs):
            payload = envelope.get("payload", {}) if isinstance(envelope, dict) else {}
            agent = payload.get("agent") if isinstance(payload, dict) else None
            correlation_id = envelope.get("correlation_id") if isinstance(envelope, dict) else None
            try:
                result = opener(r, pod=pod, tenant=tenant, envelope=envelope, **kwargs)
            except _PartialControl as exc:
                log_record(
                    "control", f"{kind}_partially_failed", correlation_id=correlation_id,
                    destination=agent if isinstance(agent, str) else None,
                    reason=str(exc),
                )
                raise exc.__cause__ from exc
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


def _actual_failed(
    committed: list[str],
    action: str,
    exc: ProvableActualFailure,
    *,
    actual_acknowledged: list[str] | None = None,
) -> _PartialControl:
    """Name acknowledged work and a later actual-state action known not to occur."""
    parts = [f"acknowledged: {', '.join(committed)}"]
    if actual_acknowledged:
        parts.append(f"actual acknowledged: {', '.join(actual_acknowledged)}")
    parts.append(f"{action} failed: {exc}")
    return _PartialControl("; ".join(parts))


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
    """Publish desired state; tmux_reconciler is the one implementation that creates windows."""
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
        raise ValueError(f"StartAgent payload.port_type must be one of: {', '.join(sorted(_STARTABLE_VABS))}")

    hmac_secret = payload.get("hmac_secret")
    kid = payload.get("kid")
    revoke_kid = payload.get("revoke_kid")
    if (hmac_secret is None) != (kid is None):
        raise ValueError("StartAgent payload.hmac_secret and payload.kid must be supplied together")
    if kid is not None and not (isinstance(kid, str) and SEGMENT_REGEX.fullmatch(kid)):
        raise ValueError("StartAgent payload.kid must be a segment string")
    if hmac_secret is not None and not (
        isinstance(hmac_secret, str) and len(hmac_secret) >= _MIN_HMAC_SECRET_LEN
    ):
        raise ValueError(
            f"StartAgent payload.hmac_secret must be a string of at least {_MIN_HMAC_SECRET_LEN} characters"
        )
    if revoke_kid is not None and not (isinstance(revoke_kid, str) and SEGMENT_REGEX.fullmatch(revoke_kid)):
        raise ValueError("StartAgent payload.revoke_kid must be a segment string")
    if agent_port_type != "api" and (kid is not None or revoke_kid is not None):
        raise ValueError("StartAgent payload.hmac_secret/kid/revoke_kid only apply to port_type 'api'")

    roster_key = prefix(pod, tenant, resource="roster")
    committed: list[str] = []
    if agent_port_type == "api":
        # Both self-supplied: the enrolling client generates its own secret and
        # hands it to control, rather than control minting one it has no
        # synchronous channel to hand back over (StartAgent is fire-and-forget,
        # LLD-api §6). HMAC verification needs the same secret on both sides to
        # recompute the MAC, so it is stored in the clear here, not hashed —
        # unlike a password hash, a digest of the secret could never reproduce
        # a matching signature.
        hmac_keys_key = prefix(pod, tenant, agent=agent, resource="hmac-keys")
        if revoke_kid is not None:
            _write_desired(
                committed, f"hmac key {revoke_kid!r} revoked", "hmac key revoke",
                lambda: r.hdel(hmac_keys_key, revoke_kid),
            )
        if kid is not None:
            key_record = json.dumps(
                {"secret": hmac_secret, "created_ts": time.time()}, separators=(",", ":")
            )
            _write_desired(
                committed, f"hmac key {kid!r} published", "hmac key publish",
                lambda: r.hset(hmac_keys_key, kid, key_record),
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
        return

    if agent_port_type == "openshell":
        cli = payload.get("cli", "claude")
        if not isinstance(cli, str) or not cli:
            raise ValueError("StartAgent payload.cli must be a non-empty string")

        # Same validation as the generic (tmux) branch below -- an
        # openshell agent's profile selects which CLAUDE_OAUTH_TOKEN_*/
        # CODEX_AUTH_JSON_*/AGY_AUTH_JSON_* env var `deliver_openshell`
        # reads at delivery time (flock/port/openshell.py's
        # `_exec_headless`), same naming convention `window_env` already
        # uses for tmux agents.
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
        launch_key = prefix(pod, tenant, agent=agent, resource="launch")
        _write_desired(
            committed, "launch published", "launch publish", lambda: r.set(launch_key, cli)
        )
        if profile:
            profile_key = prefix(pod, tenant, agent=agent, resource="profile")
            _write_desired(
                committed, "profile published", "profile publish",
                lambda: r.set(profile_key, profile),
            )
        _write_desired(
            committed, "roster row published", "roster row publish",
            lambda: r.hset(roster_key, agent, agent_port_type),
        )
        # Actual-state: provision the real sandbox now, synchronously.
        # Unlike tmux, which defers window creation to tmux_reconciler's async
        # reconciler (a window needs a session/server that may not exist
        # yet), an OpenShell sandbox is a single gRPC call with no
        # equivalent staged startup, so there is nothing to gain by
        # deferring it to a separate reconciler process.
        #
        # Imported here, not at module top: flock.openshell pulls in
        # grpc/protobuf, and this file is loaded for every control
        # delivery regardless of port_type.
        from flock.openshell import OpenShellClient, OpenShellUnavailable
        from flock.openshell.naming import sandbox_name, workspace_name

        client = OpenShellClient(workspace_name(pod, tenant))
        try:
            try:
                client.create_sandbox(
                    sandbox_name(agent),
                    environment={"AGENT_NAME": agent, "TENANT": tenant},
                    labels={"agent": agent},
                )
            except OpenShellUnavailable as exc:
                raise _actual_unknown(committed, "creating the sandbox", exc) from exc
        finally:
            client.close()
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
        # any state mutation, then persist it before roster visibility: tmux_reconciler
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
        # tmux_reconciler builds the window against the vendor's provider instead.
        provider_key = prefix(pod, tenant, agent=agent, resource="provider")
        old_provider = r.get(provider_key) if existing_port_type == "tmux" else None
        old_provider = old_provider.decode() if isinstance(old_provider, bytes) else old_provider
        config_changed = config_changed or (existing_port_type == "tmux" and old_provider != provider)
        _write_desired(
            committed, "provider published", "provider publish",
            lambda: r.set(provider_key, provider),
        )

    launch_key = prefix(pod, tenant, agent=agent, resource="launch")
    # Publish all launch state before roster membership: tmux_reconciler reconciles on
    # that row and an early window cannot be corrected by name-idempotent create.
    _write_desired(
        committed, "launch published", "launch publish", lambda: r.set(launch_key, cli)
    )

    resume = payload.get("resume")
    if resume is not None:
        if not isinstance(resume, bool):
            raise ValueError("StartAgent payload.resume must be a boolean")
        resume_key = prefix(pod, tenant, agent=agent, resource="resume")
        old_resume = r.get(resume_key) if existing_port_type == "tmux" else None
        old_resume = old_resume.decode() if isinstance(old_resume, bytes) else old_resume
        desired_resume = "1" if resume else "0"
        config_changed = config_changed or (existing_port_type == "tmux" and old_resume != desired_resume)
        _write_desired(
            committed, "resume published", "resume publish",
            lambda: r.set(resume_key, desired_resume),
        )

    skip_permissions = payload.get("skip_permissions")
    if skip_permissions is not None:
        if not isinstance(skip_permissions, bool):
            raise ValueError("StartAgent payload.skip_permissions must be a boolean")
        skip_key = prefix(pod, tenant, agent=agent, resource="skip-permissions")
        old_skip = r.get(skip_key) if existing_port_type == "tmux" else None
        old_skip = old_skip.decode() if isinstance(old_skip, bytes) else old_skip
        desired_skip = "1" if skip_permissions else "0"
        config_changed = config_changed or (existing_port_type == "tmux" and old_skip != desired_skip)
        _write_desired(
            committed, "skip_permissions published", "skip_permissions publish",
            lambda: r.set(skip_key, desired_skip),
        )

    # ⚠ Presence, not truthiness: `""` (unrestricted tools) is a valid desired
    # value, distinct from the key being absent from the payload at all — same
    # "absent is not empty" rule `window_env` applies on the way out.
    if "claude_tools" in payload:
        claude_tools = payload["claude_tools"]
        if not isinstance(claude_tools, str):
            raise ValueError("StartAgent payload.claude_tools must be a string")
        tools_key = prefix(pod, tenant, agent=agent, resource="claude-tools")
        old_tools = r.get(tools_key) if existing_port_type == "tmux" else None
        old_tools = old_tools.decode() if isinstance(old_tools, bytes) else old_tools
        config_changed = config_changed or (existing_port_type == "tmux" and old_tools != claude_tools)
        _write_desired(
            committed, "claude_tools published", "claude_tools publish",
            lambda: r.set(tools_key, claude_tools),
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
    correlation_id = envelope.get("correlation_id")
    if existing_port_type != "tmux" and isinstance(correlation_id, str) and correlation_id:
        # A fresh tmux membership makes a later window necessary. Publish its
        # cause before roster visibility so tmux_reconciler cannot observe the hire
        # without also observing the join key. Idempotent starts do not replace
        # this marker: their envelope did not cause a new window.
        cause_key = prefix(pod, tenant, agent=agent, resource="window.cause")
        _write_desired(
            committed,
            "window cause and roster row published",
            "window cause and roster row publish",
            lambda: r.eval(
                _PUBLISH_WINDOW_CAUSE_LUA,
                2,
                cause_key,
                roster_key,
                correlation_id,
                agent,
                agent_port_type,
            ),
        )
    else:
        _write_desired(
            committed, "roster row published", "roster row publish",
            lambda: r.hset(roster_key, agent, agent_port_type),
        )
    if config_changed:
        # Remove only stale actual state. tmux_reconciler observes the roster row and
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
    if agent_port_type == "openshell":
        # Imported here, not at module top -- see start_agent's openshell
        # branch for why (flock.openshell pulls in grpc/protobuf, paid only
        # for openshell deliveries/control actions, not every one).
        from flock.openshell import OpenShellClient, OpenShellUnavailable
        from flock.openshell.naming import sandbox_name, workspace_name

        client = OpenShellClient(workspace_name(pod, tenant))
        try:
            try:
                client.delete_sandbox(sandbox_name(agent))
            except OpenShellUnavailable as exc:
                raise _actual_unknown(committed, "deleting the sandbox", exc) from exc
        finally:
            client.close()
    elif agent_port_type != "api":
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
        except ProvableActualFailure as exc:
            raise _actual_failed(
                committed, f"kick {index + 1}", exc,
                actual_acknowledged=actual_acknowledged,
            ) from exc
        except Exception as exc:
            raise _actual_unknown(
                committed, f"kick {index + 1}", exc,
                actual_acknowledged=actual_acknowledged,
            ) from exc
