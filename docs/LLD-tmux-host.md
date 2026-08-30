# LLD — the tmux host

> **Status: built and running.**
>
> The module that brings up and maintains the tmux the agents live in. Moving
> envelopes into and out of those windows is
> [`LLD-port-tmux.md`](LLD-port-tmux.md); this one never touches an
> envelope.

## 1. Purpose

One tmux server, one session per tenant, one window per `port_type: tmux` agent. This module
creates them, keeps them matching the roster, and configures them so that
everything else can assume they are there.

It reads roster membership and per-agent launch configuration from Redis, but
knows nothing about envelope transport: it does not read queues or deliver. Its
entire output is "there is a window named `backend` and something is running in
it".

## 2. Headless is the normal state

The server starts detached and **requires no human client**. The session service
later attaches one headless control-mode client for terminal streaming; no
operator attachment is required. That is not a degraded mode — it is how the
office runs, and everything downstream is built for it.

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
and no per-window scoping. Keep the directory owner-only to exclude other host
users, but it is not a boundary between agents: they share the container user
and the HLD explicitly makes the container the boundary. Treat socket access as
control of the tenant.

⚠ **A window index is not stable — tmux renumbers on kill.** Measured: with
windows `[1:architect, 2:sme-2, 3:sme-3]`, retiring `sme-2` left
`[1:architect, 2:sme-3]` — the survivor moved. Address a window by **name**,
never by index, and never infer a position from a name that happens to end in a
digit.

This is the deeper reason an all-digit agent name is rejected
(`LLD-bus-and-switch` §3.1): such a name resolves as an index, and the index it
resolves to moves.

## 5. Windows

One window per agent, **named after the agent**, so a window is addressable by
the same name the bus uses. Low-level tmux operations use `flock.tmux` as a shared
library (`create_window`, `kill_window`, `list_windows`, `write_agent_guide`, etc.)
shared across `tmuxhost`, `control`, and `port`.

Windows are **reconciled against roster members with `port_type == "tmux"`**, in both directions —
a `port_type == "tmux"` agent in the roster with no window gets one, a window with no `port_type == "tmux"` agent in the roster is
removed. Non-tmux roster entries (enrolled REST clients with `port_type: "api"`, `port_type: "control"`, or sandboxed agents with `port_type: "openshell"`) generate no windows and are ignored by `tmuxhost`. Reconciliation is a repeatable operation, not a one-time setup step, so
running it again after a roster change is the whole mechanism for hiring and
letting go.

⚠ **Create before you kill.** The two directions are not interchangeable in
order. Killing first can empty the session — most obviously on the very first
pass, where the session's own initial window is by definition not an agent — and
an emptied session is destroyed and does not come back (§2). Creating first
means the session always holds at least one window and the destructive half is
never the last thing standing.

⚠ **The last stale agent window is replaced, not retained.** Cleanup still
refuses to empty the session, but when every existing window is stale it first
creates `__init__`, then retires the stale windows. The placeholder preserves
the session without leaving a departed agent present-but-unaddressable.

Nothing announces a roster change, so this module polls for it like the others.
Having no queue to block on, it polls on a loop of its own, every
`ROSTER_POLL_SECONDS` — the same value the switch takes from the environment, so
both roster-polling processes refresh on the same interval. The per-delivery
port reads the current port_type directly and does not poll. See
`LLD-bus-and-switch` §3.2
for why that value is shared, and for the one case where being a poll behind
still hurts: windows should lead routes, so this module reconciling promptly is
what keeps a new agent's first envelope from being dead-lettered.

⚠ **`create_window` is idempotent by name.** Before spawning a window, it checks `list_windows` and returns if a window with that exact name already exists. If duplicate windows with the same name were created, tmux target specifications (e.g. `hq:sme-2`) would become ambiguous and every delivery to that agent would fail with `can't find window`. Idempotence means *by name*, ensuring convergence on a single window per agent.

