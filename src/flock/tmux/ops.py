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


def run_tmux(*args: str, socket: str | None = None, input_data: str | None = None) -> tuple[int, str, str]:
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
    socket: str | None = None,
) -> tuple[int, str, str]:
    if not command:
        command = ["env", f"AGENT_NAME={agent_name}", "bash", "-il"]

    args = ["new-window", "-t", f"{session_name}:", "-n", agent_name]
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
    # -p brackets the paste; -d deletes the buffer as part of it, so the common
    # path is one call fewer than a separate delete-buffer.
    run_tmux("paste-buffer", "-b", buf_name, "-p", "-d", "-t", target, socket=socket)
    time.sleep(ENTER_DELAY)
    run_tmux("send-keys", "-t", target, "Enter", socket=socket)
    # Only reachable if paste-buffer failed — -d consumed it on success.
    run_tmux("delete-buffer", "-b", buf_name, socket=socket)
