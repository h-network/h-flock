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

Via `flock.openshell.client.OpenShellClient`, itself wrapping the SDK's
`SandboxClient`/`WorkspaceClient`:

| capability | SDK method | RPC |
|---|---|---|
| health check | `SandboxClient.health()` | `Health` |
| create + wait ready | `.create()` + `.wait_ready()` | `CreateSandbox` + polled `GetSandbox` |
| read status | `.get()` | `GetSandbox` |
| delete | `.delete()` | `DeleteSandbox` |
| run a command | `.exec()` / `.exec_stream()` | `ExecSandbox` (server-streaming, consumed to completion) |
| workspace get-or-create | `WorkspaceClient.get()`/`.create()` | `GetWorkspace` / `CreateWorkspace` |

Everything below this line is **not used**, either because the SDK doesn't
wrap it at all (raw stub access only) or because it's wrapped but flock
never calls it.

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
| `StopSandbox` | `.stop()` | **not used** — pause without deleting. Distinct from delete; a stopped sandbox can be `StartSandbox`ed again without losing its filesystem, per the `SANDBOX_PHASE_STOPPED` phase already in the enum flock reads today (§4). |
| `StartSandbox` | `.start()` | **not used** — resume a stopped sandbox. |
| `ListSandboxes` | `.list()` / `.list_for_all_workspaces()` | **not used** — enumerate sandboxes in a workspace (or all). Could replace flock's per-agent `get_sandbox` probing with one listing call for e.g. a reconciler that wants to sweep orphaned sandboxes. |
| `WatchSandbox` | none | **not used, not wrapped**. Server-streaming: `follow_status`/`follow_logs`/`follow_events`, `log_tail_lines`, `stop_on_terminal`. This is real-time push (status changes, log lines, platform events) instead of polling `GetSandbox`/`GetSandboxLogs` — see §7. |

## 4. Exec & interactive access

| RPC | wrapped as | notes |
|---|---|---|
| `ExecSandbox` (server-streaming) | `.exec()`/`.exec_stream()` | used, but flock only ever consumes it to completion (`exec()`), discarding intermediate `ExecChunk`s — see §7 for why streaming chunks matter for flock specifically. |
| `ExecSandboxInteractive` (bidi-streaming) | none | **not used, not wrapped at all**. `ExecSandboxInput{start, stdin, resize}` in, `ExecSandboxEvent` out, with `ExecSandboxWindowResize{cols, rows}` support. This is an actual PTY-style interactive session — a real "attach and type into it live" primitive that the SDK doesn't even give a convenience method for. Doesn't change the §2a finding that plain `ExecSandbox` is one-shot; this is a genuinely different, richer RPC that could in principle support something closer to tmux's live-pane model, at real added complexity (bidi streaming inside a one-shot `flock.port` process is an awkward fit — would need its own design, not a drop-in). |
| `CreateSshSession` / `RevokeSshSession` | none | **not used, not wrapped**. Issues a token + gateway host/port/scheme/host-key-fingerprint for SSH access to a sandbox (`CreateSshSessionResponse`). A genuine alternate access path, orthogonal to `ExecSandbox`. |
| `ForwardTcp` (bidi-streaming) | none | **not used, not wrapped**. `TcpForwardInit{sandbox_id, service_id, ssh|tcp target, authorization_token}` + raw `TcpForwardFrame.data` — a raw TCP tunnel into a sandbox, used together with §5's service-exposure RPCs. |

## 5. Networking / service exposure (entirely unused)

| RPC | notes |
|---|---|
| `ExposeService` | `{sandbox, service, target_port, domain, workspace}` → registers a port inside the sandbox as reachable. `domain: bool` implies a public-domain option, not just an internal address. |
| `GetService` / `ListServices` / `DeleteService` | CRUD over exposed services; `ServiceEndpointResponse{endpoint, url}` gives back a real reachable URL. |