What runs in the window is configuration, not this module's opinion. It starts
what it is told to start, in the working directory `/workdir/<agent>` it is told to use,
with `AGENT_GUIDE=/workdir/<agent>/AGENTS.md` and `OFFICE_TOOLS=office` in the environment.
`write_agent_guide` generates both `AGENTS.md` and `CLAUDE.md` (rendering lead guidance based on `<prefix>:lead`, including instructing the lead to check `office status` and hold work if an agent is `blocked`, along with general office working guidelines)
and pre-approves project trust across all three CLIs in a **profile-aware** manner (`.claude-<profile>.json`, `.codex-<profile>/config.toml`, `.gemini/.../settings.json`). Blind to profiles, a profiled agent sits at a workspace trust prompt while presence reads `idle`.
- Claude trust (`ensure_claude_project_trusted`) writes both `hasTrustDialogAccepted: true` and `hasCompletedProjectOnboarding: true` to `.claude.json` (or `.claude-<profile>/.claude.json`).
- Agy trust (`ensure_agy_project_trusted`) explicitly sets `enableTelemetry: False` in `settings.json` in addition to appending `cwd` to `trustedWorkspaces`.
- ⚠ **Guide and trust errors are visible but non-fatal:** `write_agent_guide`
  and all three `ensure_*_project_trusted` routines catch failures so window
  creation can continue, and emit a `tmux` `error` record naming the directory.
  They used to swallow these failures, which is how the profile-blind trust bug
  remained hidden.
When a CLI is configured, window creation routes through `startAgent <cli>` so permission and auto-approval flags apply.

⚠ **OAuth Refresh Token Rotation (RTR) & Profile Credential Sharing (Build 32):**
⚠ **Do not duplicate `.credentials.json` across per-agent config directories.**
Agents on one account share one config directory
(`CLAUDE_CONFIG_DIR=~/.claude-<profile>`); distinct profiles keep their own, each
with its own login.

⚠ **The mechanism is a hypothesis, not a measurement, and the doc should not
pretend otherwise.** Refresh-token rotation — each refresh invalidating the
previous token, so copies race for a single-use value — is the leading
explanation and was never confirmed: no before/after token value was recorded and
no rejection was observed. What *was* measured: the source credential file was
rewritten at 15:25:48Z and a live agent running on a copy stopped working about
four minutes later.

⚠ **An access token lives about 8 hours, not 1.** The one-hour figure came from
assuming the lifetime and subtracting it from `expiresAt`; measured against the
file's mtime the gap is 7:59:59. Therefore, agents assigned to the same account profile share the single profile config directory (`CLAUDE_CONFIG_DIR=~/.claude-<profile>`). Distinct profiles maintain separate directories with their own independent OAuth logins.

⚠ **Launch, Profile, and Cause State Ordering:** `start_agent` (`flock.control.openers`) writes the `launch` (`pod:<pod>:tenant:<tenant>:agent:<name>:launch`) and `profile` keys before roster visibility, then atomically publishes the fresh-hire `window.cause` with roster membership. `tmuxhost` reconciles as soon as the roster row appears: publishing launch or profile later builds against defaults, while publishing cause and roster sequentially can expose either a stale cause or a cause-less creation. `window.cause` is one-shot: successful creation consumes it into the event, while an already-present window discards it without attribution so a later recovery cannot borrow a stale cause.

⚠ **Quiet Terminal Telemetry:** `office` runs inside an agent's window, where
`stdout` is the agent's screen. Printing bus telemetry log records
(`{"module":"port", ...}`) to `stdout` hands the agent internal module names,
stream IDs, and correlation IDs, leading agents to inspect local processes and
discover Redis. `office` sets `FLOCK_LOG_QUIET=1` to suppress envelope logging
to `stdout`, while records still reach the window log (`FLOCK_LOG_FILE`). The
switch tails that file, emits each record once to container stdout, and mirrors
the same line to the durable mounted custody log (`FLOCK_CUSTODY_FILE`).

## 6. Lifecycle

tmux itself restarts nothing. With `remain-on-exit` off, when a pane's process
exits tmux removes its window; a server failure takes every pane with it.

