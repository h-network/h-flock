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

`claude` and `codex` argv below have been executed end-to-end against a
real OpenShell sandbox on the office's test gateway (2026-08-29): both
parse and run without argument errors, `claude -p`/`-p -c` fail cleanly on
"Not logged in" (expected — no credential was injected for this check, see
docs/LLD-port-openshell.md's credential-transfer rule), and `codex exec
--skip-git-repo-check resume --last -` was confirmed to actually resume the
session created by a prior `codex exec --skip-git-repo-check -` call in
the same sandbox — real evidence that session continuity across separate
one-shot `exec()` invocations works the way this whole design assumes.

`--skip-git-repo-check` was not in the original inference from `--help`
alone and was only found necessary by actually running the command: codex
refuses to run in a directory it doesn't trust, and a fresh sandbox's
default workdir is not one. This is exactly why the module docstring used
to warn that help-text inference is weaker than an observed result — here
is a case where that gap was real.

`agy` remains an unverified placeholder — its `--print`/`--prompt` split
was ambiguous even in its own `--help`, and it isn't installed in the
default sandbox image at all (checked directly: `which agy` exits 1), so
there's nothing to run it against yet regardless.
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
        #
        # --skip-git-repo-check: codex refuses to run at all otherwise,
        # because a sandbox's default workdir is not a trusted git
        # checkout. Found by actually running this against a real
        # sandbox, not from --help (see module docstring).
        return (
            ["codex", "exec", "--skip-git-repo-check", "resume", "--last", "-"]
            if resume
            else ["codex", "exec", "--skip-git-repo-check", "-"]
        )

    if cli == "agy":
        # UNVERIFIED — see module docstring. Best reading of `agy --help`:
        # --print/-p triggers non-interactive mode, --continue/-c resumes.
        return ["agy", "-p", "-c"] if resume else ["agy", "-p"]

    raise ValueError(f"no headless invocation known for cli {cli!r}")
