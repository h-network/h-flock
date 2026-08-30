# Watchdog: one daemon, no passive library

This note describes the current implementation of `src/flock/watchdog/`. It
follows the same daemon-vs-passive-library question `NEWDOCS/tmux-daemon-and-library.md`
asked of `flock.tmux`/`flock.tmuxhost`, but the honest answer here is
different in shape: `flock.watchdog` has a continuous loop, but it has no
passive-library half. Nothing outside this package imports from it. Every
class in it exists only to be invoked, directly or indirectly, from its own
`main()` loop.

## The daemon

The continuously running component is the `flock.watchdog` process itself —
there is no separate reconciler class the way `TmuxHost` is separate from
`flock.tmux`.

- `src/flock/watchdog/__main__.py` is the executable entry point: it imports
  `main` from `service.py` and calls it.
- `main()` in `src/flock/watchdog/service.py` owns the actual loop, and it is
  **bare procedural code, not a method on any class** — unlike
  `TmuxHost.run_forever()`, there is no `WatchdogDaemon.run_forever()`. `main()`
  reads every `WATCHDOG_*`/`ACTIVITY_POLL_SECONDS`/`PRESENCE_WORKING_SECONDS`/
  `VERIFY_AFTER_SECONDS` env var, builds one `Watchdog` instance and three
  observer instances (`ActivityTailer`, `PresenceSampler`, `DeliveryVerifier`),
  then runs `while True:` with three independently gated cadences compared
  against `time.monotonic()`:
  - every `ACTIVITY_POLL_SECONDS` (default `2`): calls `run_observers()`,
    unconditionally — this cadence ignores `WATCHDOG_ENABLED`.
  - every `WATCHDOG_INTERVAL` (default `30`), only if `alerting` (i.e.
    `WATCHDOG_ENABLED != "0"`): calls `watchdog.poll()`.
  - every `3600` seconds, only if `alerting`: calls `watchdog.check_credentials()`.
  - sleeps `min(interval, observe_seconds)` at the end of each iteration.

  `alerting` is computed once, before the loop starts, from `WATCHDOG_ENABLED`;
  it is not re-read per iteration.
- `run_observers(watchdog, jobs, agents)` is a plain module-level function, not
  a method, called once per `ACTIVITY_POLL_SECONDS` tick. It loops over the
  three `(name, job)` pairs `main()` built, calls `job.poll(agents)` on each
  under its own `try/except`, and reports any failure through
  `watchdog._error(name, exc)` — a private method of a class it does not
  otherwise touch, used here purely as the shared error-logging sink. It
  returns the list of job names that raised; its only caller (`main()`)
  discards that return value, and no test calls `run_observers()` directly
  either.

Four classes do the actual checking. None of them owns a loop — each has a
`poll()` (or `check_credentials()`) method that performs exactly one pass and
returns, and each is fully usable (and is used, in `tests/test_watchdog.py`,
`tests/test_activity.py`, `tests/test_presence.py`,
`tests/test_verification.py`) by calling that method directly with no `main()`
loop running at all:

- `Watchdog` (`service.py`) — constructed once by `main()`, holds the Redis
  handle, every threshold/window config value, and one piece of in-process
  state (`_reported_blocks`, an in-memory dedup set for the `blocked` alert
  stream record). `poll(now=None)` runs the `WATCHDOG_INTERVAL`-cadence checks
  in sequence (`_check_stalls`, `_check_blocked`, `_check_doing_duration`,
  `_check_todo_duration`, `_check_hold_duration`, `_check_unreplied_duration`,
  `_check_ack_loop`), each under its own `try/except` inside `poll()` itself.
  `check_credentials(now=None)` is the separate hourly sweep.
- `ActivityTailer` (`activity.py`) — `poll(agents=None)` makes one
  non-blocking pass over every agent's newest CLI session file, appends
  activity events, and emits `usage` records.
- `PresenceSampler` (`presence.py`) — `poll(agents, now=None)` writes one
  current `state`/`since`/`last_activity` per agent from the activity stream
  `ActivityTailer` already wrote.
- `DeliveryVerifier` (`verification.py`) — `poll(agents, now=None)` judges any
  `pending.verify` marker older than `VERIFY_AFTER_SECONDS`, writing or
  clearing the `blocked` hash.

## There is no passive-mechanism library here

`flock.tmux` is imported directly by `tmuxhost`, `port`/delivery code, and
tests — it is genuine shared library code. `flock.watchdog` has no equivalent:

```
grep -rn "from flock.watchdog\|flock\.watchdog\." src --include="*.py" | grep -v "^src/flock/watchdog/"
```

