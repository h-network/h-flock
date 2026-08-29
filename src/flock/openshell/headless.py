"""Per-CLI headless (non-interactive) invocation, for one-shot exec delivery.

Mirrors `flock.tmux.ops.start_agent_command`, which builds the *interactive*
launch argv for a tmux pane, but for a CLI invoked once per delivered
message inside an OpenShell sandbox via `ExecSandbox` instead of a
persistent pane. `ExecSandbox` spawns a fresh process and returns on exit —
there is no "paste into a running process" equivalent — so continuity
across deliveries comes entirely from each CLI's own resume/continue flag
plus its on-disk session state persisting in the long-lived sandbox.

The message text itself is never interpolated into argv: it is always
carried on stdin, both to avoid shell-quoting/length limits and so
delivered text can never be read as a flag.

Flag names/spellings below were read directly from each installed CLI's own
`--help` (claude, codex) — not guessed, not taken from external docs. That
is a weaker claim than "verified": nothing here has actually been executed
end-to-end yet (no sandbox to run it in), so behavior implied by the help
text — e.g. that omitting `[prompt]` truly reads it from stdin, or that
`-c`/`--continue` composes cleanly with `-p`/`--print` — is still an
inference from the flag descriptions, not an observed result. Confirm with
a real run before relying on it. `agy` is weaker still: its `--print`/
`--prompt` split was ambiguous even in `--help` (unclear which one takes
the prompt as a value vs. which is the mode switch), so treat that branch
as a placeholder, not even inferred-and-likely.
"""

from __future__ import annotations

# Names whose headless argv below is a placeholder guess, not even the
# help-text-derived inference the other CLIs get. A caller wiring this into
# real delivery should surface this distinction (e.g. log a warning) rather
# than treat every branch of `headless_command` as equally trustworthy.
UNVERIFIED_HEADLESS_CLIS = frozenset({"agy"})


def headless_command(cli: str, *, resume: bool) -> list[str]:
    """Build the argv for one non-interactive invocation of `cli`.

    The prompt/message is not included here — pass it via `stdin` to
    `OpenShellClient.exec_sandbox`, not appended to this list.
    """
    if cli == "claude":
        # -p/--print: non-interactive, response then exit. -c/--continue:
        # continue the most recent conversation in the current directory
        # (deterministic; unlike --resume with no id, which opens a picker
        # that cannot be answered non-interactively).
        return ["claude", "-p", "-c"] if resume else ["claude", "-p"]

    if cli == "codex":
        # `codex exec` is the documented non-interactive entry point;
        # `codex exec resume --last` resumes the most recent recorded
        # session for this cwd without needing its session id.
        return ["codex", "exec", "resume", "--last", "-"] if resume else ["codex", "exec", "-"]

    if cli == "agy":
        # UNVERIFIED — see module docstring. Best reading of `agy --help`:
        # --print/-p triggers non-interactive mode, --continue/-c resumes.
        return ["agy", "-p", "-c"] if resume else ["agy", "-p"]

    raise ValueError(f"no headless invocation known for cli {cli!r}")
