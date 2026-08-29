# OpenShell SDK/gRPC surface inventory

Requested by telegram (via architect, 2026-08-29): a full inventory of what
`openshell` 0.0.116's gRPC surface actually offers, beyond the
`create_sandbox`/`get_sandbox`/`delete_sandbox`/`exec_sandbox` slice
`flock.openshell` currently uses — as input for deciding what's worth
building next. Not code, just the inventory, per the ask.

**Method:** read directly from the installed package
(`openshell/_proto/*_grpc.py` for the definitive RPC list per service,
`*.pyi` for message shapes, `sandbox.py` for what the SDK's own high-level
wrappers cover). Not from external OpenShell docs — this may drift from
whatever NVIDIA publishes separately; treat field names as accurate for
0.0.116 specifically.

## 1. What h-flock uses today

**Updated 2026-08-29 (docs sweep, ticket `53c8a128`)** — this section
originally listed only the four-method slice this doc was first written
against; ticket `655ebeac` built substantially more of the surface below
since then. Current list, via `flock.openshell.client.OpenShellClient`:

| capability | SDK method | RPC |
|---|---|---|
| health check | `SandboxClient.health()` | `Health` |
| create + wait ready (+ opt-in partial policy) | `.create()` + `.wait_ready()` | `CreateSandbox` + polled `GetSandbox` |
| read status | `.get()` | `GetSandbox` |
| list | `.list()` | `ListSandboxes` |
| stop / start | `.stop()` / `.start()` + `.wait_ready()` | `StopSandbox` / `StartSandbox` |
| delete | `.delete()` | `DeleteSandbox` |
| run a command | `.exec()` / `.exec_stream()` | `ExecSandbox` (server-streaming, consumed to completion) |
| workspace get-or-create | `WorkspaceClient.get()`/`.create()` | `GetWorkspace` / `CreateWorkspace` |
| expose/get/list/delete a service | raw stub | `ExposeService` / `GetService` / `ListServices` / `DeleteService` |
| provider CRUD (create/list/delete) + sandbox attach/detach/list | raw stub | `CreateProvider` / `ListProviders` / `DeleteProvider` / `AttachSandboxProvider` / `DetachSandboxProvider` / `ListSandboxProviders` |
| read logs | raw stub | `GetSandboxLogs` |
| watch (lazy generator) | raw stub | `WatchSandbox` |

Everything below this line not listed above is still **not used**, either
because the SDK doesn't wrap it at all (raw stub access only) or because
it's wrapped but flock never calls it — the per-section tables further
down were written before the above was built and, in a few spots, still
say "not used" for capabilities that are now used; §3/§5/§6/§7's tables
below have been corrected accordingly, but treat this section as the
authoritative current list if the two ever disagree again.

## 2. The gateway's two services

`openshell.SandboxClient`/`WorkspaceClient`/`InferenceRouteClient` all sit
on top of **one** gRPC service, `OpenShellStub` (~70 RPCs) — plus a
second, smaller `InferenceStub` (4 RPCs) for model-routing config. The SDK
only builds convenience wrappers for a fraction of `OpenShellStub`; the
rest is real and reachable (`client._stub.<RpcName>(...)`) but has no
Python-level wrapper method at all.

## 3. Sandbox lifecycle & inventory (mostly used, some gaps)