None of this is used. If an openshell-sandboxed agent ever needs to expose
something (a dev server, a webhook receiver) the way a tmux agent might
bind a port on the container itself, this is the mechanism — currently
nothing in `flock.openshell` touches it.

## 6. Provider / credential management (much bigger than `SandboxSpec.providers`)

`flock.openshell.client.create_sandbox`'s `providers: Sequence[str]`
parameter only *attaches providers by name*
(`SandboxSpec.providers: repeated string`). The actual provider
lifecycle is a whole separate, much larger subsystem, entirely untouched:

| RPC | purpose |
|---|---|
| `CreateProvider` / `GetProvider` / `ListProviders` / `UpdateProvider` / `DeleteProvider` | Full CRUD on `Provider` objects (`datamodel_pb2.Provider`: `metadata`, `type`, `credentials: map<string,string>`, `config: map<string,string>`, `credential_expires_at_ms`, `profile_workspace`, `credential_handles: map<string, CredentialHandle>`). This is where a named credential bundle (e.g. an "openshell provider" like `anthropic-oauth`) actually gets defined — flock currently assumes such a name already exists and just references it; nothing in this codebase can create one. |
| `ListProviderProfiles` / `GetProviderProfile` / `ImportProviderProfiles` / `UpdateProviderProfiles` / `LintProviderProfiles` / `DeleteProviderProfile` | A separate, richer `ProviderProfile` concept — `display_name`, `description`, `category` (`ProviderProfileCategory`: INFERENCE/AGENT/SOURCE_CONTROL/MESSAGING/DATA/KNOWLEDGE/OTHER), `credentials`, `endpoints`, `binaries`, `inference_capable`, `discovery`, `source`, `scope`. Looks like a catalog/template layer above raw `Provider`s (importable, lintable) — plausibly how an operator would define reusable credential templates across workspaces rather than hand-building each `Provider`. |
| `GetProviderRefreshStatus` / `ConfigureProviderRefresh` / `RotateProviderCredential` / `DeleteProviderRefresh` | Credential refresh lifecycle — `ProviderCredentialRefreshStrategy` includes OAUTH2_REFRESH_TOKEN, OAUTH2_CLIENT_CREDENTIALS, GOOGLE_SERVICE_ACCOUNT_JWT, AWS_STS_ASSUME_ROLE, EXTERNAL, STATIC — this is a real, fairly complete credential-rotation system, not a stub. |
| `ListSandboxProviders` / `AttachSandboxProvider` / `DetachSandboxProvider` | Attach/detach a provider **after** a sandbox already exists (`AttachSandboxProviderRequest` takes `expected_resource_version` — optimistic concurrency control) rather than only at `CreateSandbox` time. flock currently only sets `providers` at creation; this would let a running sandbox's credentials be rotated without recreating it. |
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
(`create_sandbox(providers=[...])` → plain `exec_sandbox`). If it turns
out this genuinely doesn't help `claude` (because of its client-side
login gate), the practical path to closing "sandbox starts logged out"
is more likely still `SandboxSpec.environment` (an actual env var flock
sets directly at creation, the same shape flock's own tmux lane already
uses for `CLAUDE_CODE_OAUTH_TOKEN`) than the provider-attachment
mechanism — worth a real-credential test to settle this before building
around either assumption.

## 7. Observability (logs, watch, health) — mostly unused

