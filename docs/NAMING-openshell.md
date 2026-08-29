# Naming inventory — openshell lane

Inventory only: this document proposes no rename and changes no interface.
Tier A is documentation, B internal code, C Redis/environment, and D wire.

## `flock.openshell`

| name | where it lives | kind | what it means, in one line | networking analogue, if any | tier |
|---|---|---|---|---|---|
| `OpenShellClient` | `src/flock/openshell/client.py` | identifier | Thin wrapper around the real `openshell.SandboxClient`, one instance per tenant workspace. | Port-side transport client. | B |
| `OpenShellUnavailable` | `src/flock/openshell/client.py` | identifier | Every gateway/RPC failure, wrapped to one type so callers never import grpc/openshell exceptions directly. | Link/transport failure. | B |
| `OPENSHELL_GATEWAY_ENDPOINT` | `src/flock/openshell/client.py` | env var | `host:port` for the OpenShell gateway's gRPC channel. | Upstream service address. | C |
| `workspace` | `src/flock/openshell/client.py` | identifier | OpenShell's own tenancy-scoping dimension, mapped 1:1 to `pod:tenant` here. | Routing-domain instance name (compare tmux's `session_name`). | B |
| **`openshell provider`** | `src/flock/openshell/client.py` (`SandboxSpec.providers`) | identifier | OpenShell's own named credential-bundle mechanism, attached to a sandbox at creation. | Injected upstream credentials. | B |
| `headless_command` | `src/flock/openshell/headless.py` | identifier | Builds the non-interactive argv for one CLI invocation inside `ExecSandbox`; mirrors `start_agent_command`'s per-CLI branching for interactive tmux launch. | Non-interactive protocol handler selection. | B |
| `UNVERIFIED_HEADLESS_CLIS` | `src/flock/openshell/headless.py` | identifier | CLIs whose headless argv is a placeholder guess, not even a help-text-derived inference — currently `agy` only. | None. | B |

## The naming collision this lane must not repeat

**`provider` already means something else in this codebase**, and it is a
different concept from what OpenShell calls a provider:

- `flock.tmux`/`flock.tmuxhost`'s `provider` (see `NAMING-tmux.md`) is a
  **model backend** selected for a tmux agent — a name that resolves to
  `PROVIDER_<NAME>_URL`/`_TOKEN`/`_MODEL` environment variables read by
  `tmuxhost`. `NAMING-tmux.md` itself already flags this sense as
  "misleading: a model uplink, not the participant provider."
- OpenShell's `provider` (`SandboxSpec.providers`, `AttachSandboxProvider`)
  is a **named credential bundle** attached to a sandbox at creation — a
  different kind of thing entirely, sharing only the word.

Every reference to the OpenShell sense in this lane's code and docs is
written as **"openshell provider"**, never bare "provider", specifically so
these two do not get conflated in a future diff or bug report. If a bare
"provider" appears anywhere in `flock.openshell`, `flock.port.openshell`, or
`flock.control` code touching port_type `openshell`, treat it as a naming
bug to fix, not a term to infer from context.
