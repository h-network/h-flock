import os
import subprocess
import time
import redis
from typing import Set

from flock.bus import members, log_record


def run_tmux(*args: str, socket: str | None = None) -> tuple[int, str, str]:
    cmd = ["tmux"]
    if socket:
        cmd.extend(["-S", socket])
    cmd.extend(args)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


class TmuxHost:
    def __init__(
        self,
        pod: str,
        tenant: str,
        redis_url: str,
        poll_seconds: float = 5.0,
        session_name: str | None = None,
        socket: str | None = None,
    ):
        self.pod = pod
        self.tenant = tenant
        self.redis_url = redis_url
        self.poll_seconds = poll_seconds
        self.session_name = session_name or tenant
        self.socket = socket or os.environ.get("TMUX_SOCKET")

    def ensure_server_and_session(self) -> None:
        ret, stdout, stderr = run_tmux("has-session", "-t", self.session_name, socket=self.socket)
        if ret != 0:
            # Create session detached with geometry 80x24
            code, out, err = run_tmux(
                "new-session", "-d", "-s", self.session_name, "-n", "__init__", "-x", "80", "-y", "24",
                socket=self.socket
            )
            if code != 0:
                log_record("tmuxhost", "error", reason=f"Failed to create tmux session: {err}")

        # Set session & server options
        run_tmux("set-option", "-g", "exit-empty", "off", socket=self.socket)
        run_tmux("set-option", "-g", "window-size", "manual", socket=self.socket)
        run_tmux("set-option", "-g", "history-limit", "2000", socket=self.socket)

    def get_windows(self) -> Set[str]:
        ret, stdout, stderr = run_tmux(
            "list-windows", "-t", self.session_name, "-F", "#{window_name}", socket=self.socket
        )
        if ret != 0:
            return set()
        return {w for w in stdout.splitlines() if w}

    def create_window(self, agent_name: str) -> bool:
        ret, stdout, stderr = run_tmux(
            "new-window", "-t", self.session_name, "-n", agent_name, "-e", f"AGENT_NAME={agent_name}", socket=self.socket
        )
        if ret == 0:
            log_record("tmuxhost", "window_created", recipient=agent_name)
            return True
        else:
            log_record("tmuxhost", "error", recipient=agent_name, reason=f"new-window failed: {stderr}")
            return False

    def kill_window(self, window_name: str) -> bool:
        ret, stdout, stderr = run_tmux(
            "kill-window", "-t", f"{self.session_name}:{window_name}", socket=self.socket
        )
        if ret == 0:
            log_record("tmuxhost", "window_killed", recipient=window_name)
            return True
        else:
            log_record("tmuxhost", "error", recipient=window_name, reason=f"kill-window failed: {stderr}")
            return False

    def reconcile_once(self, r: redis.Redis) -> None:
        self.ensure_server_and_session()
        roster_agents = members(r, pod=self.pod, tenant=self.tenant)
        existing_windows = self.get_windows()

        # Create missing agent windows
        for agent in roster_agents:
            if agent not in existing_windows:
                self.create_window(agent)

        # Re-fetch after creations to decide cleanup
        existing_windows = self.get_windows()

        # Remove windows that are no longer in roster
        for window in existing_windows:
            if window not in roster_agents:
                if window == "__init__" and len(existing_windows) > 1:
                    self.kill_window(window)
                elif window != "__init__":
                    self.kill_window(window)

    def run_forever(self) -> None:
        r = redis.Redis.from_url(self.redis_url)
        log_record("tmuxhost", "started", reason=f"session={self.session_name}")
        while True:
            try:
                self.reconcile_once(r)
            except Exception as e:
                log_record("tmuxhost", "error", reason=f"Reconciliation exception: {e}")
            time.sleep(self.poll_seconds)
