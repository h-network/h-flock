# LLD — the openshell port

> **Status: built and real-gateway-verified end to end, not just
> unit-tested.** All four envelope kinds (`Message`, `Command`,
> `AddTicket`, `Attachment`) and the full `StartAgent`/`StopAgent`
> lifecycle, including per-profile credential lookup, have each been run
> against the live gateway for real (§2a–§5). `src/flock/openshell/`
> (`client.py`, `headless.py`, `naming.py`); `src/flock/port/openshell.py`
> (registered lazily via `flock.port.registry`, added by the `tmux` lane
> in anticipation — no `deliver.py` edit needed); `control/openers.py`'s
> `start_agent`/`stop_agent` openshell branches, including `profile`
> validation/publishing (ticket `f6b9f6fe`). Depends on
> [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address scheme
> and [`LLD-port-tmux.md`](LLD-port-tmux.md) for the receiving-edge shape
> this port_type parallels. See also
> [`openshell-credential-transfer-design.md`](openshell-credential-transfer-design.md)
> (per-CLI credential shape) and
> [`openshell-sdk-surface-inventory.md`](openshell-sdk-surface-inventory.md)
> (full SDK/gRPC surface vs. what's used).
>
> **What's genuinely still open, not stale claims left over from
> drafting** — see §6 for the current list. The sections below keep the
> chronological build history (useful for *why* a decision was made);
> §6 is the one section to trust for *current* state without reading the
> rest.

This document exists to keep design decisions in one place as this
port_type was built. Ticket: `ff0f4516` (closed), continued under
`655ebeac` (closed) and `f6b9f6fe` (closed) — see git history for the
office board tickets if the numbers need re-deriving later.

## 1. What this is

`port_type: openshell` hosts a roster agent inside an NVIDIA OpenShell
sandbox — a policy-governed, isolated container — instead of a tmux window.
Same switch/bus, same `flock.port` binary, same one-shot-per-delivery
model; delivery lives in `src/flock/port/openshell.py`, registered with
`flock.port.registry` (not a `deliver.py` edit), and lifecycle lives in a
dedicated pair of branches inside `src/flock/control/openers.py`'s
existing `start_agent`/`stop_agent`.

**Hard constraint, unconditionally honored by this design:** zero changes
to `src/flock/switch/service.py` or anything under `src/flock/bus/`. The
switch is already port_type-agnostic (see `LLD-bus-and-switch.md`) — it
only forwards to ingress and kicks `flock.port <agent>`. Everything
type-specific belongs inside `flock.port`'s own delivery routines, exactly
as tmux/api/control already do.

## 2. The one real interaction-model difference from tmux

Tmux's port pastes text into the terminal of a CLI (claude/codex/agy) that
is already running and holding its own conversation state in-process. The
OpenShell SDK has no equivalent. Verified directly against the real
`openshell` package (0.0.116, pip-installed and read, not assumed):

`SandboxClient.exec(sandbox_id, command, *, env, stdin, timeout_seconds) ->
ExecResult(exit_code, stdout, stderr)` spawns a **fresh, one-shot process**
inside the sandbox and returns once it exits. It does not attach to an
already-running process, and there is nothing else in the ~30-RPC surface
that does.

So "deliver a message" for this port_type cannot mean "paste into a live
pane." It means: invoke the target CLI **non-interactively, once per
delivery**, with the message on stdin, and send its stdout back to the
source via `bus.doors.send` — the reply step the tmux paste model doesn't
need, because tmux never has a return value to send anywhere. Continuity
across deliveries comes from each CLI's own resume/continue flag plus its
on-disk session history, which persists inside the sandbox because **the
sandbox is long-lived — only the port process is one-shot**, same
relationship `flock.port` already has with a tmux pane it doesn't hold
open either.

`src/flock/openshell/headless.py` builds this argv per CLI, mirroring
`flock.tmux.ops.start_agent_command`'s per-CLI branching but for
non-interactive invocation. Confirmed against each installed CLI's own
`--help` (claude, codex); flag *behavior* (does an omitted prompt really
read stdin, does resume compose with print mode) is still inferred from
that help text, not executed end-to-end — mark this line item verified
only after a real sandbox run confirms it. `agy`'s flags are a placeholder,
not even inferred-and-likely (its `--print`/`--prompt` split was ambiguous
in its own `--help`); do not ship that branch as trustworthy without
checking real `agy` behavior first.

## 2a. Live verification (2026-08-29) and two real corrections it produced

Run against the office's real OpenShell test VM (an isolated EVE-NG lab
instance, gateway reachable at `172.16.10.101:17670` with mTLS; a separate,
still-open question is whether this integration needs its own mTLS
identity distinct from the lab's local CLI registration — not resolved
here, flagged to architect). No CLI credential (`ANTHROPIC_API_KEY` etc.)
was injected for this — that requires asking `telegram` first, per this
ticket's standing rule, and wasn't needed to validate the pieces below.

Confirmed for real:
- `SandboxClient.health()` → real `SERVICE_STATUS_HEALTHY`, mTLS handshake
  succeeds.
- Full `create()` → `wait_ready()` → `exec()` → `delete()` →
  `wait_deleted()` cycle completes against the live gateway, not a mock.
- The default sandbox image is Ubuntu 24.04 and already has `claude`
  (`/usr/local/bin/claude`) and `codex` (`/usr/bin/codex`) installed. It
  does **not** have `agy` — `which agy` exits 1. This resolves half of the
  "what image, whose job is provisioning it" open question from §4: for
  claude/codex, nothing extra is needed; for `agy`, either the image needs
  it added or that CLI isn't usable under this port_type yet.
- `claude -p` and `claude -p -c` (§2's headless argv) run and parse
  correctly — fail cleanly with `"Not logged in · Please run /login"`,
  which is the expected, correct result of a real un-credentialed sandbox,
  not a bug.
- Session continuity across separate `exec()` calls in the same sandbox —
  the whole basis of §2's design — is real for codex: a fresh
  `codex exec ... -` in one call, followed by `codex exec ... resume --last -`
  in a second, separate `exec()` call against the same sandbox, actually
  resumed the first call's session.

**Update 2026-08-29, second pass — `OpenShellClient` itself run for real
(not the raw SDK, and not a mock)**, at telegram's request: injected a real
`openshell.SandboxClient.from_active_cluster()` into `OpenShellClient` via
its `sandbox_client=` test seam and ran `create_sandbox` → `get_sandbox` →
`exec_sandbox` → `delete_sandbox` against the live gateway, plus the
not-found error path. Found a real bug the first pass didn't exercise:
`create_sandbox` returned immediately after `CreateSandboxRequest`, while
the gateway still reports the sandbox as `PROVISIONING` — an immediate
`exec_sandbox` against that ref fails with
`FAILED_PRECONDITION: sandbox is not ready` (observed directly). Fixed:
`create_sandbox` now calls `wait_ready()` internally and returns the READY
ref, the same thing the SDK's own `Sandbox` context manager already does.
Confirmed fixed by rerunning the same real sequence successfully
end-to-end. Unit tests updated (`FakeSandboxClient.wait_ready`) to match.

Three real corrections this produced, now reflected in the code:
- **`codex exec` needed `--skip-git-repo-check`.** Not discoverable from
  `--help` alone — a fresh sandbox's workdir isn't a trusted git checkout,
  and codex refuses to run at all without it. `headless_command` now
  includes this flag; see its module docstring for the exact failure this
  fixed.
- **`SandboxSpec`/`CreateSandboxRequest.name` has a real 19-character
  maximum** (`INVALID_ARGUMENT: name exceeds maximum length (20 > 19)`,
  observed directly). Flock agent names allow up to 63 characters
  (`SEGMENT_REGEX` in `src/flock/bus/keys.py`), so **`name=agent` is not a
  safe assumption** for `create_sandbox` the way earlier text in this
  document implied. Resolved in a later pass — see §3's third update:
  `naming.short_name()`.
- **`create_sandbox` did not wait for READY before returning** (this
  second pass's finding, described above) — fixed in
  `src/flock/openshell/client.py`.

## 3. Client wrapper (`src/flock/openshell/client.py`)

`OpenShellClient` wraps `openshell.SandboxClient` (the real SDK class, not
raw proto stub calls — the SDK already ships a high-level wrapper). No
method has a fake-success fallback: every call either reaches the SDK or
raises `OpenShellUnavailable`. This is the specific defect that sank the
previous attempt (its default, no-transport path fabricated `"running"`
and `(0, "", "")` regardless of gateway reachability) — this module is
built and tested specifically not to repeat it. Its tests inject a fake
implementing the same method signatures as `SandboxClient`; they verify
`OpenShellClient`'s own logic (workspace scoping, error wrapping), not
gateway connectivity, and say so in their module docstring.

Known gaps in the current wrapper, deferred until the gateway is
reachable:
- No sandbox `workspace`/`name` addressing scheme is wired to Redis state
  yet (see §4).
- No caching of `SandboxRef.id` (needed for `exec`, distinct from `.name`,
  which is what `get`/`delete` use) — right now every `exec_sandbox` call
  would need its own `get_sandbox` first to learn the id, unless something
  persists it. Likely a new per-agent Redis resource, analogous to
  `launch`/`profile` — not added yet, since it changes `AGENT_STATE_RESOURCES`
  and that deserves review once the actual delivery path is being built,
  not speculatively now.
- Sandbox image/template selection is untouched — `SandboxTemplate.image`
  exists in the proto but nothing here sets it. The default image
  (confirmed live, §2a) already has claude/codex; `agy` and
  opencode/copilot are unconfirmed and likely need image changes someone
  else owns.
- **`create_sandbox`'s `name` parameter needs a real fix, not just a
  caveat** — see §2a's 19-character finding. This wrapper currently passes
  `name` straight through with no length handling at all.

**Update 2026-08-29, third pass — workspaces must be created explicitly.**
Verified directly against the live gateway: `SandboxClient.create()`
against a workspace name that was never explicitly created fails with
`NOT_FOUND: workspace '<name>' not found` — there is no implicit/lazy
workspace creation. Also confirmed the same 19-character cap applies to
workspace names, not just sandbox names
(`INVALID_ARGUMENT: workspace name exceeds maximum length (24 > 19)`).
Both real constraints are now handled:
- `src/flock/openshell/naming.py`: `short_name()` deterministically
  shortens any value to 19 characters (`value[:N]-<6-hex-digest>`), used
  by both `sandbox_name(agent)` and `workspace_name(pod, tenant)`. Pure
  function of its input, so nothing needs to persist it — every caller
  recomputes the same short name from the same agent/pod/tenant.
- `OpenShellClient.ensure_workspace()`: get-or-create, called automatically
  from `create_sandbox()` so callers never need to know about the two-step
  requirement.

**Update 2026-08-29, fourth pass — a real, previously-hidden gap: the real
construction path had no way to authenticate at all.** `OpenShellClient`'s
non-injected path built a bare `SandboxClient(endpoint, timeout=timeout)`
with no `tls=`/`bearer_token=` — which would fail outright against this
gateway's mTLS requirement (confirmed real: a plaintext attempt gets a TLS
"certificate required" alert, §2a). Every prior real-gateway check up to
this point used the `sandbox_client=`/injection seam specifically to work
around this, which is legitimate for testing `OpenShellClient`'s own logic
but never actually exercised its real construction path end to end. Fixed:
added `OPENSHELL_GATEWAY_TLS_CA`/`_CERT`/`_KEY` and
`OPENSHELL_GATEWAY_BEARER_TOKEN` env vars, wired into the real
`SandboxClient(...)` call. **Confirmed fixed for real**: ran a fully real
`OpenShellClient("acme-hq")` (zero injected fakes) against the live
gateway using the lab's own mTLS cert files
(`~/.config/openshell/gateways/openshell/mtls/*`) — `create_sandbox` →
`exec_sandbox` → `delete_sandbox` all succeeded genuinely (real sandbox
id, real `echo` output, real deletion). This is the first time the
wrapper's actual production construction path — not just its logic against
an injected fake — has been run against the live gateway.

Still open: which mTLS identity the real integration should use — the
lab's local CLI registration (used only for this check) or a separate one
provisioned for flock itself. Unresolved either way; the mechanism works
with whatever cert paths it's given.

## 3a. Delivery (`src/flock/port/openshell.py`) and lifecycle
(`control/openers.py`)

Built, unit-tested, and confirmed against the live gateway as a whole —
a real `StartAgent` → real `Message`/`Command`/`Attachment` delivery →
real `StopAgent` cycle, not just the client layer underneath it.

- **`Message`**: wraps the text as `[message from <source>] <text>`
  (mirrors tmux's own framing) and runs it as one headless invocation
  (`headless_command(cli, resume=True)`, stdin-only — see §2/§2a on why
  `resume=True` unconditionally). The result's stdout (or stdout+stderr on
  a non-zero exit) is sent back to the source via `bus.doors.send` — the
  step the prior attempt's branch never did.
- **`Command`**: same one-shot exec, but the raw text goes to stdin
  *unwrapped* — no `[message from ...]` prefix. This mirrors
  `docs/LLD-port-tmux.md`'s own characterization of `Command` exactly
  ("the same paste sequence... one difference... no prefix"): removing the
  prefix is what turns an inert message into something the CLI executes,
  and it is a deliberate capability here too, not a new risk this port_type
  introduces.
- **`AddTicket`**: reuses `flock.port.openers.add_ticket_opener` completely
  unchanged — it never touches the sandbox client at all, matching tmux's
  own "no window check" behavior for this kind.
- **`Attachment`**: implemented via base64-exec-and-mv (see §5) — built
  and confirmed genuinely real end to end.
- **Sandbox id resolution**: no Redis state added (would have required
  touching `AGENT_STATE_RESOURCES` in `src/flock/bus/resources.py`, which
  the hard constraint forbids). Instead, every delivery calls
  `get_sandbox(sbx_name)` to learn the current `.id` before `exec_sandbox`
  — one extra RPC per delivery, in exchange for touching zero files under
  `src/flock/bus/`.
- **`start_agent`**: its own explicit branch, not a fallthrough into the
  generic tmux code (that code also manages `provider`/`window.cause`/
  `replace_window`, none of which apply here). Publishes `launch`/roster
  state, plus `profile` (added later, ticket `f6b9f6fe`: validated the
  same way the tmux branch validates it — `available_profiles` check,
  segment-string requirement — and published to the same shared
  `profile` Redis resource, no new resource needed), then synchronously
  calls `create_sandbox`. Unlike tmux, which defers window creation to
  `tmuxhost`'s async reconciler, this is synchronous because sandbox
  creation is one gRPC call with no equivalent staged startup — no new
  reconciler process needed or built.
- **`stop_agent`**: calls `delete_sandbox` synchronously, following the
  file's existing `_write_desired`/`_actual_unknown` accounting — not the
  prior attempt's bare `except Exception: pass`, which silently reported a
  failed teardown as clean.
- Both control branches import `flock.openshell` lazily, inside their
  `if agent_port_type == "openshell":` block — flagged by architect: this
  file is loaded for every control delivery regardless of port_type, and
  grpc/protobuf aren't cheap imports to pay unconditionally. Mirrors how
  `control/runner.py` already lazily imports `flock.tmux` and how
  `deliver.py`'s old `control` branch lazily imported `flock.control`.

## 4. Open questions (asked of, and answered by, architect on 2026-08-29)

- **Workspace scope:** one OpenShell `workspace` per tenant (`pod:tenant`),
  not per-agent, not shared — matches this system's existing invariant that
  a tenant is the bounded unit (`LLD-container.md`, "one container is one
  tenant"). Flag to architect if OpenShell-side billing/quota/policy scoping
  argues otherwise once actually tested.
- **Headless invocation shape:** one-shot/headless per delivery, confirmed
  — see §2. Per-CLI logic lives beside the existing tmux per-CLI logic in
  spirit (`start_agent_command`), not baked into a wrapper script in the
  sandbox image, so it stays reviewable in one place.
- **"provider" naming collision:** OpenShell's own named-credential-bundle
  mechanism (`SandboxSpec.providers`) is always called "openshell provider"
  in this code/these docs, never bare "provider" — flock already uses that
  word for an unrelated concept (model backend selected for tmux agents,
  `PROVIDER_<NAME>_URL`). See `NAMING-openshell.md`.

- **Gateway endpoint (corrected 2026-08-29):** the gateway was widened to
  bind `0.0.0.0` and the tenant container is back on normal (non-host)
  networking. Real integration code should use
  `OPENSHELL_GATEWAY_ENDPOINT=https://host.docker.internal:17670`, which
  requires `extra_hosts: ["host.docker.internal:host-gateway"]` on the
  tenant container (already applied on the test VM by `acceptance`) — not
  the VM's raw bridge IP, which isn't stable across container recreates.

Still open, not yet asked:
- **Whether this integration needs its own mTLS client identity**,
  separate from the lab's local `openshell` CLI registration used for the
  §2a verification run — raised by architect, not yet decided.
- `agy` and opencode/copilot's presence in the default sandbox image, if
  they need to be there. Confirmed (§5, credential-transfer testing):
  `agy` is **not** installed in the default image at all (`which agy`
  exits 1) — not chased further, tracked as a known gap rather than fixed
  here.

Correction to an earlier pass through this row (architect, 2026-08-29):
an intermediate edit here claimed the codex/agy credential-transfer test
(§5) also confirmed `resume=True` for claude, since that test used a real
`CLAUDE_CODE_OAUTH_TOKEN` and got a genuine reply. That overstated it —
auth succeeding with `resume=True` in the argv is not the same claim as
"a fresh sandbox with nothing to continue behaves correctly under
`resume=True`," and no test has isolated that second, narrower case for
claude the way it was directly observed for codex. Still open — see §6.

Resolved since the last update:
- ~~The 19-character sandbox name limit vs. 63-character flock agent
  names~~ — resolved via `naming.short_name()` (§3).
- ~~The `AGENT_STATE_RESOURCES` change needed to persist a sandbox id~~ —
  avoided entirely: no new resource added, `get_sandbox` is called fresh
  before every `exec` instead (§3a).

## 5. Status update — Attachment delivery built and real-gateway-verified (ticket 655ebeac)

`_deliver_attachment` in `flock/port/openshell.py`: same validation as
tmux's `flock.tmux.openers.attachment_opener` (filename/mime_type/caption/content_base64
charset and size limits), then `_write_attachment` (base64-decode-into-
temp-file-then-atomic-mv via `exec_sandbox`, positional shell params for
the paths rather than string interpolation), then the same
headless-exec-and-reply path `_deliver_message`/`_deliver_command` already
use for the "[attachment from ...] saved to ..." notice.

**Real, previously-wrong assumption caught by live testing**: the first
version used `/workdir/<agent>/attachments/<stream_id>/` — flock's own
tmux-container convention. That path does not exist inside an OpenShell
sandbox at all; a real run got `mkdir: /workdir: Permission denied`.
Confirmed directly (`pwd`/`$HOME` inside a real sandbox both report
`/sandbox`) and fixed: the real base path is `/sandbox/attachments/
<stream_id>/`, with no per-agent subdirectory needed since each sandbox
already belongs to exactly one agent, unlike tmux's shared container.

**Confirmed genuinely real end to end**: built a real envelope, ran
`deliver_openshell` against a real sandbox on the live gateway, and
directly `exec_sandbox`'d a `find`/`cat` from a second, independent
client afterward — the file was really there, byte-for-byte correct
content, and the automatic reply (the CLI's own honest "Not logged in",
no credential injected) genuinely arrived back through the real bus.

Considered and rejected as the mechanism: `openshell sandbox upload`/
`download` (confirmed via `-vvv` tracing to use a real SSH session via
`CreateSshSession`, not `ExecSandbox`) — would need a new SSH-client
dependency (e.g. paramiko) to reproduce from Python, versus zero new
dependencies for the `exec_sandbox` approach actually built.

`pending.verify`/`delivery.markers` are still skipped for this port_type,
same reasoning the prior attempt gave and which still holds: `ExecSandbox`
is synchronous and returns a real result directly, and this container's
`ActivityTailer` cannot see inside an external sandbox, so those markers
would only produce false "unverified" alerts. (Trivially true here: this
module never calls `mark_delivery_pending` at all.)

All four envelope kinds (Message, Command, AddTicket, Attachment) and the
full StartAgent/StopAgent lifecycle are now built and have each been run
against the live gateway for real, not just unit-tested.

## 6. Current status, in one place (2026-08-29 docs sweep)

Everything above this line is the chronological build record — useful for
*why*, kept as-is rather than rewritten into a single narrative. This
section is what to trust for *current* state without reading the rest.

**Built and real-gateway-verified end to end:**
- Full lifecycle: `StartAgent` → real sandbox create, `StopAgent` → real
  sandbox delete (§2a, §3a).
- All four envelope kinds: `Message`, `Command` (§3a), `AddTicket` (reuses
  the shared tmux opener unchanged), `Attachment` (§5).
- Per-profile credential lookup (`f6b9f6fe`): `start_agent` validates and
  publishes `payload.profile`; delivery reads it and passes
  `CLAUDE_OAUTH_TOKEN_<PROFILE>` as `exec_sandbox`'s per-call `env=` for
  claude, or writes/wipes `CODEX_AUTH_JSON_<PROFILE>`/
  `AGY_AUTH_JSON_<PROFILE>`'s JSON content as a file immediately around
  the exec for codex/agy — see
  [`openshell-credential-transfer-design.md`](openshell-credential-transfer-design.md).
  Claude's env-var path and codex's file path were both confirmed with a
  **real, working credential** (one-time, scoped authorizations); agy's
  file path could not be exercised the same way because `agy` is not
  installed in the default sandbox image at all.
- Real, previously-hidden bugs found this way and fixed: `create_sandbox`
  not waiting for READY before returning (§2a); the real (non-injected)
  client construction path having no mTLS support at all (§3); OpenShell
  resource names (sandboxes *and* workspaces) capping at 19 characters,
  shorter than flock's 63-character agent names (§3); workspaces needing
  explicit creation before first use (§3); `create_provider`'s `name`
  argument being silently discarded server-side (found while expanding
  the SDK surface, ticket `655ebeac` — see the inventory doc); the
  `/workdir` vs. real `/sandbox` base-path assumption for Attachment
  writes (§5); setting any `SandboxSpec.policy` field replacing the
  sandbox's entire baked-in default policy including its implicit network
  access (found expanding the SDK surface — see the inventory doc).
- Zero changes to `src/flock/switch/service.py` or anything under
  `src/flock/bus/`, confirmed directly, throughout every pass above.

**Genuinely still open** (not stale — these are real, unresolved as of
this sweep):
- Whether this integration needs its own mTLS client identity, separate
  from the lab's local `openshell` CLI registration used for every
  verification pass so far (§3, §4).
- `resume=True` unconditionally is confirmed safe for codex (observed
  directly) but only *inferred* safe for claude from documented CLI
  ergonomics — not observed, since every real-credential claude test so
  far used a fresh sandbox with `resume=True` already baked into the argv
  by `headless_command`, never isolating the "nothing to continue" case
  specifically (§2, §4).
- `agy` is not in the default sandbox image at all — confirmed directly,
  repeatedly. Its headless argv (`headless.py`) remains an unverified
  placeholder, and its credential-file path has never been exercised for
  real, for the same reason.
- Whether `SandboxSpec.policy`'s fuller L7 network-policy surface (MCP/
  GraphQL-aware rules, credential binding, middleware) is worth building
  beyond the plain filesystem/process/host+port slice already shipped —
  see the SDK inventory doc's own "worth building next" opinion.
- Credential rotation for a long-lived sandbox — not addressed anywhere.
