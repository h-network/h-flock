#!/usr/bin/env python3
"""
drive-setup.py — prompt-aware interactive driver for setup.sh.

Drives setup.sh through a pseudo-terminal (pty), matching each expected
prompt regex in exact sequence before providing the configured answer.
If setup.sh presents an unexpected prompt, reorders prompts, or omits one,
this driver aborts immediately with a loud mismatch error instead of
silently shifting answers downstream.
"""

import argparse
import os
import pty
import re
import select
import subprocess
import sys


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PROMPT_END = re.compile(r"(?:\[[^\r\n]*\]\s*)?[:?]\s*$")


def terminal_prompt_line(output):
    """Return the current unterminated prompt-shaped terminal line, if any.

    Bash ``read -p`` writes a prompt without a newline and then blocks. Build
    output is allowed to take arbitrarily long; newline-terminated output is
    therefore never classified as a prompt. Carriage returns and ANSI display
    controls are discarded before inspecting only the current terminal line.
    """
    visible = _ANSI_ESCAPE.sub("", output)
    line = re.split(r"[\r\n]", visible)[-1]
    if line.strip() and _PROMPT_END.search(line):
        return line
    return None


def parse_args():
    parser = argparse.ArgumentParser(description="Prompt-aware driver for setup.sh")
    parser.add_argument("--setup-cmd", default="./setup.sh", help="Path to setup.sh script")
    parser.add_argument("--pod", default="acme", help="Pod name")
    parser.add_argument("--tenant", default="hq", help="Tenant name")
    parser.add_argument("--agents", type=int, default=2, help="Agent count")
    parser.add_argument("--agent-names", default="architect,sme-2", help="Comma-separated agent names")
    parser.add_argument("--multi-account", default="n", help="Use more than one account? [y/N]")
    parser.add_argument("--oauth-token", default="", help="OAuth token for default account")
    parser.add_argument("--default-cli", default="", help="Default CLI (claude/codex/agy)")
    parser.add_argument("--cli-exceptions", default="", help="Any agents differing")
    parser.add_argument("--local-provider", default="n", help="Point any agent at local provider? [y/N]")
    parser.add_argument("--api", default="y", help="Start REST API door? [y/N]")
    parser.add_argument("--telegram", default="n", help="Run Telegram bot? [y/N]")
    parser.add_argument("--telegram-token", default="", help="Telegram Bot Token")
    parser.add_argument("--telegram-chat-id", default="", help="Telegram Chat ID")
    parser.add_argument("--telegram-voice", default="n", help="Enable spoken voice replies? [y/N]")
    parser.add_argument("--publish-api", default="y", help="Reach REST API from outside container? [y/N]")
    parser.add_argument("--api-port", default="8080", help="Host port for REST API")
    parser.add_argument("--publish-session", default="y", help="Reach session console from outside container? [Y/n]")
    parser.add_argument("--session-port", default="8081", help="Host port for session console")
    parser.add_argument("--remote", default="y", help="Reach published doors from another machine? [Y/n]")
    parser.add_argument("--tls-cert", default="", help="Path to TLS certificate")
    parser.add_argument("--self-signed", default="n", help="Generate self-signed cert? [y/N]")
    return parser.parse_args()


def is_yes(val, default=False):
    if not val:
        return default
    return val.strip().lower() in ("y", "yes")


def is_no(val, default=False):
    if not val:
        return default
    return val.strip().lower() in ("n", "no")


