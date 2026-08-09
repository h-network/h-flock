import json
import os
import subprocess
import time
from typing import Set


# Seconds between the paste and the Enter. `paste-buffer -p` only emits the
# bracket markers when the application has asked for bracketed paste mode; a
# CLI that never does gets the old behaviour, and this delay is what that case
# still relies on. 0.5 is the margin decision across CLIs (Claude Code Ink,
# codex, agy) to ensure Enter keystrokes are never swallowed into input boxes.
ENTER_DELAY = float(os.environ.get("PASTE_ENTER_DELAY", "0.5"))
OFFICE_TOOLS_ENV = "OFFICE_TOOLS=office"


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


def generate_agents_md(agent_name: str, tenant: str = "default", lead: str | None = None) -> str:
    if lead and agent_name == lead:
        lead_sentence = "You are the lead of this office. The other agents follow your direction, and yours is the account that decides when something is done.\n\n"
    elif lead:
        lead_sentence = f"{lead} is the lead of this office. Their direction is the office's direction.\n\n"
    else:
        lead_sentence = ""

    return f"""You are **{agent_name}**, an agent in this office.

{lead_sentence}Everything about your situation is in your environment:

    $AGENT_NAME      who you are
    $TENANT          the office you are in
    $OFFICE_TOOLS    the commands available to you

Run any of those with --help. To see who you can talk to:

    office peers

A message arrives in your terminal as `[message from <name>] …` — reply by name
with `office send -a <name> <message>`. This directory is yours; work in it.

You have a task board. Nothing will notify you about it — check it yourself:

    office list        titles waiting for you
    office take        take the next one, and it prints in full
    office done        when it is finished

Take a ticket *before* you start work, not after. `doing` is how the office
knows what you are on.
"""


def ensure_claude_project_trusted(cwd: str, profile: str | None = None) -> None:
    """⚠ Trust is written where the CLI will read it, which the profile decides.

    An agent with `profile=work` runs with CLAUDE_CONFIG_DIR=~/.claude-work and
    reads its trust from there. Writing to ~/.claude.json trusted a directory for
    an account the agent does not use — so it met the "Yes, I trust this folder"
    picker and sat on it, unreachable, while presence read `idle`.
    """
    try:
        home_dir = os.environ.get("HOME", "/home/ubuntu")
        if profile:
            config_path = os.path.join(home_dir, f".claude-{profile}", ".claude.json")
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
        else:
            config_path = os.path.join(home_dir, ".claude.json")
        data = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        if "projects" not in data or not isinstance(data["projects"], dict):
            data["projects"] = {}

        if cwd not in data["projects"] or not isinstance(data["projects"][cwd], dict):
            data["projects"][cwd] = {}

        data["projects"][cwd]["hasTrustDialogAccepted"] = True
        data["projects"][cwd]["hasCompletedProjectOnboarding"] = True

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def ensure_codex_project_trusted(cwd: str, profile: str | None = None) -> None:
    """Same as the Claude one: CODEX_HOME moves with the profile."""
    try:
        home_dir = os.environ.get("HOME", "/home/ubuntu")
        codex_dir = os.path.join(home_dir, f".codex-{profile}" if profile else ".codex")
        os.makedirs(codex_dir, exist_ok=True)
        config_path = os.path.join(codex_dir, "config.toml")

        header = f'[projects."{cwd}"]'
        entry = f'{header}\ntrust_level = "trusted"\n'

        if not os.path.exists(config_path):
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(entry)
            return

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        if header in content:
            return

        with open(config_path, "a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(f"\n{entry}")
    except Exception:
        pass


def ensure_agy_project_trusted(cwd: str) -> None:
    try:
        home_dir = os.environ.get("HOME", "/home/ubuntu")
        agy_dir = os.path.join(home_dir, ".gemini", "antigravity-cli")
        os.makedirs(agy_dir, exist_ok=True)
        config_path = os.path.join(agy_dir, "settings.json")

        data = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        if not isinstance(data, dict):
            data = {}

        data["enableTelemetry"] = False

        workspaces = data.get("trustedWorkspaces", [])
        if not isinstance(workspaces, list):
            workspaces = []

        if cwd not in workspaces:
            workspaces.append(cwd)
        data["trustedWorkspaces"] = workspaces

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def window_env(
    agent_name: str,
    *,
    tenant: str = "default",
    cwd: str | None = None,
    profile: str | None = None,
) -> list[str]:
    """Single place where a window environment is constructed for all execution paths."""
    cwd = cwd or f"/workdir/{agent_name}"
    guide_path = f"{cwd}/AGENTS.md"
    env_vars = [
        "env",
        f"AGENT_NAME={agent_name}",
        OFFICE_TOOLS_ENV,
        f"AGENT_GUIDE={guide_path}",
    ]
    if profile:
        env_vars.extend([
            f"CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-{profile}",
            f"CODEX_HOME=/home/ubuntu/.codex-{profile}",
        ])
    return env_vars


def write_agent_guide(
    cwd: str, agent_name: str, tenant: str = "default", lead: str | None = None,
    profile: str | None = None,
) -> None:
    try:
        os.makedirs(cwd, exist_ok=True)
        content = generate_agents_md(agent_name, tenant, lead=lead)

        for filename in ("AGENTS.md", "CLAUDE.md"):
            file_path = os.path.join(cwd, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        ensure_claude_project_trusted(cwd, profile=profile)
        ensure_codex_project_trusted(cwd, profile=profile)
        ensure_agy_project_trusted(cwd)
    except Exception:
        pass


def create_window(
    session_name: str,
    agent_name: str,
    command: list[str] | None = None,
    cwd: str | None = None,
    socket: str | None = None,
    lead: str | None = None,
    profile: str | None = None,
) -> tuple[int, str, str]:
    """⚠ This writes the guide for every caller, so it needs the lead.

    Without the parameter it wrote a guide with no lead sentence *over* the one
    a caller had just written with it. Measured: the initial window (created by
    new-session, which does not come through here) named the lead; every other
    agent's guide had been silently overwritten and named nobody.
    """
    if cwd is None:
        cwd = f"/workdir/{agent_name}"

    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError:
        pass

    write_agent_guide(cwd, agent_name, lead=lead, profile=profile)

    # ⚠ Idempotent by name. tmux happily creates a second window with the same
    # name, and then refuses to resolve it: `tmux -t hq:<name>` answers
    # "can't find window" on an ambiguous target. Every delivery to that agent
    # fails from then on, silently.
    #
    # Measured: hiring an existing name three times left three windows called
    # `rehire` and made the agent unaddressable. Re-writing the guide above is
    # deliberate and harmless — it refreshes the lead sentence — but a second
    # window is not.
    try:
        if agent_name in list_windows(session_name, socket=socket):
            return 0, "", ""
    except Exception:
        pass

    if not command:
        command = window_env(agent_name, cwd=cwd) + ["bash", "-il"]

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
