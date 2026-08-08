import json
import os
import time
import redis
from typing import Set

from flock.bus import members, log_record, vab, prefix
import flock.tmux.ops as tmux_ops
from flock.tmux.ops import generate_agents_md, ensure_claude_project_trusted, write_agent_guide

OFFICE_TOOLS_ENV = "OFFICE_TOOLS=office"


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

    def get_agent_cli(self, r: redis.Redis, agent: str) -> str | None:
        launch_key = prefix(self.pod, self.tenant, agent=agent, resource="launch")
        raw_cli = r.get(launch_key)
        if not raw_cli:
            return None
        return raw_cli.decode() if isinstance(raw_cli, bytes) else raw_cli

    def ensure_server_and_session(
        self, initial_window: str = "__init__", cli: str | None = None
    ) -> None:
        ret, stdout, stderr = tmux_ops.run_tmux("has-session", "-t", self.session_name, socket=self.socket)
        if ret != 0:
            cwd = f"/workdir/{initial_window}" if initial_window != "__init__" else None
            cmd = [
                "new-session", "-d", "-s", self.session_name, "-n", initial_window, "-x", "120", "-y", "32"
            ]
            if cwd:
                try:
                    os.makedirs(cwd, exist_ok=True)
                except OSError:
                    pass
                cmd.extend(["-c", cwd])

            if initial_window != "__init__":
                guide_path = f"/workdir/{initial_window}/AGENTS.md"
                write_agent_guide(cwd, initial_window, self.tenant)
                cmd_args = ["startAgent", cli] if cli else ["bash", "-il"]
                cmd.extend([
                    "env",
                    f"AGENT_NAME={initial_window}",
                    OFFICE_TOOLS_ENV,
                    f"AGENT_GUIDE={guide_path}",
                ] + cmd_args)

            code, out, err = tmux_ops.run_tmux(*cmd, socket=self.socket)
            if code != 0:
                log_record("tmuxhost", "error", reason=f"Failed to create tmux session: {err}")
            elif initial_window != "__init__":
                log_record("tmuxhost", "window_created", recipient=initial_window)

        # Set session & server options
        tmux_ops.run_tmux("set-option", "-g", "exit-empty", "off", socket=self.socket)
        tmux_ops.run_tmux("set-option", "-g", "default-size", "120x32", socket=self.socket)
        tmux_ops.run_tmux("set-option", "-g", "history-limit", "2000", socket=self.socket)

    def get_windows(self) -> Set[str]:
        return tmux_ops.list_windows(self.session_name, socket=self.socket)

    def create_window(
        self, agent_name: str, cli: str | None = None, cwd: str | None = None
    ) -> bool:
        cwd = cwd or f"/workdir/{agent_name}"
        guide_path = f"{cwd}/AGENTS.md"

        env_args = [
            "env",
            f"AGENT_NAME={agent_name}",
            OFFICE_TOOLS_ENV,
            f"AGENT_GUIDE={guide_path}",
        ]
        if cli:
            command = env_args + ["startAgent", cli]
        else:
            command = env_args + ["bash", "-il"]

        ret, stdout, stderr = tmux_ops.create_window(
            self.session_name, agent_name, command=command, cwd=cwd, socket=self.socket
        )
        if ret == 0:
            log_record("tmuxhost", "window_created", recipient=agent_name)
            return True
        else:
            log_record("tmuxhost", "error", recipient=agent_name, reason=f"new-window failed: {stderr}")
            return False

    def kill_window(self, window_name: str) -> bool:
        ret, stdout, stderr = tmux_ops.kill_window(self.session_name, window_name, socket=self.socket)
        if ret == 0:
            log_record("tmuxhost", "window_killed", recipient=window_name)
            return True
        else:
            log_record("tmuxhost", "error", recipient=window_name, reason=f"kill-window failed: {stderr}")
            return False

    def reconcile_once(self, r: redis.Redis) -> None:
        all_members = members(r, pod=self.pod, tenant=self.tenant)
        roster_agents = {
            a for a in all_members
            if vab(r, pod=self.pod, tenant=self.tenant, agent=a) == "tmux"
        }
        first_agent = sorted(list(roster_agents))[0] if roster_agents else "__init__"
        first_cli = self.get_agent_cli(r, first_agent) if first_agent != "__init__" else None

        self.ensure_server_and_session(initial_window=first_agent, cli=first_cli)

        existing_windows = self.get_windows()

        # Create missing agent windows first
        for agent in sorted(list(roster_agents)):
            if agent not in existing_windows:
                cli = self.get_agent_cli(r, agent)
                self.create_window(agent, cli=cli)

        # Re-fetch after creations to decide cleanup
        existing_windows = self.get_windows()

        # Remove windows that are no longer in roster (never leaving 0 windows in session)
        for window in sorted(list(existing_windows)):
            if window not in roster_agents:
                if len(existing_windows) > 1:
                    if self.kill_window(window):
                        existing_windows.remove(window)

    def run_forever(self) -> None:
        r = redis.Redis.from_url(self.redis_url)
        log_record("tmuxhost", "started", reason=f"session={self.session_name}")
        while True:
            try:
                self.reconcile_once(r)
            except Exception as e:
                log_record("tmuxhost", "error", reason=f"Reconciliation exception: {e}")
            time.sleep(self.poll_seconds)
