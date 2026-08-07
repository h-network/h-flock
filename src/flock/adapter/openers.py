import os
import subprocess
import time
import json
from typing import Set

from flock.bus import prefix, log_record


def get_tmux_windows(session_name: str, socket: str | None = None) -> Set[str]:
    cmd = ["tmux"]
    if socket:
        cmd.extend(["-S", socket])
    cmd.extend(["list-windows", "-t", session_name, "-F", "#{window_name}"])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return set()
    return {w for w in proc.stdout.splitlines() if w}


def run_tmux_cmd(args: list[str], socket: str | None = None, input_data: str | None = None) -> tuple[int, str, str]:
    cmd = ["tmux"]
    if socket:
        cmd.extend(["-S", socket])
    cmd.extend(args)
    proc = subprocess.run(cmd, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def message_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    stream_id = envelope.get("stream_id", "")
    corr_id = envelope.get("correlation_id")
    producer = envelope.get("producer", "unknown")
    recipient = envelope.get("recipient", agent)
    payload = envelope.get("payload", {})

    windows = get_tmux_windows(session_name, socket=socket)
    if recipient not in windows:
        dead_key = prefix(pod, tenant, agent=recipient, resource="dead")
        r.rpush(dead_key, json.dumps(envelope))
        log_record(
            module="adapter",
            event="dead_lettered",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=recipient,
            reason="window_missing",
        )
        return

    text = payload.get("text", "")
    formatted_msg = f"[message from {producer}] {text}\n"

    buf_name = f"flock_{stream_id[:8]}"
    # Load buffer
    run_tmux_cmd(["load-buffer", "-b", buf_name, "-"], socket=socket, input_data=formatted_msg)
    # Bracketed paste
    run_tmux_cmd(["paste-buffer", "-b", buf_name, "-p", "-t", f"{session_name}:{recipient}"], socket=socket)
    time.sleep(0.05)
    # Send Enter key
    run_tmux_cmd(["send-keys", "-t", f"{session_name}:{recipient}", "Enter"], socket=socket)
    # Clean up buffer
    run_tmux_cmd(["delete-buffer", "-b", buf_name], socket=socket)

    log_record(
        module="adapter",
        event="opened",
        stream_id=stream_id,
        correlation_id=corr_id,
        producer=producer,
        recipient=recipient,
    )
