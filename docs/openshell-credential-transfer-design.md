# Design: just-in-time CLI credential transfer for port_type: openshell

Ticket 655ebeac, thread 2. Goal, stated by telegram: an openshell sandbox
can run anywhere — nothing about it guarantees it's on infrastructure
flock trusts the way the tenant container itself is. So a CLI credential
should never come to rest on the sandbox's own persisted state at all;
h-flock (the tenant container) holds it, and transfers it only for the
duration of one `exec_sandbox` call.

**Status: built. Both claude's shape (env var per call) and codex/agy's
shape (Candidate B — write-then-wipe file transfer, telegram's decision:
credentials must stay in h-flock, not rest in OpenShell's own `Provider`
object even server-side, so Candidate A was ruled out without a real
test) are implemented in `flock/port/openshell.py`'s `_exec_headless`,
unit-tested, and verified against the live gateway with dummy (non-real)
credential values — see §3b.**

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

## 3. codex / agy: decided — Candidate B (write-then-wipe)

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

**Decision (telegram, via architect, 2026-08-29): Candidate B.**
Credentials must stay in h-flock, not rest in OpenShell's own `Provider`
object even server-side — the §3a tension below was disqualifying on its
own, so no real-credential test of Candidate A was run.

### 3a. Candidate A — OpenShell's own native provider mechanism (not chosen)

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

### 3b. Candidate B — transient write-then-wipe file transfer (built)

Implemented in `flock/port/openshell.py`'s `_exec_headless`. Per delivery
needing codex/agy auth:

1. `_write_credential_file`: `exec_sandbox(["/bin/sh", "-c", 'mkdir -p "$1" && base64 -d > "$2"', "sh", dir, path], stdin=base64(credential_json))` — write the credential file. Path as a shell positional parameter, not interpolated, same reasoning as the Attachment delivery write.
2. `exec_sandbox(headless_command(cli, resume=True), stdin=prompt)` — the actual delivery.
3. `_wipe_credential_file`, in a real `finally`: `exec_sandbox(["/bin/sh", "-c", 'shred -u "$1" 2>/dev/null || rm -f "$1" 2>/dev/null || true', "sh", path])` — best-effort, never raises, so a wipe failure never masks or replaces whatever the actual delivery's own outcome was. Runs even when step 2 fails.

The credential's real JSON shape, inspected safely (key names only, via a
script that never printed a value, against real files already present in
this office's environment — never guessed):

```
codex ~/.codex/auth.json:
  {auth_mode, OPENAI_API_KEY, tokens: {id_token, access_token, refresh_token, account_id}, last_refresh}

agy ~/.gemini/antigravity-cli/antigravity-oauth-token:
  {token: {access_token, token_type, refresh_token, expiry}, auth_method}
```

(agy's file is JSON too, despite its filename suggesting a bare token —
correcting an earlier assumption in this doc.)

flock reads the whole JSON blob from one env var per CLI+profile —
`CODEX_AUTH_JSON_<PROFILE>` / `AGY_AUTH_JSON_<PROFILE>` — mirroring
`CLAUDE_OAUTH_TOKEN_<PROFILE>`'s existing naming shape
(`flock.tmux.ops.window_env`), just holding a full JSON string instead of
one bare token, since that's the real shape these two files take.
Profile support itself is not wired up anywhere yet for openshell agents
(no `profile` lookup in `control/openers.py`'s `start_agent` branch) —
`_exec_headless` accepts a `profile` parameter for when that lands, and
defaults to `"DEFAULT"` until then.

**Verified against the live gateway with a dummy (non-functional)
credential value** — no real secret needed for this, since it only tests
the write/exec/wipe mechanics, not whether a credential actually
authenticates anything: the file was written with exactly the given
content (read back via `cat`), and confirmed absent afterward in three
separate scenarios — a clean wipe call on its own, the full write→exec→wipe
sequence when the exec succeeds, and critically also when the write
succeeds but the exec itself fails, proving the `finally`-based wipe runs
regardless of the delivery's own outcome.

Two RPCs of real overhead per codex/agy delivery (write, wipe) beyond the
one Message/Command/Attachment already needed — cheap relative to the
actual CLI invocation.

**Still open:**
- Whether the exact JSON above (plus whatever `auth_mode`/`last_refresh`
  values flock would need to supply) is sufficient for codex to actually
  authenticate, and the equivalent for agy — needs a real, working
  credential to settle, per telegram's second scoped, one-time
  authorization (same handling discipline as the claude test: never
  printed/logged, shredded after, not reused). Telegram is placing the
  real files and will specify where; not yet done as of this writing.
- `agy`'s own native provider profile, if one exists, is now moot given
  the Candidate B decision applies uniformly to both CLIs regardless.

## 4. What this design explicitly does not cover

- Provider-attachment persistence semantics from §3a — moot now that
  Candidate A wasn't chosen, left as-written for the record.
- Rotation — if a token expires mid-lifetime of a long-lived sandbox,
  nothing here addresses refreshing it. Out of scope for this pass.
- Profile support for openshell agents in general (`_exec_headless`
  accepts the parameter; nothing populates it yet).
