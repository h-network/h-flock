# LLD — the openshell port

> **Status: SDK layer verified against a live gateway; delivery/lifecycle
> wiring not built.** `src/flock/openshell/client.py` and
> `src/flock/openshell/headless.py` exist, are unit-tested against an
> injected fake, and — as of 2026-08-29 — have also been exercised for
> real against the office's OpenShell test VM (`172.16.10.101`, gateway
> `openshell-gateway` 0.0.116): real `create` → `wait_ready` → `exec` →
> `delete` cycle, real health check, real per-CLI headless invocation.
> `flock.port`/`flock.control` are still not wired to any of this. Depends
> on [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) for the address
> scheme and [`LLD-port-tmux.md`](LLD-port-tmux.md) for the receiving-edge
> shape this port_type parallels.

This document exists to keep design decisions and open questions in one
place while the gateway is unavailable, so building doesn't restart from
zero once it is. Ticket: `ff0f4516` in the office board.

## 1. What this is

`port_type: openshell` hosts a roster agent inside an NVIDIA OpenShell
sandbox — a policy-governed, isolated container — instead of a tmux window.
Same switch/bus, same `flock.port` binary, same one-shot-per-delivery
model; a different `deliver_one` branch in `src/flock/port/deliver.py`
(not built yet) and a different pair of lifecycle actions in
`src/flock/control/openers.py` (also not built yet).

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

Two real corrections this produced, now reflected in the code:
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
  document implied. Not yet resolved — needs either a deterministic
  short-name derivation (and the real agent name kept in `labels`, which
  has no such length limit observed) or confirmation from OpenShell docs
  of the exact limit's shape before picking one. Flagged, not fixed.

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
- The exact sandbox image / how `agy` (and opencode/copilot) get into it,
  if they need to.
- The `AGENT_STATE_RESOURCES` change needed to persist a sandbox id per
  agent (or an alternative that avoids it).
- **The 19-character sandbox name limit vs. 63-character flock agent
  names** (§2a) — needs a real decision, not just a flag.
- **Whether this integration needs its own mTLS client identity**,
  separate from the lab's local `openshell` CLI registration used for the
  §2a verification run — raised by architect, not yet decided.

## 5. Not built yet

- `src/flock/port/openshell.py` and the `deliver.py` branch that reaches it.
- `control/openers.py`'s `start_agent`/`stop_agent` branches for
  `port_type: openshell` (`create_sandbox` / `delete_sandbox`, following the
  file's existing acknowledged/unknown/failed accounting — not a bare
  `except: pass`, which is what the prior attempt did for teardown).
- Attachment delivery (base64-exec-and-mv via `exec_sandbox`, the same
  approach the prior attempt sketched — plausible given `exec` is
  confirmed real, but unverified end-to-end).
- `pending.verify`/`delivery.markers` are expected to be skipped for this
  port_type, same reasoning the prior attempt gave and which still holds:
  `ExecSandbox` is synchronous and returns a real result directly, and this
  container's `ActivityTailer` cannot see inside an external sandbox, so
  those markers would only produce false "unverified" alerts.

All of the above needs a reachable gateway to build against honestly, per
the standing instruction on this ticket: report what's verified versus
assumed, don't let mocked tests stand in for real connectivity.
