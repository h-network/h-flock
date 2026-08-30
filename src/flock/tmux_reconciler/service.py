import json
import os
import time
import redis
from typing import Set

from flock.bus import members, log_record, port_type, prefix
import flock.tmux.ops as tmux_ops
from flock.tmux.ops import generate_agents_md, ensure_claude_project_trusted, write_agent_guide, window_env

OFFICE_TOOLS_ENV = "OFFICE_TOOLS=office"


class TmuxReconciler:
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

    def get_agent_profile(self, r: redis.Redis, agent: str) -> str | None:
        profile_key = prefix(self.pod, self.tenant, agent=agent, resource="profile")
        raw_prof = r.get(profile_key)
        if not raw_prof:
            return None
        return raw_prof.decode() if isinstance(raw_prof, bytes) else raw_prof

    def get_agent_provider(self, r: redis.Redis, agent: str) -> dict | None:
        """The model provider this agent runs against, or None for the vendor's.

        ⚠ The NAME lives per agent; the address lives in the tenant's
        environment. A url in a Redis value would be an provider an agent could
        read and change, and the roster is a MAC table — membership and port_type,
        nothing else.
        """
        key = prefix(self.pod, self.tenant, agent=agent, resource="provider")
        raw = r.get(key)
        if not raw:
            return None
        name = (raw.decode() if isinstance(raw, bytes) else raw).strip()
        if not name:
            return None
        upper = name.upper().replace("-", "_")
        url = os.environ.get(f"PROVIDER_{upper}_URL")
        if not url:
            log_record("tmux_reconciler", "error", destination=agent,
                       reason=f"provider '{name}' has no PROVIDER_{upper}_URL")
            return None
        return {
            "name": name,
            "url": url,
            "token": os.environ.get(f"PROVIDER_{upper}_TOKEN"),
            "model": os.environ.get(f"PROVIDER_{upper}_MODEL"),
            "small_model": os.environ.get(f"PROVIDER_{upper}_SMALL_MODEL"),
        }

    def get_lead(self, r: redis.Redis) -> str | None:
        lead_key = prefix(self.pod, self.tenant, resource="lead")
        raw_lead = r.get(lead_key)
        if not raw_lead:
            return None
        return raw_lead.decode() if isinstance(raw_lead, bytes) else str(raw_lead)

    def consume_creation_correlation(self, r: redis.Redis, agent: str) -> str | None:
        """Consume the one-shot hire cause for a newly created window.

        Consumption before logging prefers an absent join over a stale, false
        join if tmux_reconciler dies between the Redis operation and stdout.
        """
        key = prefix(self.pod, self.tenant, agent=agent, resource="window.cause")
        raw = r.getdel(key)
        if not raw:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    def get_agent_resume(self, r: redis.Redis, agent: str) -> str | None:
        key = prefix(self.pod, self.tenant, agent=agent, resource="resume")
        val = r.get(key)
        return val.decode() if isinstance(val, bytes) else (str(val) if val is not None else None)

    def get_agent_skip_permissions(self, r: redis.Redis, agent: str) -> bool | None:
        key = prefix(self.pod, self.tenant, agent=agent, resource="skip-permissions")
        val = r.get(key)
        if val is None:
            return None
        val = val.decode() if isinstance(val, bytes) else val
        return val == "1"

    def get_agent_claude_tools(self, r: redis.Redis, agent: str) -> str | None:
        # ⚠ `None` (key absent) and `""` (published, unrestricted) are both
        # legitimate returns here and mean different things downstream --
        # do not coalesce them.
        key = prefix(self.pod, self.tenant, agent=agent, resource="claude-tools")
        val = r.get(key)
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else val

    def log_window_created(self, r: redis.Redis, agent: str) -> None:
        log_record(
            "tmux_reconciler", "window_created", destination=agent,
            correlation_id=self.consume_creation_correlation(r, agent),
        )

    def ensure_server_and_session(
        self,
        r: redis.Redis,
        initial_window: str = "__init__",
        cli: str | None = None,
        profile: str | None = None,
        lead: str | None = None,
        provider: dict | None = None,
        resume: bool | None = None,
        skip_permissions: bool | None = None,
        claude_tools: str | None = None,
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
                write_agent_guide(cwd, initial_window, self.tenant, lead=lead, profile=profile)
                if cli:
                    if resume is None:
                        should_resume = tmux_ops.has_session_history(initial_window, cli, profile=profile)
                    else:
                        should_resume = resume
                    cmd_args = tmux_ops.start_agent_command(cli, resume=should_resume)
                else:
                    cmd_args = ["bash", "-il"]
                cmd.extend(
                    window_env(
                        initial_window, tenant=self.tenant, cwd=cwd, profile=profile, provider=provider,
                        skip_permissions=skip_permissions, claude_tools=claude_tools,
                    )
                    + cmd_args
                )

            code, out, err = tmux_ops.run_tmux(*cmd, socket=self.socket)
            if code != 0:
                log_record("tmux_reconciler", "error", reason=f"Failed to create tmux session: {err}")
            elif initial_window != "__init__":
                self.log_window_created(r, initial_window)

        # Set session & server options
        tmux_ops.run_tmux("set-option", "-g", "exit-empty", "off", socket=self.socket)
        tmux_ops.run_tmux("set-option", "-g", "default-size", "120x32", socket=self.socket)
        tmux_ops.run_tmux("set-option", "-g", "history-limit", "2000", socket=self.socket)

    def get_windows(self) -> Set[str]:
        return tmux_ops.list_windows(self.session_name, socket=self.socket)

    def create_window(
        self,
        r: redis.Redis,
        agent_name: str,
        cli: str | None = None,
        profile: str | None = None,
        cwd: str | None = None,
        lead: str | None = None,
        provider: dict | None = None,
        resume: bool | None = None,
        skip_permissions: bool | None = None,
        claude_tools: str | None = None,
    ) -> bool:
        cwd = cwd or f"/workdir/{agent_name}"
        env_args = window_env(
            agent_name, tenant=self.tenant, cwd=cwd, profile=profile, provider=provider,
            skip_permissions=skip_permissions, claude_tools=claude_tools,
        )

        # ⚠ Not written here — tmux_ops.create_window below writes it for every
        # caller, and writing it twice is what dropped the lead sentence.
        if cli:
            if resume is None:
                should_resume = tmux_ops.has_session_history(agent_name, cli, profile=profile)
            else:
                should_resume = resume
            command = env_args + tmux_ops.start_agent_command(cli, resume=should_resume)
        else:
            command = env_args + ["bash", "-il"]

        ret, stdout, stderr = tmux_ops.create_window(
            self.session_name, agent_name, command=command, cwd=cwd, socket=self.socket,
            lead=lead, profile=profile
        )
        if ret == 0:
            self.log_window_created(r, agent_name)
            return True
        else:
            log_record("tmux_reconciler", "error", destination=agent_name, reason=f"new-window failed: {stderr}")
            return False

    def kill_window(self, window_name: str) -> bool:
        ret, stdout, stderr = tmux_ops.kill_window(self.session_name, window_name, socket=self.socket)
        if ret == 0:
            log_record("tmux_reconciler", "window_killed", destination=window_name)
            return True
        else:
            log_record("tmux_reconciler", "error", destination=window_name, reason=f"kill-window failed: {stderr}")
            return False

    def reconcile_once(self, r: redis.Redis) -> None:
        all_members = members(r, pod=self.pod, tenant=self.tenant)
        roster_agents = {
            a for a in all_members
            if port_type(r, pod=self.pod, tenant=self.tenant, agent=a) == "tmux"
        }
        lead = self.get_lead(r)
        first_agent = sorted(list(roster_agents))[0] if roster_agents else "__init__"
        first_cli = self.get_agent_cli(r, first_agent) if first_agent != "__init__" else None
        first_profile = self.get_agent_profile(r, first_agent) if first_agent != "__init__" else None
        first_provider = self.get_agent_provider(r, first_agent) if first_agent != "__init__" else None
        first_resume_raw = self.get_agent_resume(r, first_agent) if first_agent != "__init__" else None
        first_resume = True if first_resume_raw == "1" else (False if first_resume_raw == "0" else None)
        first_skip_permissions = (
            self.get_agent_skip_permissions(r, first_agent) if first_agent != "__init__" else None
        )
        first_claude_tools = (
            self.get_agent_claude_tools(r, first_agent) if first_agent != "__init__" else None
        )

        self.ensure_server_and_session(
            r,
            initial_window=first_agent,
            cli=first_cli,
            profile=first_profile,
            lead=lead,
            provider=first_provider,
            resume=first_resume,
            skip_permissions=first_skip_permissions,
            claude_tools=first_claude_tools,
        )

        existing_windows = self.get_windows()

        # Create missing agent windows first
        for agent in sorted(list(roster_agents)):
            if agent not in existing_windows:
                cli = self.get_agent_cli(r, agent)
                profile = self.get_agent_profile(r, agent)
                provider = self.get_agent_provider(r, agent)
                resume_raw = self.get_agent_resume(r, agent)
                resume = True if resume_raw == "1" else (False if resume_raw == "0" else None)
                skip_permissions = self.get_agent_skip_permissions(r, agent)
                claude_tools = self.get_agent_claude_tools(r, agent)
                self.create_window(
                    r, agent, cli=cli, profile=profile, lead=lead, provider=provider, resume=resume,
                    skip_permissions=skip_permissions, claude_tools=claude_tools,
                )

        # A cause marker beside an already-present window did not cause that
        # window. Consume it without attaching it to a later crash recovery.
        for agent in roster_agents & existing_windows:
            self.consume_creation_correlation(r, agent)

        # Re-fetch after creations to decide cleanup
        existing_windows = self.get_windows()

        # Remove windows that are no longer in roster.
        #
        # ⚠ The session must keep at least one window or tmux exits, but the
        # guard used to mean a RETIRED AGENT'S window survived forever when it
        # was the last one — an office showing a name that is no longer a member,
        # which is the "present but unaddressable" state we work hardest to
        # avoid. Put up the placeholder the empty-roster path already uses, then
        # retire the agent properly.
        stale = [w for w in sorted(existing_windows) if w not in roster_agents]
        if stale and len(stale) == len(existing_windows):
            placeholder = "__init__"
            if placeholder not in existing_windows:
                ret, _, stderr = tmux_ops.create_window(
                    self.session_name, placeholder, command=["bash", "-il"], socket=self.socket
                )
                if ret == 0:
                    existing_windows.add(placeholder)
                else:
                    log_record("tmux_reconciler", "error", destination=placeholder,
                               reason=f"placeholder window failed, keeping stale window: {stderr}")
        for window in stale:
            if len(existing_windows) > 1:
                if self.kill_window(window):
                    existing_windows.remove(window)

    def run_forever(self) -> None:
        r = redis.Redis.from_url(self.redis_url)
        log_record("tmux_reconciler", "started", reason=f"session={self.session_name}")
        while True:
            try:
                self.reconcile_once(r)
            except Exception as e:
                log_record("tmux_reconciler", "error", reason=f"Reconciliation exception: {e}")
            time.sleep(self.poll_seconds)
