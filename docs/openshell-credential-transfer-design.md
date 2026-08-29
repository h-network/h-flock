# Design: just-in-time CLI credential transfer for port_type: openshell

Ticket 655ebeac, thread 2. Goal, stated by telegram: an openshell sandbox
can run anywhere — nothing about it guarantees it's on infrastructure
flock trusts the way the tenant container itself is. So a CLI credential
should never come to rest on the sandbox's own persisted state at all;
h-flock (the tenant container) holds it, and transfers it only for the
duration of one `exec_sandbox` call.

**Status: claude's shape is settled and proven for real. Codex/agy's
shape has two real candidate designs and is intentionally left open,
pending telegram's call on which to build — see §3.**

## 1. The real constraint that shapes everything here

`SandboxSpec.environment` (set at `CreateSandbox` time) persists for the
sandbox's entire lifetime — anything placed there sits in the sandbox's
ambient process environment for as long as the sandbox exists, which is
exactly the kind of resting credential this design exists to avoid.
`ExecSandboxRequest.environment` (the `env=` parameter of
`exec_sandbox()`), by contrast, is genuinely per-call — **confirmed
directly against the live gateway**: a variable set on one `exec()` call
is correctly absent from a second, separate `exec()` call against the
same sandbox. So the shape of "transient" here is concrete and testable,
not aspirational: **use `exec_sandbox(..., env={...})`, never
`create_sandbox(..., environment={...})`, for anything credential-shaped.**

## 2. claude: settled — env var per exec call, nothing on disk

**Proven for real** (2026-08-29, telegram's explicit one-time
authorization for this specific test): passed a real
`CLAUDE_CODE_OAUTH_TOKEN` via `exec_sandbox`'s per-call `env=` dict
against the live gateway. `claude -p` genuinely authenticated and
returned a real model reply. No credential file, no `SandboxSpec`-level
env var, nothing written to the sandbox's filesystem at any point.

