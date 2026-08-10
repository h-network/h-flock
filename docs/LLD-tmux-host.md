# LLD — the tmux host

> **Status: built and running.**
>
> The module that brings up and maintains the tmux the agents live in. Moving
> envelopes into and out of those windows is
> [`LLD-adapter-tmux.md`](LLD-adapter-tmux.md); this one never touches an
> envelope.

## 1. Purpose

One tmux server, one session per tenant, one window per agent. This module
creates them, keeps them matching the roster, and configures them so that
everything else can assume they are there.

It knows nothing about the bus. It does not read queues, does not deliver, does
not know what an envelope is. Its entire output is "there is a window named
`backend` and something is running in it".

## 2. Headless is the normal state

The server runs detached and **nobody attaches**. That is not a degraded mode —
it is how the office runs, and everything downstream is built for it.

```
  tmux new-session -d          create without attaching
  set -g exit-empty off        server survives its last window closing
```

`exit-empty off` matters more than it looks: without it, removing the last agent
takes the server down.

⚠ **It does not save the session, and the session is what everything depends
on.** A session whose last window closes is destroyed by tmux, and no option
prevents that — `exit-empty off` keeps the *server* running with no sessions in
it, which is not the same thing and is not enough. Every later
`new-window -t <session>` then fails with "no current target", permanently.

This is not theoretical: it is how the first deployment failed. See §5 — it is
the reason reconciliation has an order.

Attaching is an **escape hatch for a human**, not the interface. Nothing may
depend on a client being connected.

## 3. Geometry

The one that bites, because it only appears when no one is looking.

With no client attached, panes get `default-size`. Every TUI in the office
renders to that, and anything reading a pane sees exactly those columns. Then a
human attaches with a wide terminal, tmux resizes, and every window reflows
underneath whatever was reading it.

**120×32, fixed.** tmux's own default of 80×24 is cramped for the TUIs that
actually run here, and a size nothing ever changes is what lets an app render a
window without negotiating geometry. Wide enough not to wrap awkwardly, small
enough that a full redraw is not much to push down a stream.

```
  new-session -d -x 120 -y 32           an explicit size, not the default
  set -g default-size 120x32            the size a headless window gets
```

`window-size` defaults to `latest`, which hands control to whoever attached most
recently. That is the wrong owner once the windows exist to be read by software
rather than looked at.

⚠ **`set -g window-size manual` is the obvious fix and it does not work.** On
tmux 3.5a it kills the server outright the moment a second window is created
with no client attached — the first window succeeds, the next one takes the
whole server down, and every later call reports "server exited unexpectedly".
Verified in the container image; without it three windows create cleanly.

So pin `default-size` and leave `window-size` alone. That secures the half that
matters — a known, stable geometry for every window created headless, which is
the normal state (§2). It does not stop a human who attaches from resizing, and
that is accepted: attaching is a rare escape hatch, nothing may depend on a
client being connected, and a reflow while someone is looking is visible rather
than silent.

Also set here, because it is a property of the host rather than of any agent:

```
  set -g history-limit <n>              scrollback per pane
```

Keep it small. Scrollback is per-pane memory across every window in the tenant,
and nothing in this design reads it.

## 4. The socket

Give the server its own socket rather than sharing the default:

```
  TMUX_TMPDIR=<dir>            relocates the default socket's directory
```

`-L <name>` also works but has to be passed on **every** `tmux` invocation
everywhere; `TMUX_TMPDIR` is inherited by children, so the isolation happens
once and nothing else has to remember.

⚠ **Socket access is total.** Anything that can reach it can `send-keys` into any
pane, which is arbitrary code execution as that user. There is no authentication
and no per-window scoping. The directory permissions are the boundary — keep it
owner-only, and treat handing out the socket as handing out the machine.

⚠ **A window index is not stable — tmux renumbers on kill.** Measured: with
windows `[1:architect, 2:sme-2, 3:sme-3]`, retiring `sme-2` left
`[1:architect, 2:sme-3]` — the survivor moved. Address a window by **name**,
never by index, and never infer a position from a name that happens to end in a
digit.

This is the deeper reason an all-digit agent name is rejected
(`LLD-bus-and-router` §3.1): such a name resolves as an index, and the index it
resolves to moves.

## 5. Windows

One window per agent, **named after the agent**, so a window is addressable by
the same name the bus uses. Low-level tmux operations use `flock.tmux` as a shared
library (`create_window`, `kill_window`, `list_windows`, `write_agent_guide`, etc.)
shared across `tmuxhost`, `control`, and `adapter`.

Windows are **reconciled against roster members with `vab == "tmux"`**, in both directions —
a `vab == "tmux"` agent in the roster with no window gets one, a window with no `vab == "tmux"` agent in the roster is
removed. Non-tmux roster entries (enrolled REST clients with `vab: "api"`, or `vab: "control"`) generate no windows and are ignored by `tmuxhost`. Reconciliation is a repeatable operation, not a one-time setup step, so
running it again after a roster change is the whole mechanism for hiring and
letting go.