The continuously polling tmuxhost makes the effective agent restart policy
different from tmux's own behavior: on its next reconciliation pass, every
`port_type: tmux` roster member whose window is missing is recreated. There is
currently no retry limit, backoff, or terminal failed state. A configured CLI
is launched again through `startAgent`, and the ordinary session-history check
may select that CLI's resume command. This was verified live when a second
Ctrl-C made a CLI exit, tmux removed its window, and reconciliation recreated
it.

Supervision therefore has two layers: tmuxhost continuously supervises desired
window existence, while the container entrypoint restarts tmuxhost itself
without restarting peer services. Both layers depend on idempotence: bringing
the host up when it is already up must be a no-op, and reconciliation must
converge rather than duplicate.

Two consequences for anything downstream:

- A missing window for `port_type == "tmux"` is a real state, not an error to repair from elsewhere. The
  port dead-letters into it rather than trying to create one.
- Nothing may assume a window it saw earlier is still there.

## 7. Deferred

**Desired restart policy for a dead agent.** The implemented behavior is
unlimited recreation on reconciliation (§6). Whether that should instead have
a retry limit, backoff, or terminal failed state remains a design decision.
Documenting the current behavior does not decide that policy.

**Cross-tenant routing.** Multiple tenants on one host are already supported:
`flock_tenant_context` gives each tenant its own Compose project and container,
and therefore its own tmuxhost process, server and session. What remains
deferred is tenants reaching one another, not how their tmux sessions are
owned.

## 8. What this is not

Not the port — it never reads a queue, never opens an envelope, never types
into a window.

Not a child-process supervisor. It does not keep a CLI process alive in place,
but its desired-state reconciliation does recreate a missing agent window and
therefore relaunches the configured CLI (§6).

Not a terminal multiplexer for humans. Attaching is supported because tmux
supports it, not because anything here is designed around a viewer.

## Windows, models and failures — added after a night of live running

⚠ **A window may point at a model provider.** `window_env` states the
CLI-neutral intent with `AGENT_PROVIDER_URL`, `AGENT_PROVIDER_TOKEN`,
`AGENT_PROVIDER_MODEL` and, when configured, `AGENT_PROVIDER_SMALL_MODEL`. It
does not construct any vendor-specific variables itself. The base image's
`startAgent` launcher translates that intent for the selected CLI, including
Claude's URL and model-tier rules.

⚠ **Known accepted limitation: an explicitly configured provider name can
silently fall through to the vendor when its URL is missing.** If an agent has
no provider configured, `get_agent_provider` returning `None` is intentional:
the CLI uses its normal vendor/OAuth path. But the same return value is used
when a provider name exists and its matching `PROVIDER_<NAME>_URL` does not
(`src/flock/tmuxhost/host.py:53-65`). The lookup logs an error, then window
creation continues with `provider=None`, making that misconfiguration
indistinguishable downstream from the intentional no-provider case. The CLI can
therefore consume real vendor usage instead of refusing loudly. This behavior
is accepted for now; operators must treat the tmuxhost error as the only signal
that the requested provider was not applied.

⚠ **Unsupported provider/CLI combinations refuse rather than fall through.**
The base launcher currently rejects provider configuration for codex and agy
with exit 3. h-flock used to build `ANTHROPIC_*` directly, so a codex window
silently ignored the intended provider and ran against the vendor. Keeping the
translation and refusal in `startAgent` prevents that cost-and-privacy defect
from returning when CLI-specific rules differ.

⚠ **The model id must match the served id byte for byte.** `gpt-oss:20b` is not
`gpt-oss-20b`, and a mismatch is reported by the CLI as a model that does not
exist. `setup.sh` offers what `/v1/models` returns rather than asking anyone to
type one.

⚠ **Tool calls are the server's problem, not ours.** A model that answers text
but emits literal `<tool_call>{…}</tool_call>` is a server missing
`--enable-auto-tool-choice` and a `--tool-call-parser` matching its template
(`hermes` for Qwen). An agent whose tools do not work is useless for real work,
and nothing in h-flock can fix it. Measured working on a vLLM serving
`qwen3-vl-32b`: `Write` then `Read`, and `office send` to a colleague who
replied.

