"""One-envelope delivery routine for the control VAB."""

import subprocess

from flock.bus import log_record, receive

from .openers import pause_agent, resume_agent, start_agent, stop_agent


def _ensure_tmux(command: str, result: tuple[int, str, str]) -> None:
    code, _, stderr = result
    if code != 0:
        raise RuntimeError(f"{command} failed: {stderr}")


def _kick(agent: str) -> None:
    try:
        subprocess.Popen(["flock.adapter", agent])
    except OSError as exc:
        log_record("adapter", "error", recipient=agent, reason=f"adapter kick failed: {exc}")


def deliver_one(
    r,
    *,
    pod: str,
    tenant: str,
    agent: str,
    session_name: str,
    socket: str | None = None,
) -> None:
    """Pop and open one lifecycle envelope addressed to a control agent."""
    # The tmux lane owns this shared library. Keeping the import here lets the
    # control storage operations remain independently testable on this lane.
    from flock.tmux import create_window, kill_window, run_tmux, window_env
    import os

    from flock.bus import prefix

    def create(target: str, cli: str) -> None:
        def _value(resource: str) -> str | None:
            raw = r.get(prefix(pod, tenant, agent=target, resource=resource))
            if not raw:
                return None
            return raw.decode() if isinstance(raw, bytes) else raw

        profile = _value("profile")
        cwd = f"/workdir/{target}"

        # ⚠ StartAgent builds the window itself, so this path must resolve
        # everything tmuxhost resolves. It is not a fallback: create_window is
        # idempotent by name, so whatever this builds is what the agent keeps —
        # a reconcile afterwards will NOT correct it. Measured: an agent hired
        # onto a local endpoint came up pointed at the vendor's, because only
        # tmuxhost knew about endpoints.
        endpoint = None
        name = _value("endpoint")
        if name:
            upper = name.upper().replace("-", "_")
            url = os.environ.get(f"ENDPOINT_{upper}_URL")
            if url:
                endpoint = {
                    "name": name,
                    "url": url,
                    "token": os.environ.get(f"ENDPOINT_{upper}_TOKEN"),
                    "model": os.environ.get(f"ENDPOINT_{upper}_MODEL"),
                    "small_model": os.environ.get(f"ENDPOINT_{upper}_SMALL_MODEL"),
                }

        result = create_window(
            session_name,
            target,
            command=window_env(target, tenant=tenant, cwd=cwd, profile=profile, endpoint=endpoint)
            + ["startAgent", cli],
            socket=socket,
        )
        _ensure_tmux("create-window", result)

    def kill(target: str) -> None:
        _ensure_tmux("kill-window", kill_window(session_name, target, socket=socket))

    def interrupt(target: str) -> None:
        _ensure_tmux(
            "pause send-keys",
            run_tmux("send-keys", "-t", f"{session_name}:{target}", "C-c", socket=socket),
        )

    def resume(target: str) -> None:
        _ensure_tmux(
            "resume send-keys",
            run_tmux(
                "send-keys",
                "-t",
                f"{session_name}:{target}",
                "startAgent --resume",
                "Enter",
                socket=socket,
            ),
        )

    def handle_start(envelope: dict) -> None:
        start_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope=envelope,
            create_window=create,
        )

    def handle_stop(envelope: dict) -> None:
        stop_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope=envelope,
            kill_window=kill,
        )

    def handle_pause(envelope: dict) -> None:
        pause_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope=envelope,
            interrupt_window=interrupt,
        )

    def handle_resume(envelope: dict) -> None:
        resume_agent(
            r,
            pod=pod,
            tenant=tenant,
            envelope=envelope,
            resume_window=resume,
            kick_agent=_kick,
        )

    receive(
        r,
        pod=pod,
        tenant=tenant,
        agent=agent,
        openers={
            "StartAgent": handle_start,
            "StopAgent": handle_stop,
            "PauseAgent": handle_pause,
            "ResumeAgent": handle_resume,
        },
        timeout=1,
        module="adapter",
    )
