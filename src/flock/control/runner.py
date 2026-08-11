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
    from flock.tmux import kill_window, run_tmux

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
            replace_window=kill,
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
