import json
import os
from pathlib import Path

from flock.bus.logging import log_record
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


class TmuxCommandError(RuntimeError):
    """A tmux command failed, distinct from a valid empty result."""

    def __init__(self, command: str, code: int, stderr: str):
        self.command = command
        self.code = code
        self.stderr = stderr
        super().__init__(f"{command} failed ({code}): {stderr or 'no error output'}")


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
    ret, stdout, stderr = run_tmux("list-windows", "-t", session_name, "-F", "#{window_name}", socket=socket)
    if ret != 0:
        raise TmuxCommandError("list-windows", ret, stderr)
    return {w for w in stdout.splitlines() if w}


def generate_agents_md(agent_name: str, tenant: str = "default", lead: str | None = None) -> str:
    if lead and agent_name == lead:
        lead_sentence = (
            "You are the lead of this office. The other agents follow your direction, "
            "and yours is the account that decides when something is done.\n\n"
            "Before you hand out work, check `office status`. An agent that is `blocked` "
            "will not receive it — hold the work and say so. Do not try to fix the agent.\n\n"
            "`office cloneToAll` only ever reuses a copy it made during that same call "
            "as a local source for the next agent — never a target that already existed "
            "before the call started. Mixing a pre-existing agent into the same `-a` list "
            "as fresh hires is safe: the existing one is skipped, not reused as a source.\n\n"
        )
    elif lead:
        lead_sentence = f"{lead} is the lead of this office. Their direction is the office's direction.\n\n"
    else:
        lead_sentence = ""

    return f"""You are **{agent_name}**, an agent in this office.

{lead_sentence}Everything about your situation is in your environment:

    $AGENT_NAME      who you are
    $TENANT          the office you are in
    $OFFICE_TOOLS    the commands available to you

Run any of those with --help. To see your tmux colleagues:

    office peers

That's colleagues only — an app client (a Telegram bot, say) or the tenant's
lifecycle provider won't be on it; `office peers -i` lists those too, labeled
apart from colleagues. Either way it's still a valid `office send` destination.
A message arrives in your terminal as `[message from <name>] …` — reply by name,
whether or not `peers` lists it:

    office send -a <name> "one quoted argument"
    office send -a <name> --stdin      < the body on stdin
    office send -a <name> --file PATH  the body from a file

⚠ The body is ONE argument. Unquoted words after the first are rejected, not
sent — and anything long or multi-line belongs on --stdin or --file, which are
never shell-parsed. `send` prints the destination and the bytes it accepted;
if that byte count is not what you meant to send, it did not arrive intact.
This directory is yours; work in it.

You have a task board. Nothing will notify you about it — check it yourself:

    office list        titles waiting for you
    office take        take the next one, and it prints in full
    office done        when it is finished

Take a ticket *before* you start work, not after. `doing` is how the office
knows what you are on.

## Working in this office

This directory is your own clone — work only here. Do not read or write
another agent's files or state directly; `office send` is how you reach
another agent, not a shortcut around it.

Always reply through `office send`, not just in your own terminal output.
Text you write as your own response is only visible to whoever is directly
watching that pane — it never reaches the sender unless you also send it.

A short reply that reads like the last line of a conversation — a
confirmation, an acknowledgment, "nice," "got it" — is the highest-risk
moment for skipping this, not a low-risk one. It feels complete as text alone
precisely because it reads like a natural close. Before treating a turn as
finished: did an office send call actually execute in this turn, not "did I
mean to."

That said, "always reply via office send" means a substantive message must
actually reach its recipient — it does not mean every message needs a reply
forever. Once an exchange is down to pure closing acknowledgments ("thanks",
"got it", "noted") with nothing new in either message, let it end. Replying
to an acknowledgment with another acknowledgment is a loop, not courtesy —
watchdog will flag it if it keeps going.

Push your own branch, never `main` or `develop` directly — name it
`<your-agent-name>/short-description`. The lead opens the pull request into
`develop` and merges it once CI passes; you don't need `gh`/PR access
yourself, only enough git credential to push your own branch (SSH or
whatever's already set up). `develop` moves to `main` on its own release
cadence, separately from any individual merge.

Your git identity is your own agent name — that is how the office knows
which agent did which work. No co-author line, no "generated with" trailer,
no other identity in a commit: only the one you are authenticated as.

When a ticket is done, message the lead a summary before or alongside
`office done`. A closed ticket with no report is invisible to the lead.

Long-running work: don't go silent. Background it, or answer a check-in
with real status — not silence until you're finished.

Never dump a credential's actual value to check whether it is set — check
presence only. This office's shells carry real, live credentials; `env |
grep` prints secrets, not just names.

Anything destructive, ambiguous, or outside a ticket's stated scope: ask
the lead first, don't guess.

Read a ticket's claimed cause skeptically — check it against the real
system, logs, or code before building the fix it describes. The ticket can
be wrong.

A behaviour change ships with its docs, in the same branch — not as a
follow-up.

One ticket, one branch, one focused change. Don't fold unrelated work into
a branch just because you're already in it.
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
    except Exception as exc:
        # ⚠ Never raise into a delivery path — but never vanish either.
        # Silence here is how the profile-blind trust bug hid: seeding
        # failed, every profiled agent sat at a picker unreachable, and
        # presence read `idle` because idle is what a prompt looks like.
        log_record("tmux", "error",
                   reason=f"claude trust seeding failed for {cwd}: {exc}")


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
    except Exception as exc:
        # ⚠ Never raise into a delivery path — but never vanish either.
        # Silence here is how the profile-blind trust bug hid: seeding
        # failed, every profiled agent sat at a picker unreachable, and
        # presence read `idle` because idle is what a prompt looks like.
        log_record("tmux", "error",
                   reason=f"codex trust seeding failed for {cwd}: {exc}")


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
    except Exception as exc:
        # ⚠ Never raise into a delivery path — but never vanish either.
        # Silence here is how the profile-blind trust bug hid: seeding
        # failed, every profiled agent sat at a picker unreachable, and
        # presence read `idle` because idle is what a prompt looks like.
        log_record("tmux", "error",
                   reason=f"agy trust seeding failed for {cwd}: {exc}")


def window_env(
    agent_name: str,
    *,
    tenant: str = "default",
    cwd: str | None = None,
    profile: str | None = None,
    provider: dict | None = None,
    skip_permissions: bool | None = None,
    claude_tools: str | None = None,
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

    # ⚠ PER WINDOW, KEYED TO THE PROFILE — never one token for the tenant.
    # A token in the container environment is inherited by EVERY window, which
    # is a single-account mechanism bolted onto a multi-account design: with two
    # accounts it either overrides both profiles with one identity or is ignored
    # where a profile already has credentials. Injecting it here means the
    # profile decides both which config dir and which credential, so the two
    # compose instead of competing.
    #
    # ⚠ Absent is not empty. No token means the variable is not set at all, and
    # the agent logs in interactively as it always has — an empty string would
    # look to the CLI like a credential that fails.
    token = os.environ.get(
        f"CLAUDE_OAUTH_TOKEN_{(profile or 'default').upper().replace('-', '_')}"
    )
    if token:
        env_vars.append(f"CLAUDE_CODE_OAUTH_TOKEN={token}")

    # ⚠ Both are `startAgent`'s own knobs (base image, not h-flock's), threaded
    # through per window rather than left tenant-wide. Absent is not the same
    # as off/empty for either: `startAgent` reads `AGENT_SKIP_PERMISSIONS`
    # with a default of `1` and `AGENT_CLAUDE_TOOLS` with bash's `${VAR-default}`
    # (unset only), so leaving the variable out entirely is what preserves its
    # own default rather than this layer silently re-deciding it.
    if skip_permissions is not None:
        env_vars.append(f"AGENT_SKIP_PERMISSIONS={'1' if skip_permissions else '0'}")
    # ⚠ `""` is a real, distinct value here — "no restriction" — not "unset".
    # `startAgent` only falls back to its limited default when the variable is
    # completely absent, so a hire that asked for the full tool set must set
    # the variable to empty, never omit it.
    if claude_tools is not None:
        env_vars.append(f"AGENT_CLAUDE_TOOLS={claude_tools}")
    # A local model instead of the vendor's. claude reads these itself; nothing
    # in h-flock talks to the model, so an agent on a local provider is an agent
    # like any other — same window, same paste, same activity file.
    #
    # ⚠ It uses NO account credential. The watchdog's credential check does not
    # apply to it, and a missing login is not a fault for this agent
    # (LLD-watchdog). Do not seed it a profile expecting one.
    if provider:
        # ⚠ STATE THE INTENT; THE BASE IMAGE TRANSLATES IT. `startAgent` turns
        # these into the CLI's own variables, and it knows things h-flock should
        # not have to: that claude wants the URL WITHOUT `/v1` because it appends
        # `/v1/messages` itself, that all three model tiers must carry the same
        # id or the others fall back to vendor names the local server does not
        # serve, and that inherited `ANTHROPIC_*` must be stripped first.
        #
        # ⚠ **AND IT REFUSES WHAT IT CANNOT DO.** `startAgent codex` and
        # `startAgent agy` with these set exit 3 instead of starting. h-flock
        # built `ANTHROPIC_*` by hand until 2026-08-23, which meant a codex agent
        # carrying a provider ran against the VENDOR while `setup.sh` printed
        # `(local)` beside its name — cost and privacy both differing from what
        # the operator was told, silently. Delegating buys that refusal.
        url = (provider.get("url") or "").rstrip("/")
        if url:
            env_vars.append(f"AGENT_PROVIDER_URL={url}")
        if provider.get("token"):
            env_vars.append(f"AGENT_PROVIDER_TOKEN={provider['token']}")
        model = provider.get("model")
        if model:
            env_vars.append(f"AGENT_PROVIDER_MODEL={model}")
            if provider.get("small_model"):
                env_vars.append(f"AGENT_PROVIDER_SMALL_MODEL={provider['small_model']}")
    return env_vars


def has_session_history(
    agent: str,
    cli: str,
    profile: str | None = None,
    home_root: str | Path | None = None,
) -> bool:
    """Return True if prior session history exists for the given agent/CLI/profile."""
    home = Path(home_root) if home_root is not None else Path(os.environ.get("HOME", "/home/ubuntu"))
    suffix = f"-{profile}" if profile else ""
    cwd = f"/workdir/{agent}"

    if cli == "claude":
        project_dir = home / f".claude{suffix}" / "projects" / cwd.replace("/", "-")
        if not project_dir.is_dir():
            return False
        for p in project_dir.glob("*.jsonl"):
            try:
                if p.is_file() and p.stat().st_size > 0:
                    return True
            except OSError:
                continue
        return False

    elif cli == "codex":
        sessions_dir = home / f".codex{suffix}" / "sessions"
        if not sessions_dir.is_dir():
            return False
        for p in sessions_dir.glob("**/rollout-*.jsonl"):
            if not p.is_file():
                continue
            try:
                with p.open("rb") as f:
                    raw = f.readline()
                record = json.loads(raw)
                payload = record.get("payload") if isinstance(record, dict) else None
                if (
                    record.get("type") == "session_meta"
                    and isinstance(payload, dict)
                    and payload.get("cwd") == cwd
                ):
                    return True
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        return False

    elif cli == "agy":
        history_file = home / ".gemini" / "antigravity-cli" / "history.jsonl"
        if not history_file.is_file():
            return False
        try:
            with history_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict) and record.get("workspace") == cwd:
                            return True
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return False
        return False

    return False


def start_agent_command(
    cli: str,
    resume: bool = False,
) -> list[str]:
    """Construct the startAgent argv list for the given CLI and resume mode."""
    if not resume:
        return ["startAgent", cli]

    if cli == "claude":
        return ["startAgent", "claude", "--resume"]
    elif cli == "codex":
        return ["startAgent", "codex", "resume", "--last"]
    elif cli == "agy":
        return ["startAgent", "agy", "--continue"]
    else:
        return ["startAgent", cli, "--resume"]


def _seed_profile_dirs(profile: str | None) -> None:
    """Populate a profiled CLI's config dir from the image's defaults.

    ⚠ **Unprofiled agents need nothing** — they read `~/.claude` directly, which
    the image already ships populated.

    `seedProfile` comes from the base image, which owns first-run state and CLI
    defaults; h-flock only decides *which* profile an agent gets. It copies from
    the live config dir at runtime, so there is one source of truth rather than a
    copy here that drifts from the image.

    Never raises: a missing `seedProfile` means an older base, and an agent that
    starts against an unseeded dir is a visible failure, not a silent one.
    """
    if not profile:
        return
    for cli in ("claude", "codex"):
        try:
            result = subprocess.run(
                ["seedProfile", cli, profile],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log_record(
                    "tmux", "error",
                    reason=f"seedProfile {cli} {profile} exited {result.returncode}: "
                           f"{(result.stderr or '').strip()[:200]}",
                )
        except FileNotFoundError:
            log_record("tmux", "error",
                       reason="seedProfile is not on PATH — the base image predates it, "
                              f"so profile {profile!r} is unseeded and its agents may "
                              "stop on a first-run dialog")
            return
        except Exception as exc:
            log_record("tmux", "error",
                       reason=f"seedProfile {cli} {profile} failed: {exc}")


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

        # ⚠ SEED THE PROFILE DIR BEFORE TRUST, AND THE ORDER IS LOAD-BEARING.
        # A CLI pointed at CLAUDE_CONFIG_DIR=~/.claude-<profile> does NOT fall
        # back to ~/.claude for its settings or its first-run state — measured
        # in the base image, where `CLAUDE_CONFIG_DIR=~/.claude-test claude`
        # stops on the theme picker. So a profiled agent needs that directory
        # populated or it waits forever for a keypress and looks exactly like an
        # agent with nothing to say.
        #
        # ⚠ `seedProfile` never overwrites an existing file. The trust helpers
        # below CREATE `<dir>/.claude.json`, so running them first leaves a file
        # carrying trust and no `hasCompletedOnboarding` — which seedProfile then
        # declines to touch, and the picker returns. Seed first, always.
        _seed_profile_dirs(profile)

        ensure_claude_project_trusted(cwd, profile=profile)
        ensure_codex_project_trusted(cwd, profile=profile)
        ensure_agy_project_trusted(cwd)
    except Exception as exc:
        # ⚠ Never raise into a delivery path — but never vanish either.
        # Silence here is how the profile-blind trust bug hid: seeding
        # failed, every profiled agent sat at a picker unreachable, and
        # presence read `idle` because idle is what a prompt looks like.
        log_record("tmux", "error",
                   reason=f"guide write failed for {cwd}: {exc}")


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
    if agent_name in list_windows(session_name, socket=socket):
        return 0, "", ""

    if not command:
        command = window_env(agent_name, cwd=cwd) + ["bash", "-il"]

    args = ["new-window", "-t", f"{session_name}:", "-n", agent_name, "-c", cwd]
    args.extend(command)
    return run_tmux(*args, socket=socket)


def kill_window(session_name: str, window_name: str, socket: str | None = None) -> tuple[int, str, str]:
    return run_tmux("kill-window", "-t", f"{session_name}:{window_name}", socket=socket)


def submit_text(
    session_name: str,
    agent_name: str,
    text: str,
    stream_id: str = "",
    socket: str | None = None,
) -> None:
    target = f"{session_name}:{agent_name}"
    buf_name = f"flock_{stream_id[:8]}" if stream_id else f"flock_{os.urandom(4).hex()}"

    def checked(command: str, result: tuple[int, str, str]) -> None:
        code, _, stderr = result
        if code != 0:
            raise TmuxCommandError(command, code, stderr)

    try:
        checked(
            "load-buffer",
            run_tmux("load-buffer", "-b", buf_name, "-", socket=socket, input_data=text),
        )
        checked(
            "paste-buffer",
            run_tmux("paste-buffer", "-b", buf_name, "-p", "-d", "-t", target, socket=socket),
        )
        time.sleep(ENTER_DELAY)
        checked("send-keys", run_tmux("send-keys", "-t", target, "Enter", socket=socket))
    except Exception:
        run_tmux("delete-buffer", "-b", buf_name, socket=socket)
        raise