⚠ **A local model leaves suggestion text in the pane.** After a turn the CLI may
show a proposed next prompt in its input box. It is a rendering, not input — a
bare Enter does nothing and a paste replaces it — but it looks alarming in a
screenshot and in a terminal panel.

⚠ **The base launcher unsets inherited `ANTHROPIC_*` before translating a
Claude provider.** A previous subscription's variables otherwise win over the
translated settings, which is the quietest way for a local provider to look
broken. This sanitising belongs to `startAgent`; `window_env` deliberately knows
only the neutral `AGENT_PROVIDER_*` contract.

⚠ **There is one creation owner.** `StartAgent` publishes profile, provider and
launch desired state; `tmuxhost` resolves it and builds the window. The former
second creator drifted independently three times: it omitted the lead, seeded
trust into the wrong profile, and once ignored the provider. Re-hiring with
changed configuration removes the stale window so this canonical path rebuilds
it; unchanged hires leave it alone.

⚠ **A retired agent's window is never the one holding the session open.** tmux
exits when a session has no windows, so reconciliation keeps at least one — but
the guard could not tell *hold the session open* from *keep this dead agent*, and
a retired agent's window survived forever when it was the last. It now raises the
`__init__` placeholder the empty-roster path already uses, then retires the agent
properly.

⚠ **Trust and guide failures are recorded, not swallowed.** They still never
raise into a delivery path, but each emits a `tmux` `error` naming the directory.
Silence here is how the profile-blind trust bug hid.

⚠ **Re-hiring auto-resumes prior session history.** When `tmuxhost` creates a
window for an agent, it checks whether prior session history exists for that
agent's working directory (`has_session_history`):
- `claude`: `.claude[-<profile>]/projects/-workdir-<name>/*.jsonl`
- `codex`: `.codex[-<profile>]/sessions/**/rollout-*.jsonl` matching `payload.cwd`
- `agy`: `.gemini/antigravity-cli/history.jsonl` matching `workspace`

If prior history exists and `resume` is not explicitly set to `0` (`--fresh`),
`tmuxhost` launches with the CLI's native resume command (`startAgent claude --resume`,
`startAgent codex resume --last`, or `startAgent agy --continue`). If multiple
sessions exist, it continues the most recent recorded session. When explicit
`resume: true` (`--resume`) or `resume: false` (`--fresh`) is set via `StartAgent`,
that explicit instruction overrides auto-detection.

⚠ **A window may opt out of `startAgent`'s own defaults, per agent.** The base
image's `startAgent` (not h-flock's) reads two env vars nothing threaded
per-window before: `AGENT_SKIP_PERMISSIONS` (default `1` — skip CLI approval
prompts; all three CLIs read it, each mapping to its own bypass flag) and
`AGENT_CLAUDE_TOOLS` (claude only; unset means the limited
Bash/Read/Write/Edit/Glob/Grep default, an *empty string* means unrestricted).
`office hire --skip-permissions`/`--no-skip-permissions` and `--claude-tools
<list>` set `StartAgent` payload fields of the same name (`office hire`,
`CONTRACTS.md` §5), which `start_agent` (`src/flock/control/openers.py:384`,
`:401`) persists to per-agent Redis keys — `skip-permissions` and
`claude-tools` — the same `config_changed`/replace-window pattern `resume`
already uses. `TmuxHost.get_agent_skip_permissions`/`get_agent_claude_tools`
(`src/flock/tmuxhost/host.py:98`, `:106`) read them back into
`window_env` (`src/flock/tmux/ops.py:305`), which appends
`AGENT_SKIP_PERMISSIONS=1`/`0` and `AGENT_CLAUDE_TOOLS=<value>` to the
window's env list only when a value was actually set (`:354`, `:360`) — same
"absent is not empty" rule as the OAuth token above it: omitted means
`startAgent` decides, never this layer re-deciding it. `AGENT_CLAUDE_TOOLS=`
(empty) is therefore a real, distinct value from the variable being absent —
it is how a hire asks for claude's unrestricted tool set.