This works because claude's own CLI accepts `CLAUDE_CODE_OAUTH_TOKEN` as
a first-class, per-process auth source — the exact same mechanism
`flock.tmux.ops.window_env` already relies on for tmux-hosted claude
agents (`CLAUDE_CODE_OAUTH_TOKEN_<PROFILE>` read from the tenant
container's own environment, keyed by profile). The openshell delivery
path (`flock/port/openshell.py`'s `_exec_headless`) would do the
analogous thing:

```python
token = os.environ.get(f"CLAUDE_OAUTH_TOKEN_{(profile or 'default').upper().replace('-', '_')}")
result = client.exec_sandbox(
    sandbox_id, headless_command("claude", resume=True),
    stdin=prompt.encode("utf-8"),
    env={"CLAUDE_CODE_OAUTH_TOKEN": token} if token else None,
)
```

Same env var name, same profile-keyed lookup convention as tmux — no new
naming scheme needed for claude specifically. **Not yet wired into
`deliver_openshell`** — this doc describes the shape; the code hasn't
been changed to look up and pass a token yet, since doing so needs the
same token this test already burned its one-time authorization on, and
that authorization does not cover reuse (see
[[feedback-no-unasked-credential-transfer]]). Wiring the plumbing itself
doesn't need a live token — only *testing* it again would.

## 3. codex / agy: not settled — two real candidates

**Confirmed directly (not assumed): codex and agy are both file-based,
not env-var-based, unlike claude.** `container/seed-home.sh`'s own
`CRED_PATHS` already documents exactly where:

| CLI | credential file |
|---|---|
| codex | `.codex/auth.json` |
| agy | `.gemini/antigravity-cli/antigravity-oauth-token` |

Also confirmed directly via `codex login --help`: there is no per-
invocation env-var auth path for codex at all — `--with-api-key`/
`--with-access-token` read a value from stdin during an explicit `codex
login` step whose entire purpose is writing `~/.codex/auth.json`. There
is no `CODEX_CODE_OAUTH_TOKEN`-shaped equivalent to skip that file.

### 3a. Candidate A — OpenShell's own native provider mechanism

OpenShell ships a built-in `codex`-typed provider profile (`openshell
provider list-profiles`), wanting `access_token`/`refresh_token`/
`account_id`/(optional)`id_token`. Attaching a provider this way means
flock never writes anything to the sandbox's filesystem or process env at
all — OpenShell's own gateway/supervisor would be responsible for making
codex authenticated, by whatever internal mechanism it uses (still not
directly observable from outside — `GetSandboxProviderEnvironment`, the
one RPC that could show this, requires "a sandbox principal" and refuses
external callers).

**Tested with a dummy (non-functional) credential, specifically so no
real secret needed moving for this check:** unlike claude, `codex exec`
did **not** refuse client-side — no local auth file or `CODEX_*` env var
appeared, but it proceeded through full session startup and then hung/
timed out apparently attempting a real network call, rather than gating
locally the way claude does. This is consistent with codex having no
client-side login gate to get past (the reason claude's provider-profile
test failed) — but a dummy credential cannot distinguish "the proxy
injected a wrong token and got rejected" from "nothing was injected and
it's retrying against nothing." **Genuinely inconclusive without a real,
working codex credential**, which needs its own ask-first per the
standing rule — the claude test's authorization does not cover this, and
no such test has been run yet.

**A real tension worth naming even if Candidate A turns out to work
technically**: attaching a provider means the actual credential material
lives in OpenShell's own `Provider` object, stored by the gateway — not
resting on the sandbox's own filesystem, but not literally "transferred
per call and forgotten" either. Whether that satisfies telegram's "the
h-flock container should hold them, not leave them there" framing is a
real question this design doc can't answer on flock's behalf; flagging it
explicitly rather than assuming Candidate A trivially satisfies the goal
just because it avoids touching the sandbox's filesystem.

### 3b. Candidate B — transient write-then-wipe file transfer

Guaranteed to work (no dependency on an unconfirmed OpenShell-internal
mechanism), at the cost of more code and more RPCs on flock's side. Per
delivery needing codex/agy auth:

1. `exec_sandbox(["sh", "-c", "mkdir -p ~/.codex && base64 -d > ~/.codex/auth.json"], stdin=base64(credential_json))` — write the credential file.
2. `exec_sandbox(headless_command("codex", resume=True), stdin=prompt)` — the actual delivery.
3. `exec_sandbox(["sh", "-c", "shred -u ~/.codex/auth.json 2>/dev/null || rm -f ~/.codex/auth.json"])` — wipe it, **in a `finally`-equivalent** so step 2 failing (including a timeout) still triggers cleanup. `shred` first, falling back to plain `rm`, mirrors `container/seed-home.sh`'s own handling for the equivalent tmux case.

Three `exec_sandbox` RPCs per delivery instead of one — real overhead,
though each is cheap relative to the actual CLI invocation. The
credential genuinely never lives anywhere but flock's own environment and
the sandbox's ephemeral filesystem for the few seconds between steps 1
and 3 — the literal shape telegram described ("transient write-then-wipe
per exec call, not zero-touch"), and the one architect flagged as the
likely fallback if claude turns out to be the exception rather than the
rule.

**Open, not yet answered:**
- Which of 3a/3b to build for codex/agy — pending telegram, intentionally
  left open per architect's instruction not to block this doc on it.
- The exact shape of the credential file content flock would need to
  construct for `.codex/auth.json` (its real JSON schema — access token,
  refresh token, account id, expiry, in what field names) and for agy's
  bare-token file, if Candidate B is chosen. Not yet inspected.
- `agy`'s own native provider profile, if one exists — `openshell
  provider list-profiles` did not show an `agy`-specific entry among the
  AGENT-category profiles seen so far (`claude-code`, `codex`, `copilot`,
  `cursor`); if there's genuinely none, Candidate A isn't available for
  `agy` regardless of what's decided for codex, and Candidate B would be
  the only option there.

## 4. What this design explicitly does not cover

- Provider-attachment persistence semantics beyond what's described in
  §3a — e.g., whether a `Provider` object can be scoped so tightly
  (single-use, single-sandbox) that it approximates "per-call" even
  though it's stored server-side. Not investigated.
- Rotation — if a token expires mid-lifetime of a long-lived sandbox,
  nothing here addresses refreshing it. Out of scope for this pass.
- Any actual code changes. This document is deliberately design-only, per
  the ticket's own framing ("doesn't need to be code yet") — wiring
  either candidate into `deliver_openshell`/`control/openers.py` is
  follow-on work once the codex/agy branch is decided.
