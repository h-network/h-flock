# Verification round — tmux lane — 2026-08-22

Code was treated as authoritative. This sweep covered `LLD-port-tmux.md`,
`LLD-tmux-host.md`, `INVARIANTS-tmux.md`, and `NAMING-tmux.md`; dated build and
verification records were not edited.

## Contradictions fixed

| finding | code evidence | documentation fix |
|---|---|---|
| The port LLD assigned delivery judgment and `blocked` writes to the switch. The running service constructs `DeliveryVerifier` as a watchdog job, and that verifier reads `pending.verify`, judges eligible markers, and writes `blocked`. | `src/flock/watchdog/verification.py:85`; `src/flock/watchdog/verification.py:123`; `src/flock/watchdog/service.py:384` | `docs/LLD-port-tmux.md:173` now names the watchdog; `docs/LLD-port-tmux.md:211` uses the same ownership in the delivery narrative. |
| The port LLD documented only `pending.verify`, but every verifiable paste writes both that stream and `delivery.markers`. | `src/flock/port/openers.py:44`; `src/flock/port/openers.py:45`; `src/flock/port/openers.py:50`; `src/flock/port/openers.py:66` | `docs/LLD-port-tmux.md:152` documents both bounded streams, their consumers, ordering, and shared shape. |
| The LLD did not reflect the 10-to-120-second verification-window change or the simulator's derived wall-clock deadline. | `src/flock/watchdog/service.py:384`; `container/sim-blocked.sh:89` | `docs/LLD-port-tmux.md:173` documents the 120-second default; `docs/LLD-port-tmux.md:180` documents the derived harness deadline. |

## Absences fixed

| absent contract | code evidence | documentation fix |
|---|---|---|
| `delivery.markers` appeared in no living documentation. | `src/flock/port/openers.py:45`; `src/flock/port/openers.py:66` | Added its behavior to `docs/LLD-port-tmux.md:159`, its falsifiable runtime claim to `docs/INVARIANTS-tmux.md:16`, and its name/tier to `docs/NAMING-tmux.md:65`. |
| `FLOCK_CUSTODY_FILE` appeared in no living documentation, including the tmux-host explanation of quiet pane telemetry. | `container/entrypoint.sh:6`; `container/entrypoint.sh:16`; `src/flock/bus/logging.py:27`; `src/flock/bus/logging.py:122` | Extended the pane-to-window-log-to-switch-to-durable-file path in `docs/LLD-tmux-host.md:193` and added the environment name to `docs/NAMING-tmux.md:114`. |
| The operator-tunable verification window was absent from the tmux naming inventory. | `src/flock/watchdog/service.py:386` | Added `VERIFY_AFTER_SECONDS` and its default to `docs/NAMING-tmux.md:66`. |

## Stale citations fixed

All 14 near misses reported in the owned living files were corrected
individually. They were in `docs/NAMING-tmux.md` and covered the three opener
functions plus the container `host`, provider/token/publish settings, Redis
settings, watchdog flag, `door`, `start`, and `rcli`. After the edits, the
citation checker reports no hard failure and no near miss in any tmux-owned
file. Dated records were left unchanged.

## Hand-off

No proposed contract change and no suspected code defect resulted from this
lane's sweep. The repository-wide absences for `office usage`, `usage.requests`,
and RESP `xrange` fall outside the tmux-owned living documents and were not
duplicated here.
