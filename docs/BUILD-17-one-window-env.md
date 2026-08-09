# Build 17 — one window environment, built in one place

> **Base on `main`.** Branch `tmux/build-17-one-window-env`, push to origin.

## 1. Measured, on a live tenant

Two code paths create windows and they have drifted. From `/proc/<pane>/environ`
on 2026-08-09:

| | booted from the roster (`alice`) | hired over the bus (`iris`) |
|---|---|---|
| `AGENT_NAME` | ✓ | ✓ |
| `AGENT_GUIDE` | ✓ | **missing** |
| `OFFICE_TOOLS` | ✓ | **missing** |
| profile vars | ✓ (build 16) | **missing** |

`flock.tmuxhost` builds the full environment. `flock.control.runner` builds its
own — `["env", f"AGENT_NAME={target}", "startAgent", cli]` — and that is all a
hired agent gets.

## 2. Why it went unnoticed, and why it still matters

`office` is on `PATH` from the venv, so a hired agent can still send messages —
which is why every live test passed. The guide is written to disk by
`create_window` for every caller, so `AGENTS.md` exists too.

⚠ **What breaks is the guide's own first paragraph.** It tells an agent
*"everything about your situation is in your environment"* and then names
`$OFFICE_TOOLS` and `$AGENT_GUIDE`. A hired agent reads that, echoes them, gets
nothing, and has to guess. We built a discovery path and then shipped half the
agents without it.

⚠ **Build 16 inherits the same hole.** A hired agent will not get its profile
either, so accounts work for booted agents and silently do not for hired ones —
which is a worse failure than the one build 16 just fixed, because it is
conditional.

## 3. The change

**One function builds the window environment; both paths call it.** Put it where
the other shared window logic lives:

```python
def window_env(agent_name: str, *, tenant: str, cwd: str,
               profile: str | None = None) -> list[str]
    # ["env", "AGENT_NAME=…", "OFFICE_TOOLS=…", "AGENT_GUIDE=…", …]
```

Then `flock.tmuxhost` and `flock.control.runner` both use it and cannot disagree.

⚠ **Do not fix this by copying the missing variables into the control path.**
That leaves two lists to keep in step and the next variable drifts the same way.
The defect is the duplication, not the missing entries.

⚠ **The control path must read the `profile` key too**, the same way `tmuxhost`
does. `StartAgent` does not carry a profile in its payload and should not start
now — the key is set by the entrypoint, and the window creator reads it.

## 4. Done when

- a hired agent's `/proc/<pane>/environ` matches a booted agent's, variable for
  variable
- an agent hired *with* a profile key gets both config-dir variables
- one function is the only place a window environment is constructed —
  `grep -c "AGENT_NAME=" src/` finds it once
- 127 tests still green

⚠ **Verify on a running tenant, not only in tests.** Both existing paths pass
their unit tests today and still produced different environments.

## 5. Reporting

`jira done`, then message `architect` with the function's location and signature,
and the `environ` comparison from a live tenant.