def build_expected_prompts(args):
    agent_names = [a.strip() for a in args.agent_names.split(",") if a.strip()]
    if len(agent_names) < args.agents:
        for i in range(len(agent_names) + 1, args.agents + 1):
            agent_names.append(f"sme-{i}")
    agent_names = agent_names[: args.agents]

    pairs = [
        (r"Pod name", args.pod),
        (r"Tenant name", args.tenant),
        (r"How many agents\?", str(args.agents)),
    ]
    for i, name in enumerate(agent_names, 1):
        pairs.append((rf"Agent #{i} name", name))

    pairs.append((r"Use more than one account in this tenant\?", args.multi_account))
    if is_yes(args.multi_account, default=False):
        pass
    else:
        pairs.append((r"OAuth token for 'default'", args.oauth_token))

    pairs.append((r"Default CLI \(claude/codex/agy\)", args.default_cli))
    pairs.append((r"Any agents differing from that\?", args.cli_exceptions))
    pairs.append((r"Point any agent at a local model provider\?", args.local_provider))
    pairs.append((r"Start the REST API door inside the tenant\?", args.api))
    pairs.append((r"Run the Telegram bot in this tenant\?", args.telegram))

    if is_yes(args.telegram, default=False):
        pairs.append((r"Telegram Bot Token", getattr(args, "telegram_token", "")))
        pairs.append((r"Telegram Chat ID", getattr(args, "telegram_chat_id", "")))
        if getattr(args, "telegram_token", "") and getattr(args, "telegram_chat_id", ""):
            pairs.append((r"Enable spoken voice replies\?", getattr(args, "telegram_voice", "n")))

    api_enabled = is_yes(args.api, default=False) or is_yes(args.telegram, default=False)

    if api_enabled:
        pairs.append((r"Reach the REST API from outside the container", args.publish_api))
        if is_yes(args.publish_api, default=False):
            pairs.append((r"Host port for the REST API", str(args.api_port)))

    pairs.append((r"Reach the session console from outside the container", args.publish_session))
    session_published = not is_no(args.publish_session, default=False)
    if session_published:
        pairs.append((r"Host port for the session console", str(args.session_port)))

    api_published = api_enabled and is_yes(args.publish_api, default=False)
    if api_published or session_published:
        pairs.append((r"Reach published doors from another machine", args.remote))
        if not is_no(args.remote, default=False):
            pairs.append((r"Path to a TLS certificate", args.tls_cert))
            if not args.tls_cert:
                pairs.append((r"Generate a self-signed certificate\?", args.self_signed))

    return pairs


def drive_setup(cmd, pairs, timeout=15.0, cwd=None, env=None):
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        cwd=cwd,
        env=env,
    )
    os.close(slave)

    buf = ""
    pair_idx = 0
    try:
        while pair_idx < len(pairs):
            expected_pattern, answer = pairs[pair_idx]
            matched = False
            while not matched:
                if proc.poll() is not None:
                    sys.stderr.write(
                        f"\ndrive-setup: setup.sh exited with code {proc.returncode} before prompt #{pair_idx+1}: {expected_pattern!r}\n"
                    )
                    sys.stderr.write(f"Buffer before exit:\n{buf}\n")
                    return proc.returncode or 2

                r, _, _ = select.select([master], [], [], timeout)
                if not r:
                    sys.stderr.write(
                        f"\ndrive-setup: timeout ({timeout}s) waiting for prompt #{pair_idx+1}: {expected_pattern!r}\n"
                    )
                    sys.stderr.write(f"Buffer at timeout:\n{buf}\n")
                    proc.kill()
                    return 2

                try:
                    chunk = os.read(master, 1024).decode("utf-8", errors="replace")
                except OSError:
                    break

                if not chunk:
                    break

                sys.stdout.write(chunk)
                sys.stdout.flush()
                buf += chunk

                if re.search(expected_pattern, buf):
                    matched = True
                else:
                    unexpected = terminal_prompt_line(buf)
                    if unexpected is not None:
                        sys.stderr.write(
                            f"\ndrive-setup: unexpected prompt before prompt "
                            f"#{pair_idx+1} {expected_pattern!r}: {unexpected!r}\n"
                        )
                        return 2

            if not matched:
                sys.stderr.write(
                    f"\ndrive-setup: failed matching prompt #{pair_idx+1}: {expected_pattern!r}\n"
                )
                sys.stderr.write(f"Buffer:\n{buf}\n")
                return 2

            # Send answer
            os.write(master, (answer + "\n").encode("utf-8"))
            pair_idx += 1
            buf = ""

        # Drain remaining output while setup builds and starts the tenant. Prompt
        # drift before any expected prompt is bounded above; after the final
        # answer there is no safe timeout because a legitimate image build can
        # take minutes.
        buf = ""
        while proc.poll() is None:
            r, _, _ = select.select([master], [], [], 1.0)
            if r:
                try:
                    chunk = os.read(master, 1024).decode("utf-8", errors="replace")
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                    buf += chunk
                    unexpected = terminal_prompt_line(buf)
                    if unexpected is not None:
                        sys.stderr.write(
                            f"\ndrive-setup: unexpected trailing prompt after "
                            f"the final scripted answer: {unexpected!r}\n"
                        )
                        return 2
                except OSError:
                    break

        proc.wait()
        return proc.returncode
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def main():
    args = parse_args()
    pairs = build_expected_prompts(args)
    cmd = [args.setup_cmd]
    rc = drive_setup(cmd, pairs)
    sys.exit(rc)


if __name__ == "__main__":
    main()