returns nothing. `src/flock/watchdog/__init__.py` exports only `Watchdog`, and
nothing outside this package imports even that. `office/cli.py` and
`tmux/openers.py` mention `PresenceSampler`/`ActivityTailer` only in comments,
citing the Redis keys those classes write (`presence`, `activity`, `blocked`,
`activity.offset`) — the coupling to the rest of the system is entirely
**through Redis state and terminal pastes** (`_notify_lead`'s direct write to
the lead's `ingress` plus a `flock.port` kick), never through a Python call
into this package. That absence is the module's actual "library boundary": it
has none, by design (`LLD-watchdog.md` §1 — "the watchdog imports shared bus
and tmux library functions, but it neither receives nor sends envelopes").

So the daemon/library split this note was asked to describe does not apply in
the tmux sense. The real internal split is between the one file with no loop
of its own (`main()`, `run_observers()` — the scheduler) and four files, each
holding one class whose methods perform a single pass and return, invoked by
that scheduler.

## Map of the real structure

```
src/flock/watchdog/
  __main__.py     entry point -> service.main()
  __init__.py     exports Watchdog only
  service.py      main() + run_observers() [the scheduler, no class]
                  Watchdog                 [ordinary-cadence checks + credentials]
                    _agents, _window_activity, _alert, _error, _ticket, _presence,
                    _blocked, _check_blocked, _check_stalls, _lead, _notify_lead,
                    _check_doing_duration, _check_todo_duration,
                    _check_hold_duration, _check_unreplied_duration,
                    _ack_edge, _check_ack_loop, poll,
                    _credential_accounts, check_credentials
  activity.py     ActivityTailer            [CLI session tailer + usage emitter]
                    per-CLI parsers: _claude_events/_claude_usage,
                    _codex_events/_codex_usage, _agy_events
                    _EMIT_USAGE_LUA (dedup + attribution, atomic)
  presence.py     PresenceSampler           [state machine over activity recency]
  verification.py DeliveryVerifier          [pending.verify -> blocked/verified]
                    VERIFICATION_ACTIVITY_KINDS = {input, output, tool}
```

Every file except `service.py` holds exactly one class and its private
helpers; `service.py` holds the scheduler *and* the largest checker class,
which is the main asymmetry in the layout (see below).

Cross-package dependencies actually used by this module: `flock.bus` (roster
reads, envelope build/encode, `admit_ingress`, `log_record`/`mirror`) and
`flock.tmux.run_tmux` (the one `list-windows` call `_window_activity` makes).
Nothing in `flock.port` or `flock.control` is imported here.

## Things that don't fit cleanly

- **The scheduler has no class, so its policy is not independently testable
  the way `TmuxHost.reconcile_once()` is.** The three-cadence logic (2s
  unconditional, 30s gated by `alerting`, 3600s gated by `alerting`) lives as
  loose code inside `main()`. The only tests that exercise it at all
  (`test_disabled_alerting_still_connects_because_observers_need_redis`,
  `test_alerting_disabled_still_runs_the_observers`,
  `test_observation_failure_does_not_disable_due_credential_check`) do so by
  monkeypatching `time.monotonic`/`time.sleep`/`redis.Redis.from_url` (and, in
  two of the three, the `Watchdog`/observer classes themselves) to force
  exactly one iteration before raising `StopIteration` — there is no
  `WatchdogScheduler` object whose cadence rules can be asserted on directly.
- **`Watchdog` is one class doing three largely independent jobs.** Reading
  `docs/LLD-watchdog.md`, the class covers: the three-signal stall rule and
  the `blocked` alert (§2, §3); five lead-notification rules that share one
  delivery mechanism and one crossing-count dedup shape but otherwise watch
  unrelated state (§2a-e: `doing`, `todo`, `hold`, `unreplied`, `acks`); and
  the hourly credential sweep (§5). These three groups share no state with
  each other except the Redis connection and the `_alert`/`_error` helpers —
  they are one class because `main()` calls them from the same object, not
  because they are one responsibility.
- **`_check_blocked` (in `Watchdog`) reads a key that a different class in a
  different file (`DeliveryVerifier`) writes.** The two are connected only by
  both being polled from the same `main()` loop and touching the same Redis
  hash (`<prefix>:agent:<name>:blocked`) — there is no import or call between
  `service.py` and `verification.py`. `docs/LLD-watchdog.md` §7 invariant 4
  already documents *who owns* the key; it does not document that the reader
  and the writer are two unrelated classes with no reference to each other.
- **`WATCHDOG_ENABLED` disables two of the daemon's three cadences, not all
  three**, and the flag name does not say which. `_check_blocked`/`poll()`/
  `check_credentials()` all stop; `ActivityTailer`/`PresenceSampler`/
  `DeliveryVerifier` do not (`docs/LLD-watchdog.md` §6, fixed in this office's
  last watchdog-doc pass). Structurally this means "the watchdog" is really
  two co-processes sharing one Python process, one Redis connection, and one
  boolean that only controls one of them.
- **`run_observers()` takes a whole `Watchdog` instance just to call one
  private method on it (`_error`).** It has no other relationship to
  `Watchdog` — it operates on the three observer objects, not on the checker
  class. The dependency exists only because error logging happened to be
  written as a `Watchdog` method first.
- **All four classes name their one-pass method `poll()`** (`Watchdog.poll(now=None)`,
  `ActivityTailer.poll(agents=None)`, `PresenceSampler.poll(agents, now=None)`,
  `DeliveryVerifier.poll(agents, now=None)`), which reads as a shared interface
  but is not one: the required arguments differ across all four, and
  `Watchdog.poll()` fetches its own agent list internally while the other
  three require the caller to pass it in. `main()` and `run_observers()`
  therefore call the "same-named" method two different ways in the same
  function.

## A cleaner split and vocabulary

With freedom to change module boundaries and names, matching the shape
`NEWDOCS/tmux-daemon-and-library.md` proposed for tmux:

- `flock.watchdog_daemon.main`: entry point, replacing today's `__main__.py`
  with a name that says what runs, not just that something does.
- `flock.watchdog_daemon.scheduler.WatchdogScheduler`: a real object owning
  `run_forever()` and the three-cadence policy (`should_observe`,
  `should_alert`, `should_check_credentials` as separately testable methods,
  each taking `now`), so the scheduling rule stops being unverifiable loop
  code and becomes unit-testable the way `TmuxHost.reconcile_once()` already
  is. `run_observers()` becomes a method of this class, or of a small
  `ObserverGroup` it owns, and stops borrowing `Watchdog._error` as a generic
  sink — it gets its own error-reporting call, shared via composition rather
  than an unrelated object's private method.
- Split today's single `Watchdog` class by the three responsibilities it
  currently bundles:
  - `flock.watchdog.stalls.StallChecker`: `_check_stalls`, `_check_blocked`,
    `_ticket`, `_presence`, `_blocked`, `_window_activity` — the three-signal
    rule and the `blocked` read-side (§2, §3).
  - `flock.watchdog.lead_alerts.LeadAlerter`: `_notify_lead`,
    `_check_doing_duration`, `_check_todo_duration`, `_check_hold_duration`,
    `_check_unreplied_duration`, `_check_ack_loop`, `_ack_edge`, `_lead` — the
    five §2a-e rules, which already share one delivery mechanism and belong
    together, separated from the other two groups.
  - `flock.watchdog.credentials.CredentialChecker`: `_credential_accounts`,
    `check_credentials` (§5), independent of both of the above and on its own
    hourly cadence already.
  - A small shared `flock.watchdog.alerts` module for `_alert`/`_error` and the
    `_text`/`_timestamp`/`_iso`/`_fields` helpers duplicated near-identically
    across `service.py`, `activity.py`, `presence.py`, and `verification.py`
    today (each file currently defines its own copy of `_text`/`_timestamp`).
  - `WatchdogScheduler` would then hold one `StallChecker`, one `LeadAlerter`,
    one `CredentialChecker`, and the three observers, and call each directly —
    removing the need for a single `Watchdog` facade class at all.
- Rename the four `poll()` methods to name the actual one-pass action, so the
  same word stops meaning four different signatures:
  `ActivityTailer.tail_once(agents=None)`, `PresenceSampler.sample_once(agents, now=None)`,
  `DeliveryVerifier.judge_once(agents, now=None)`,
  `StallChecker.check_once(now=None)`, `LeadAlerter.check_once(now=None)`.
- Rename `blocked` awareness explicitly at the boundary: `StallChecker._blocked()`
  reads a hash `DeliveryVerifier` writes with no shared code between them
  today; a `BlockedVerdictStore` (read/write pair, used by both) would make
  that cross-class dependency an explicit collaborator instead of an implicit
  Redis-key agreement documented only in prose.
- `WATCHDOG_ENABLED` would become two flags if the behavior stays split —
  `WATCHDOG_ALERTING_ENABLED` (gates `StallChecker`/`LeadAlerter`/
  `CredentialChecker`) — rather than one name that silently means "alerting
  only." (An env-var rename is a behavior/config change, not a doc or file
  split, so I would raise this rather than fold it into a rename-only pass.)

The daemon/library question this note was asked to answer therefore has a
one-sentence answer for `flock.watchdog`: everything here is daemon-owned,
nothing here is a library, and the split worth making is not
daemon-vs-library but scheduler-vs-checkers — currently blurred because the
scheduler has no class and one checker class does three jobs.
