# tmux lane — runtime invariants

These are claims about a running tenant, not descriptions of intended code.
Each claim names an observation that would disprove it.

| invariant | falsifying observation |
|---|---|
| One rostered `vab=tmux` name converges to exactly one same-named window. | A settled rostered name has zero windows, or `list-windows -F '#{window_name}'` returns it more than once. |
| tmuxhost is the sole creator after `StartAgent`; desired launch/profile/endpoint state is visible before the window. | A new window appears with a command or environment different from the Redis launch/profile/endpoint keys that preceded it. |
| A changed re-hire replaces stale actual state; an unchanged re-hire does not duplicate it. | The old CLI remains after a changed hire, or either hire leaves duplicate same-named windows. |
| A failed window lookup or paste is observable and is not logged as `opened`. | The delivery log contains `opened` after tmux returned non-zero, with no adapter error/dead-letter evidence. |
| Losing the last agent window does not destroy the tenant session permanently. | After reconciliation time, the session is absent or the retired/stale window is the only object preserving it. |
| API and Redis credentials do not reach the tmux server or agent pane environments. | `API_TOKEN`, `REDIS_PASSWORD`, `REDISCLI_AUTH`, or an authenticated `REDIS_URL` appears in the tmux global environment or `/proc/<pane_pid>/environ`. |
| The container—not an agent home—is the isolation boundary. Agents are colleagues and can read another agent's `/workdir` files. | A normal agent pane running as the tenant user receives a permissions error reading a peer's ordinary file. Such access would not be a security improvement unless the documented boundary changes with it. |
| Window names, not indices or substring matches, identify agents. | An operation addressed to one name affects a different window, or `sim-a` is accepted as evidence for `sim-a-long`. |

The scenarios under `container/scenarios/tmux-*.sh` print raw commands and
observations. They intentionally do not decide these claims for the reader.
