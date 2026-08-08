import os
import subprocess
import time
from typing import Set


# Seconds between the paste and the Enter. `paste-buffer -p` only emits the
# bracket markers when the application has asked for bracketed paste mode; a
# CLI that never does gets the old behaviour, and this delay is what that case
# still relies on. 0.15 is the value h-office arrived at in the field after
# roughly one delivery in ten was left sitting in an input box.
ENTER_DELAY = float(os.environ.get("PASTE_ENTER_DELAY", "0.15"))


class AmbientTmuxError(RuntimeError):
    """Refused to drive a tmux server we were not explicitly pointed at."""


def require_isolated_tmux(socket: str | None = None) -> None:
    """Refuse to touch whatever tmux server happens to be ambient.

    With no explicit socket and no TMUX_TMPDIR, tmux uses /tmp/tmux-$UID/default
    — which, for anything developed inside an office, is the office's own server.
    A reconcile then deletes every window not in the roster it was given, and a
    control-mode client can drive every pane on it. That has destroyed this
    office twice, both times with a warning already written in the docs.

    The container always sets TMUX_TMPDIR, so this costs nothing in production
    and stops the accident everywhere else.
    """
    if socket or os.environ.get("TMUX_SOCKET") or os.environ.get("TMUX_TMPDIR"):
        return
    inside = " You are inside a tmux session right now." if os.environ.get("TMUX") else ""
    raise AmbientTmuxError(
        "refusing to use the ambient tmux server: neither TMUX_TMPDIR nor an "
        "explicit socket is set, so this would drive /tmp/tmux-$UID/default."
        + inside
        + " Set TMUX_TMPDIR=$(mktemp -d) for a scratch server, or pass socket=."
    )


def run_tmux(*args: str, socket: str | None = None, input_data: str | None = None) -> tuple[int, str, str]:
    require_isolated_tmux(socket)
    cmd = ["tmux"]
    if socket:
        cmd.extend(["-S", socket])
    cmd.extend(args)
    proc = subprocess.run(cmd, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def list_windows(session_name: str, socket: str | None = None) -> Set[str]:
    ret, stdout, _ = run_tmux("list-windows", "-t", session_name, "-F", "#{window_name}", socket=socket)
    if ret != 0:
        return set()
    return {w for w in stdout.splitlines() if w}


def create_window(
    session_name: str,
    agent_name: str,
    command: list[str] | None = None,
    cwd: str | None = None,
    socket: str | None = None,
) -> tuple[int, str, str]:
    if cwd is None:
        cwd = f"/workdir/{agent_name}"

    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError:
        pass

    if not command:
        command = ["env", f"AGENT_NAME={agent_name}", "bash", "-il"]

    args = ["new-window", "-t", f"{session_name}:", "-n", agent_name, "-c", cwd]
    args.extend(command)
    return run_tmux(*args, socket=socket)


def kill_window(session_name: str, window_name: str, socket: str | None = None) -> tuple[int, str, str]:
    return run_tmux("kill-window", "-t", f"{session_name}:{window_name}", socket=socket)


def paste_text(
    session_name: str,
    agent_name: str,
    text: str,
    stream_id: str = "",
    socket: str | None = None,
) -> None:
    target = f"{session_name}:{agent_name}"
    buf_name = f"flock_{stream_id[:8]}" if stream_id else f"flock_{os.urandom(4).hex()}"

    run_tmux("load-buffer", "-b", buf_name, "-", socket=socket, input_data=text)
    run_tmux("paste-buffer", "-b", buf_name, "-p", "-d", "-t", target, socket=socket)
    time.sleep(ENTER_DELAY)
    run_tmux("send-keys", "-t", target, "Enter", socket=socket)
    run_tmux("delete-buffer", "-b", buf_name, socket=socket)