| RPC | wrapped as | notes |
|---|---|---|
| `CreateSandbox` | `.create()` | used |
| `GetSandbox` | `.get()` | used |
| `DeleteSandbox` | `.delete()` | used |
| `StopSandbox` | `.stop()` | used (`OpenShellClient.stop_sandbox`) — pause without deleting; a stopped sandbox can be `StartSandbox`ed again without losing its filesystem. Not yet wired into `control/openers.py`'s `pause_agent`, which openshell agents still have no real implementation for — the client method exists, the control-lifecycle hookup doesn't. |
| `StartSandbox` | `.start()` | used (`OpenShellClient.start_sandbox`) — resume a stopped sandbox. Same "client method exists, `resume_agent` hookup doesn't" gap as `StopSandbox`. |
| `ListSandboxes` | `.list()` / `.list_for_all_workspaces()` | used (`OpenShellClient.list_sandboxes`, workspace-scoped only — `list_for_all_workspaces` still unwrapped). Not yet used by anything in `flock.port`/`flock.control` itself (e.g. a reconciler sweeping orphaned sandboxes) — just available on the client. |
| `WatchSandbox` | `OpenShellClient.watch_sandbox` (lazy generator) | Wrapped and confirmed real against the live gateway (received a genuine streamed event). Server-streaming: `follow_status`/`follow_logs`/`follow_events`, `log_tail_lines`, `stop_on_terminal`. Real-time push (status changes, log lines, platform events) instead of polling `GetSandbox`/`GetSandboxLogs` — see §7. Nothing in `flock.port`/`flock.control` consumes it yet. |

## 4. Exec & interactive access

| RPC | wrapped as | notes |
|---|---|---|
| `ExecSandbox` (server-streaming) | `.exec()`/`.exec_stream()` | used, but flock only ever consumes it to completion (`exec()`), discarding intermediate `ExecChunk`s — see §7 for why streaming chunks matter for flock specifically. |
| `ExecSandboxInteractive` (bidi-streaming) | none | **not used, not wrapped at all**. `ExecSandboxInput{start, stdin, resize}` in, `ExecSandboxEvent` out, with `ExecSandboxWindowResize{cols, rows}` support. This is an actual PTY-style interactive session — a real "attach and type into it live" primitive that the SDK doesn't even give a convenience method for. Doesn't change the §2a finding that plain `ExecSandbox` is one-shot; this is a genuinely different, richer RPC that could in principle support something closer to tmux's live-pane model, at real added complexity (bidi streaming inside a one-shot `flock.port` process is an awkward fit — would need its own design, not a drop-in). |
| `CreateSshSession` / `RevokeSshSession` | none | **not used, not wrapped**. Issues a token + gateway host/port/scheme/host-key-fingerprint for SSH access to a sandbox (`CreateSshSessionResponse`). A genuine alternate access path, orthogonal to `ExecSandbox`. |
| `ForwardTcp` (bidi-streaming) | none | **not used, not wrapped**. `TcpForwardInit{sandbox_id, service_id, ssh|tcp target, authorization_token}` + raw `TcpForwardFrame.data` — a raw TCP tunnel into a sandbox, used together with §5's service-exposure RPCs. |

## 5. Networking / service exposure (client-wrapped, not used by any delivery/lifecycle path yet)

| RPC | notes |
|---|---|
| `ExposeService` | `{sandbox, service, target_port, domain, workspace}` → registers a port inside the sandbox as reachable. `domain: bool` implies a public-domain option, not just an internal address. Wrapped as `OpenShellClient.expose_service`, confirmed real against the live gateway (got back a genuine reachable URL). |
| `GetService` / `ListServices` / `DeleteService` | CRUD over exposed services; `ServiceEndpointResponse{endpoint, url}` gives back a real reachable URL. Wrapped and confirmed real the same way. |

All four are wrapped on `OpenShellClient` and confirmed to work against
the live gateway, but nothing in `flock.port`/`flock.control` calls them
yet — no openshell agent's lifecycle currently exposes a service
automatically. If an openshell-sandboxed agent ever needs to expose
something (a dev server, a webhook receiver) the way a tmux agent might
bind a port on the container itself, the client-side mechanism is ready;
the lifecycle wiring to use it isn't.

## 6. Provider / credential management (much bigger than `SandboxSpec.providers`)

`flock.openshell.client.create_sandbox`'s `providers: Sequence[str]`
parameter only *attaches providers by name*
(`SandboxSpec.providers: repeated string`). A wider slice of the provider
lifecycle is now wrapped on the client (`create_provider`/
`list_providers`/`delete_provider`/`attach_sandbox_provider`/
`detach_sandbox_provider`/`list_sandbox_providers`), but **as a general
capability, not as flock's actual credential-transfer mechanism** — the
real delivery path uses per-CLI env-var/write-then-wipe transfer instead
(`docs/openshell-credential-transfer-design.md`), specifically because
telegram ruled out storing credentials in OpenShell's own `Provider`
object even server-side (§6a below). Still genuinely unused/unwrapped:

| RPC | purpose |
|---|---|
| `GetProvider` / `UpdateProvider` | Read/update a single existing `Provider` (`datamodel_pb2.Provider`: `metadata`, `type`, `credentials: map<string,string>`, `config: map<string,string>`, `credential_expires_at_ms`, `profile_workspace`, `credential_handles: map<string, CredentialHandle>`) — create/list/delete are wrapped (§1), these two aren't. |
| `ListProviderProfiles` / `GetProviderProfile` / `ImportProviderProfiles` / `UpdateProviderProfiles` / `LintProviderProfiles` / `DeleteProviderProfile` | A separate, richer `ProviderProfile` concept — `display_name`, `description`, `category` (`ProviderProfileCategory`: INFERENCE/AGENT/SOURCE_CONTROL/MESSAGING/DATA/KNOWLEDGE/OTHER), `credentials`, `endpoints`, `binaries`, `inference_capable`, `discovery`, `source`, `scope`. Looks like a catalog/template layer above raw `Provider`s (importable, lintable) — this is where the real, built-in `claude-code`/`codex`/`copilot`/`cursor` profiles found in §6a live. Read via the `openshell` CLI directly for that investigation; still nothing wrapped on `OpenShellClient`. |
| `GetProviderRefreshStatus` / `ConfigureProviderRefresh` / `RotateProviderCredential` / `DeleteProviderRefresh` | Credential refresh lifecycle — `ProviderCredentialRefreshStrategy` includes OAUTH2_REFRESH_TOKEN, OAUTH2_CLIENT_CREDENTIALS, GOOGLE_SERVICE_ACCOUNT_JWT, AWS_STS_ASSUME_ROLE, EXTERNAL, STATIC — this is a real, fairly complete credential-rotation system, not a stub. Unused — flock's own credential transfer has no rotation story at all yet (see `openshell-credential-transfer-design.md` §4). |
| `GetSandboxProviderEnvironment` | Returns whatever env vars a sandbox's attached providers resolve to (`supports_static_credential_bindings` flag) — a real introspection point for "what did the provider actually inject," which would help verify §8 of `LLD-port-openshell.md`'s open question about credential wiring without guessing. |
| `ExchangeProviderSubjectToken` | `{sandbox_id, provider, credential_key, supervisor_jwt_svid}` — looks like the sandbox-internal supervisor process's own mechanism for exchanging its identity (a JWT-SVID, i.e. SPIFFE-style workload identity) for the actual provider credential at runtime, rather than the credential being handed to the sandbox statically at creation. Internal machinery, not something flock would call directly, but explains *how* `providers` at creation time actually becomes a real credential inside the sandbox process.

**Relevance to the ticket's own credential-handling rule**: none of this
changes the "ask telegram before moving a real credential" rule — if
anything, `CreateProvider`/`ImportProviderProfiles` are exactly the
mechanism that rule is about, formalized as an API instead of an env var.

### 6a. Checked directly: does this already close the "sandbox starts
logged out" gap, the way `container/seed-home.sh` does for tmux?

Telegram's instinct (2026-08-29) — that OpenShell might already have a
seed-home.sh-shaped mechanism (copy an existing auth file/credential into
a sandbox) that would close this gap without flock building anything new
— is **half right, evidenced by real testing, not just proto reading**:

**Real and confirmed:** `openshell provider list-profiles` shows built-in,
purpose-built profiles for exactly the CLIs this ticket cares about —
`claude-code`, `codex`, `copilot`, `cursor` (category `AGENT`), plus
`aws`, `aws-s3`, `google-cloud`, `aws-bedrock`, `deepinfra`,
`google-vertex-ai`, `nvidia`, `github`, `pypi`. `openshell provider
profile export claude-code` shows its exact shape:

```
credentials:
- name: api_key
  env_vars: [ANTHROPIC_API_KEY, CLAUDE_API_KEY]
  required: true
  auth_style: header
  header_name: x-api-key
endpoints:
- {host: api.anthropic.com, port: 443, protocol: rest, access: read-write, enforcement: enforce}
- {host: statsig.anthropic.com, ...}
- {host: sentry.io, ...}
binaries: [/usr/bin/claude, /usr/local/bin/claude]
```

`auth_style: header`/`header_name: x-api-key` plus binary-scoped,
enforced `endpoints` strongly suggests the real mechanism is **L7 proxy
credential injection at the network layer** — the gateway's network
policy enforcement adds the `x-api-key` header to outbound requests from
the `claude` binary to `api.anthropic.com`, rather than writing a
credential file or env var into the sandbox itself (matching
`NetworkEndpoint.credential_binding`/`provider_credentialed` fields found
in §8's `SandboxPolicy` shape).

**Real and tested, with a dummy (non-functional) credential value — never
a real secret — specifically to avoid needing to ask before this check**:
created a workspace-scoped `claude-code`-typed provider
(`openshell provider create --name test-claude-mech --type claude-code
--credential api_key=dummy-test-value-not-real`), attached it to a
sandbox via `create_sandbox(..., providers=["test-claude-mech"])` (this
project's own actual code path, not a hand-rolled call).
`ListSandboxProviders` confirmed the attachment is real and structural
(`type: "claude-code"`, `credentials { key: "api_key" value: "REDACTED" }`
— correctly never exposes the raw value even to a legitimate caller).
`GetSandboxProviderEnvironment` — the one RPC that could have proven
credential materialization directly — refused with
`PERMISSION_DENIED: this method requires a sandbox principal`: it's
callable only by the sandbox's own internal supervisor identity, not by
an external client like flock, so it can't be used to introspect this
from outside.

**But: a plain `exec_sandbox(["printenv"])` on that same sandbox showed no
`ANTHROPIC_API_KEY`/`CLAUDE_API_KEY` at all, and `claude -p` still
reported `"Not logged in · Please run /login"`** — the identical result
as with no provider attached whatsoever. This is consistent with the
network-layer-injection theory: `claude`'s own CLI checks for a *local*
credential (file or env var) before ever attempting a network call, and
exits with "Not logged in" before an L7 proxy would ever get a chance to
inject anything into a request that's never sent. A proxy-injected header
only helps a client willing to send the request unauthenticated and trust
the proxy to add credentials in flight — `claude` isn't that client.

**Conclusion, precisely stated:** the mechanism telegram was thinking of
is real, purpose-built, and does not require flock to build anything new
to *define* — but a real end-to-end test (with an actual working
Anthropic key, which needs asking telegram first per the standing rule)
would be needed to know for certain whether it authenticates `claude`
specifically, and this session's dummy-credential test found no visible
effect through the path flock's own code currently uses
(`create_sandbox(providers=[...])` → plain `exec_sandbox`).

**Resolved since this was written**: telegram decided against the native
provider mechanism regardless of whether it would have worked technically
— credentials must stay in h-flock, not rest in OpenShell's own
`Provider` object even server-side. The actual shipped mechanism is
`exec_sandbox`'s per-call `env=` for claude (confirmed with a real
credential: genuine authentication, a real reply) and write-then-wipe
files for codex/agy (confirmed with a real credential for codex; `agy`
isn't in the default image to test against at all). See
`docs/openshell-credential-transfer-design.md`.

## 7. Observability (logs, watch, health) — health wrapped and used, logs/watch wrapped but not called anywhere yet

| RPC | wrapped as | notes |
|---|---|---|
| `GetSandboxLogs` | `OpenShellClient.get_sandbox_logs` | Wrapped, confirmed real against the live gateway. `{sandbox_id, lines, since_ms, sources, min_level, workspace}` — pull-model log read (like `kubectl logs`), independent of `ExecSandbox`'s own stdout/stderr. Nothing in `flock.port`/`flock.control` calls it yet — available on the client, not wired into any delivery/lifecycle path. |
| `WatchSandbox` | `OpenShellClient.watch_sandbox` | Wrapped and confirmed real (see §3). `SandboxStreamEvent{sandbox, log: SandboxLogLine, event: PlatformEvent, warning, draft_policy_update}` — one stream multiplexing status changes, log lines, and platform events. This remains the closest OpenShell analogue to flock's own `ActivityTailer`/watchdog concept — `docs/LLD-port-openshell.md` still argues `pending.verify`/`delivery.markers` don't apply here because "this container's ActivityTailer can't see into an external sandbox," and that conclusion still holds since nothing consumes this stream yet; it's the one RPC that *could* change it if someone builds that consumer. |
| `Health` | `.health()` | used |
| `GetCurrentUser` | none | **not used, not wrapped**. `{subject, display_name, roles, scopes, identity_provider}` — directly relevant to the still-open "whose mTLS identity" question: this RPC would tell you, for real, which identity a given cert/token actually authenticates as, rather than inferring it from which cert file was used. |
| `GetGatewayInfo` | none | **not used, not wrapped**. `{status, gateway_version, compute_drivers: [{name, capabilities}]}` — compute driver capabilities could matter for whatever sandbox templates/runtime classes are available on a given gateway. |

## 8. Sandbox execution environment (a slice now used, most still isn't)

`SandboxSpec`/`SandboxTemplate` fields flock's `create_sandbox` doesn't
set at all yet:

- `SandboxTemplate.image` / `runtime_class_name` / `agent_socket` — image
  selection (§ open question in `LLD-port-openshell.md` about how `agy`
  would get into the image) and container runtime class (e.g. gVisor/Kata
  vs. default) are both real, settable fields, currently defaulted by the
  gateway's own policy instead.
- `SandboxTemplate.user_namespaces: bool`, `driver_config: Struct` — extra
  isolation/driver knobs, unused.
- `SandboxSpec.resource_requirements.gpu.count` — **GPU resource
  requests are real and settable**; flock has never requested one. If an
  openshell-hosted agent ever needs GPU access this is the field, not
  something to invent.
- `SandboxSpec.policy: SandboxPolicy` — **partially used since this was
  first written.** `create_sandbox` now accepts opt-in `filesystem_read_only`/
  `filesystem_read_write`/`include_workdir`, `run_as_user`/`run_as_group`,
  and a `network_allow` pass-through, and confirmed real against the live
  gateway (`whoami` genuinely reflected a policy-specified user). Omitting
  all of them still omits `policy` entirely, unchanged from the original
  default-discovery behavior. **A real, previously-hidden gateway
  behavior found building this**: setting *any* of filesystem/process
  without also setting `network_allow` replaces the sandbox's entire
  baked-in default policy, including whatever network access it
  implicitly granted, and the container exits immediately
  (`ContainerExited`) — `create_sandbox` now raises `ValueError` up front
  rather than let that happen silently. Still 100% unused, no wrapper at
  all:
  - `LandlockPolicy{compatibility}` — Landlock LSM compatibility mode.
  - `NetworkEndpoint`'s full L7 richness beyond the plain `host`/`port`/
    `protocol` fields `network_allow` passes through close to verbatim:
    TLS, `enforcement`/`access` mode, `allow_encoded_slash`,
    `persisted_queries`/`graphql_persisted_queries` +
    `graphql_max_body_bytes` (GraphQL-specific controls),
    `websocket_credential_rewrite`/`request_body_credential_rewrite`,
    `json_rpc_max_body_bytes`, an `mcp: McpOptions` field (MCP-protocol
    awareness specifically), `credential_binding`/`provider_credentialed`
    (ties a network rule to a specific attached provider's credential).
  - `network_middlewares: map<name, NetworkMiddlewareConfig>` — pluggable
    middleware (`middleware` name + `config: Struct`, ordered, scoped by
    `MiddlewareEndpointSelector{include, exclude}`).

  The full L7 surface above is the real substance behind this ticket's
  own framing of OpenShell as "policy-governed" sandboxing, and flock
  still opts out of essentially all of it — what's shipped is a plain
  filesystem/process/host+port slice, not the protocol-aware egress
  control system this proto actually offers.
- **Draft-policy review subsystem** (`SubmitPolicyAnalysis`,
  `GetDraftPolicy`, `ApproveDraftChunk`/`RejectDraftChunk`/
  `ApproveAllDraftChunks`/`EditDraftChunk`/`UndoDraftChunk`/
  `ClearDraftChunks`, `GetDraftHistory`) — an entire iterative
  policy-tightening workflow (submit observed denials +
  `network_activity_summaries`, get back proposed `PolicyChunk`s, approve/
  reject/edit them individually, track `draft_version`/history). Nothing
  in flock touches this. Looks aimed at a human (or automated) reviewer
  gradually tightening a sandbox's egress policy based on what it actually
  tried to reach — a fundamentally different capability than anything
  flock does today, worth a dedicated look on its own if "isolated,
  policy-governed" ever needs to be more than the default.

## 9. Workspace management beyond get-or-create

| RPC | wrapped as | notes |
|---|---|---|
| `CreateWorkspace` / `GetWorkspace` | `.create()`/`.get()` | used (via `ensure_workspace()`) |
| `ListWorkspaces` | `.list()` | **not used** |
| `DeleteWorkspace` | `.delete()` | **not used** — flock creates a workspace per tenant and never removes it, even on tenant teardown. Not necessarily wrong (a workspace is cheap, reusable if the tenant comes back), but worth a deliberate decision rather than an oversight. |
| `AddWorkspaceMember` / `RemoveWorkspaceMember` / `ListWorkspaceMembers` | none | **not used, not wrapped**. `WorkspaceRole`: USER/ADMIN. Real workspace-level RBAC — currently irrelevant since flock authenticates as one identity per gateway connection, but relevant the moment "whose mTLS identity" (the standing open question) gets an answer that isn't "one shared identity for everything." |

## 10. Config / settings / gateway administration (entirely unused)

`GetSandboxConfig`/`GetGatewayConfig`/`UpdateConfig`,
`GetSandboxPolicyStatus`/`ListSandboxPolicies`/`ReportPolicyStatus`,
`IssueSandboxToken`/`RefreshSandboxToken`. Broadly: reading/writing
gateway- or sandbox-scoped settings (`SettingValue`/`EffectiveSetting`,
scoped `SETTING_SCOPE_SANDBOX`/`SETTING_SCOPE_GLOBAL`), and a token-based
sandbox authentication path distinct from the gateway's own mTLS
(`IssueSandboxTokenResponse{token, expires_at_ms}`,
`RefreshSandboxTokenResponse` also returns `extension_credentials`).
None of this looked directly relevant to flock's current needs on first
pass; flagging for completeness rather than recommending action.

## 11. Internal sandbox↔gateway protocol (not for flock to call)

`ConnectSupervisor`, `ReportMainProcessExit`, `PushSandboxLogs`,
`RelayStream` — these all look like the protocol the sandbox's own
in-container supervisor process uses to talk back to the gateway (pushing
logs, reporting the main process's exit, relaying streams), not something
an external client like flock should ever call directly. Listed for
completeness of the RPC inventory, not as a candidate.

## 11a. Update 2026-08-29 — built and real-gateway-verified (ticket 655ebeac)

Added to `flock.openshell.client.OpenShellClient`: `list_sandboxes`,
`stop_sandbox`/`start_sandbox`, `expose_service`/`get_service`/
`list_services`/`delete_service`, `create_provider`/`list_providers`/
`delete_provider`/`attach_sandbox_provider`/`detach_sandbox_provider`/
`list_sandbox_providers`, `get_sandbox_logs`, `watch_sandbox`, and a
deliberately partial opt-in `SandboxSpec.policy` slice on `create_sandbox`
(filesystem read-only/read-write/include_workdir, process run_as_user/
group, and a pass-through `network_allow`). Unit-tested against fakes,
then run for real against the live gateway. Two real, previously-unknown
findings from that live run, not visible from proto reading alone:

- **Setting *any* `SandboxPolicy` field replaces the entire baked-in
  default policy, including whatever network access it implicitly
  grants.** `run_as_user="sandbox"` alone (no `network_allow`) creates a
  sandbox whose container exits immediately
  (`SandboxCondition{reason: "ContainerExited"}`, only visible via a raw
  `GetSandbox` call — not surfaced as a creation-time error at all,
  `create()` succeeds and only `wait_ready()` eventually reports "entered
  error phase"). The identical policy plus one valid `network_allow` rule
  creates and reaches READY normally. `create_sandbox` now raises
  `ValueError` up front if filesystem/process policy is set without
  `network_allow`, rather than let a caller hit this opaquely.
  `run_as_user` also turned out to have real semantic validation beyond
  the proto's own string type: must be `"sandbox"` or a numeric UID/GID,
  not an arbitrary username (`"ubuntu"` was rejected outright,
  cleanly, at creation time — unlike the network-omission failure above).
- **`create_provider`'s `name` argument was silently discarded** — without
  setting `Provider.metadata.name` explicitly (a nested `ObjectMeta`
  field, not top-level on `Provider`), the gateway auto-assigns a random
  name instead (observed: passed `"verify-dummy2"`, got back
  `"belxyr"`), so a later `attach_sandbox_provider("verify-dummy2")`
  failed with "provider not found" — a bug only a real round trip could
  have caught. Fixed.
- **Confirmed real and working, unmodified from first pass**: sandbox
  create-with-policy (`whoami` genuinely returned the policy-specified
  user), list/stop/start, all four service-exposure operations (got a
  real reachable URL back), `get_sandbox_logs`, `watch_sandbox` (received
  a real streamed event).
- **A further, more specific constraint found on `attach_sandbox_provider`
  specifically** (post-creation attach, not `providers=[...]` at
  creation): the gateway refused to attach a `claude-code`-typed provider
  to a sandbox using the plain baked-in default policy —
  `FAILED_PRECONDITION: credentialed endpoint 'statsig.anthropic.com:443'
  ... uses L4-only; configure L7 inspection or explicitly set
  allow_uninspected_credentials: true`. Attaching `providers=[...]` at
  `CreateSandbox` time, by contrast, did *not* hit this in an earlier
  check (§6a) — the two paths appear to validate differently. Not fully
  reconciled; noted as a real nuance rather than resolved.

## 12. What seems worth building next (opinion, not a decision)

**Updated 2026-08-29 (docs sweep)** — most of this list has since been
built at the client layer; re-scoped to what's actually left, in rough
order of how directly it'd serve flock's needs:

1. **Wire `StopSandbox`/`StartSandbox` into `control/openers.py`'s
   `pause_agent`/`resume_agent`.** The client methods (`stop_sandbox`/
   `start_sandbox`) are built and real-verified; openshell agents still
   have no actual `PauseAgent`/`ResumeAgent` implementation calling them.
   Cheapest real gap left.
2. **Build a consumer for `watch_sandbox`.** The method exists and is
   real-verified, but nothing calls it — it's the one RPC that could
   change the "no ActivityTailer equivalent" conclusion
   `docs/LLD-port-openshell.md` still relies on, and that only happens
   once something actually consumes the stream, not just wraps the RPC.
3. **`SandboxSpec.policy`'s full L7 surface** (§8) — a plain filesystem/
   process/host+port slice is built; the protocol-aware egress control
   (GraphQL/MCP awareness, credential binding, middleware) that's the
   real substance of "policy-governed" remains untouched. Biggest
   still-real gap between what this integration claims and what it uses.
4. ~~`GetSandboxProviderEnvironment`~~ — **turned out to be a dead end**:
   confirmed directly (§6a) that this RPC refuses external callers
   (`PERMISSION_DENIED: this method requires a sandbox principal`), so it
   can never do what this recommendation assumed. Superseded.
5. ~~Provider CRUD~~ — built at the client layer, but telegram's decision
   (credentials must stay in h-flock, never rest in OpenShell's own
   `Provider` object) means it isn't and won't be flock's actual
   credential-transfer mechanism. Superseded for that purpose; the
   wrapped methods remain available for whatever else a provider object
   might be useful for.

Everything else in this document is real and available, but further from
anything flock currently does.