| RPC | wrapped as | notes |
|---|---|---|
| `GetSandboxLogs` | none | **not used, not wrapped**. `{sandbox_id, lines, since_ms, sources, min_level, workspace}` — pull-model log read (like `kubectl logs`), independent of `ExecSandbox`'s own stdout/stderr. |
| `WatchSandbox` | none | **not used, not wrapped**, see §3. `SandboxStreamEvent{sandbox, log: SandboxLogLine, event: PlatformEvent, warning, draft_policy_update}` — one stream multiplexing status changes, log lines, and platform events. This is the closest OpenShell analogue to flock's own `ActivityTailer`/watchdog concept (tailing an agent's activity file) — worth remembering given `docs/LLD-port-openshell.md` already argues `pending.verify`/`delivery.markers` don't apply here because "this container's ActivityTailer can't see into an external sandbox." `WatchSandbox` is the one RPC that could actually change that conclusion — it's a real, live signal source from *inside* the sandbox that flock currently has no equivalent for. Worth a closer look before assuming that gap is permanent. |
| `Health` | `.health()` | used |
| `GetCurrentUser` | none | **not used, not wrapped**. `{subject, display_name, roles, scopes, identity_provider}` — directly relevant to the still-open "whose mTLS identity" question: this RPC would tell you, for real, which identity a given cert/token actually authenticates as, rather than inferring it from which cert file was used. |
| `GetGatewayInfo` | none | **not used, not wrapped**. `{status, gateway_version, compute_drivers: [{name, capabilities}]}` — compute driver capabilities could matter for whatever sandbox templates/runtime classes are available on a given gateway. |

## 8. Sandbox execution environment (partially unused)

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
- `SandboxSpec.policy: SandboxPolicy` — flock's `create_sandbox`
  deliberately omits this (comment in `client.py`: lets the sandbox
  discover policy from its baked-in default). The real `SandboxPolicy`
  shape is substantial and currently 100% unused by flock:
  - `FilesystemPolicy{include_workdir, read_only: [paths], read_write: [paths]}`
  - `LandlockPolicy{compatibility}` — Landlock LSM compatibility mode
  - `ProcessPolicy{run_as_user, run_as_group}`
  - `network_policies: map<name, NetworkPolicyRule>` — each rule lists
    `endpoints: [NetworkEndpoint]` and `binaries: [NetworkBinary]`
    (i.e. network access can be scoped to specific host binaries, not
    just the sandbox as a whole)
  - `NetworkEndpoint` is large and genuinely L7-aware: TLS, an
    `enforcement`/`access` mode, `allow_encoded_slash`,
    `persisted_queries`/`graphql_persisted_queries` +
    `graphql_max_body_bytes` (GraphQL-specific controls),
    `websocket_credential_rewrite`/`request_body_credential_rewrite`,
    `json_rpc_max_body_bytes`, an `mcp: McpOptions` field (MCP-protocol
    awareness specifically), `credential_binding`/`provider_credentialed`
    (ties a network rule to a specific attached provider's credential)
  - `network_middlewares: map<name, NetworkMiddlewareConfig>` — pluggable
    middleware (`middleware` name + `config: Struct`, ordered, scoped by
    `MiddlewareEndpointSelector{include, exclude}`)

  This is a real, fine-grained, protocol-aware egress control system —
  the actual substance behind this ticket's own framing of OpenShell as
  "policy-governed" sandboxing. Flock currently opts out of all of it by
  never setting `policy` at all.
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

## 12. What seems worth building next (opinion, not a decision)

In rough order of how directly they'd serve flock's actual needs, not
NVIDIA's:

1. **`GetSandboxProviderEnvironment`** — cheapest, most directly useful:
   turns "what did the provider actually inject" from a guess into an
   observable fact, closing a real gap in this ticket's own docs.
2. **`WatchSandbox`** — could genuinely change the "no ActivityTailer
   equivalent" conclusion this ticket's docs currently rely on; worth
   confirming or refuting deliberately rather than leaving as an
   assumption.
3. **`StopSandbox`/`StartSandbox`** — cheap to wire in, gives `PauseAgent`/
   `ResumeAgent` (already real lifecycle actions for tmux agents) a real
   openshell-side implementation instead of no-op/unsupported.
4. **`SandboxSpec.policy`** (network/filesystem/process) — the actual
   substance of "policy-governed" that flock currently opts out of by
   never setting it; biggest single gap between what this integration
   claims and what it uses.
5. Provider CRUD (`CreateProvider` et al.) — only matters once there's an
   actual credential to provision through flock rather than assumed to
   pre-exist; lower priority until that decision is made.

Everything else in this document is real and available, but further from
anything flock currently does.