⚠ **Create before you kill.** The two directions are not interchangeable in
order. Killing first can empty the session — most obviously on the very first
pass, where the session's own initial window is by definition not an agent — and
an emptied session is destroyed and does not come back (§2). Creating first
means the session always holds at least one window and the destructive half is
never the last thing standing.

⚠ **Last window retention (`len(existing_windows) > 1`):** The cleanup loop in `reconcile_once` explicitly checks `if len(existing_windows) > 1:` before killing any non-roster window. This deliberate guard keeps the session alive so tmux does not destroy it. As a consequence, if a retired agent's window is the only remaining window in the session, it persists until a new agent window is created or the session is reset.

Nothing announces a roster change, so this module polls for it like the others.
Having no queue to block on, it polls on a loop of its own, every
`ROSTER_POLL_SECONDS` — the same value the router and the adapter take from the
environment, so all three see the same membership. See `LLD-bus-and-router` §3.2
for why that value is shared, and for the one case where being a poll behind
still hurts: windows should lead routes, so this module reconciling promptly is
what keeps a new agent's first envelope from being dead-lettered.

⚠ **`create_window` is idempotent by name.** Before spawning a window, it checks `list_windows` and returns if a window with that exact name already exists. If duplicate windows with the same name were created, tmux target specifications (e.g. `hq:sme-2`) would become ambiguous and every delivery to that agent would fail with `can't find window`. Idempotence means *by name*, ensuring convergence on a single window per agent.

What runs in the window is configuration, not this module's opinion. It starts
what it is told to start, in the working directory `/workdir/<agent>` it is told to use,
with `AGENT_GUIDE=/workdir/<agent>/AGENTS.md` and `OFFICE_TOOLS=office` in the environment.
`write_agent_guide` generates both `AGENTS.md` and `CLAUDE.md` (rendering lead guidance based on `<prefix>:lead`, including instructing the lead to check `office status` and hold work if an agent is `blocked`)
and pre-approves project trust across all three CLIs in a **profile-aware** manner (`.claude-<profile>.json`, `.codex-<profile>/config.toml`, `.gemini/.../settings.json`). Blind to profiles, a profiled agent sits at a workspace trust prompt while presence reads `idle`.
- Claude trust (`ensure_claude_project_trusted`) writes both `hasTrustDialogAccepted: true` and `hasCompletedProjectOnboarding: true` to `.claude.json` (or `.claude-<profile>/.claude.json`).
- Agy trust (`ensure_agy_project_trusted`) explicitly sets `enableTelemetry: False` in `settings.json` in addition to appending `cwd` to `trustedWorkspaces`.
- ⚠ **Silent error handling:** `write_agent_guide` and all three `ensure_*_project_trusted` routines wrap operations in bare `try...except: pass`. Failures (such as filesystem permissions or JSON parse errors) are silent and unlogged, which is how the profile-blind trust bug remained hidden.
When a CLI is configured, window creation routes through `startAgent <cli>` so permission and auto-approval flags apply.

⚠ **OAuth Refresh Token Rotation (RTR) & Profile Credential Sharing (Build 32):**
Anthropic OAuth enforces Refresh Token Rotation (RTR): every token refresh yields a new access token and a new single-use refresh token, while invalidating the old refresh token (`BUILD-32-FINDINGS.md`). Duplicating `.credentials.json` into multiple per-agent config directories is structurally broken, as the first agent to refresh invalidates all other copies within 1 hour. Therefore, agents assigned to the same account profile share the single profile config directory (`CLAUDE_CONFIG_DIR=~/.claude-<profile>`). Distinct profiles maintain separate directories with their own independent OAuth logins.

## 6. Lifecycle

tmux restarts nothing. A window whose process exits stays dead; a server that
dies takes every pane with it.

So supervision lives **above** this module — a service manager or the
container's restart policy. What this module owes that supervisor is
idempotence: bringing the host up when it is already up must be a no-op, and
reconciliation must converge rather than duplicate.

Two consequences for anything downstream:

- A missing window for `vab == "tmux"` is a real state, not an error to repair from elsewhere. The
  adapter dead-letters into it rather than trying to create one.
- Nothing may assume a window it saw earlier is still there.

## 7. Deferred

**Restart policy for a dead agent.** Whether a window whose process exited should
be relaunched, and how many times before giving up, is a decision that needs
something watching. Not part of bringing the host up.

**Multiple tenants on one host.** One session per tenant is the shape, but
whether one process manages several sessions or one runs per tenant is not
settled and does not need to be yet.

## 8. What this is not

Not the adapter — it never reads a queue, never opens an envelope, never types
into a window.

Not a supervisor. It creates windows and reconciles them; keeping processes
alive is someone else's job.

Not a terminal multiplexer for humans. Attaching is supported because tmux
supports it, not because anything here is designed around a viewer.
