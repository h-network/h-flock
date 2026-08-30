# Notes — bus/switch file ownership and core-scoping

> **Status: a working note, not a spec.** Written 2026-08-30 in response to an
> operator question ("which files do you actually touch/own?") while scoping
> a from-scratch rebuild (`h-mesh`). It records a snapshot answer, not a
> contract — if the file lists below drift from the repo, trust the repo.
> The spec for what these modules *do* is [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md);
> this note is only about which files that spec's owner touches, and which of
> them are load-bearing for a minimal rebuild.

Per [`LLD-lanes.md`](LLD-lanes.md)'s own ownership table: `bus | switch +
bus.doors.send/tracking | flock.bus, flock.switch`.

## Source — `src/flock/bus/` (12 files)

| file | what it holds |
|---|---|
| `__init__.py` | lazy facade — the only stable import surface (`flock.bus.X`) |
| `envelope.py` | v4 wire frame: `build`/`parse`/`encode`, header splicing (`stamp_source`, `advance_hop`), address resolution |
| `keys.py` | `prefix()` — the sole Redis key constructor, segment validation |
| `doors.py` | `send()`/`receive()`, unreplied + ack-loop tracking, `DeadLetter` |
| `queues.py` | `admit_ingress()` — shared atomic ingress-admission Lua op |
| `roster.py` | read-only roster access (`members`/`is_member`/`port_type`) |
| `policy.py` | import/export tag ACL (`allows`/`require_allowed`) |
| `resources.py` | Redis-key classification + `purge_agent`/`purge_transport` |
| `logging.py` | `log_record`/`emit`/`mirror`/`record_task_event` — the JSONL contract |
| `resp.py` | hand-rolled minimal RESP2 client (24 commands) for one-shot CLIs |
| `connection.py` | `local_redis_url()` — URL construction, shared with container boot |
| `accounts.py` | `available_profiles()` — configured-account discovery |

## Source — `src/flock/switch/` (5 files)

| file | what it holds |
|---|---|
| `service.py` | the `Switch` class — BLPOP/forward/kick loop, is what "the switch" is |
| `retention.py` | count-based trim of `tasks.done`/`dead` in the switch's maintenance pass |
| `windowlog.py` | tails `window.log.jsonl` into container stdout, in the same pass |
| `__main__.py` | entrypoint: `python3 -m flock.switch` → `service.main()` |
| `__init__.py` | empty, module docstring only |

## Tests

`LLD-lanes.md` names `test_bus.py` explicitly as the bus lane's test file;
`testbed` owns the shared harness/fixtures (`tests/conftest.py`) rather than
any lane's own tests. The following are also bus/switch-owned by content,
even though the lane table doesn't enumerate them individually:

- `test_bus.py` — the big one: doors/envelope/keys/policy/roster/switch
  integration via `FakeRedis`, plus `Switch.step()` behavior
- `test_resp.py` — `bus.resp.Redis` (RESP2 client) and its 24-command surface
- `test_resources.py` — `purge_agent`/`purge_transport`, resource classification
- `test_retention.py` — `switch.retention.RetentionTrimmer`
- `test_window_logging.py` — `switch.windowlog.WindowLogTailer`
- `test_ingress_admission.py` — `bus.queues.admit_ingress` against real Redis
- `test_import_boundaries.py` — the module-independence guarantee (importing
  `flock.switch.service` must not import `flock.bus.doors`)

## Docs

- [`LLD-bus-and-switch.md`](LLD-bus-and-switch.md) — the spec
- [`NAMING-bus.md`](NAMING-bus.md) — frozen naming inventory, pinned to a sha (not living)

## Core-scoping for a from-scratch rebuild

Everything else in the repo (tmux/tmuxhost, port delivery, api, session,
watchdog, office, control, openshell, the container entrypoint chain) imports
`flock.bus` as a dependency but is owned by other lanes. The bus/switch split
itself is the L1/L2 line from `LLD-bus-and-switch.md`'s own diagram: bus is a
pure library (no daemon, no loop) that anything can import; switch is the one
daemon built on top of it that actually forwards.

If "core" means *the minimum a message needs to move between two participants
with no opinion about what they are*, that's the 17 files above:

- `envelope.py` + `keys.py` + `queues.py` + `roster.py` + `policy.py` +
  `doors.py` give the wire format, addressing, and the two queue-door
  primitives.
- `switch/service.py` is the only thing that has to run as a process.
- `logging.py`, `resources.py`, `resp.py`, `connection.py`, `accounts.py` are
  supporting infrastructure — observability, retirement, a transport client,
  URL building, account listing — that a minimal rebuild could defer or fold
  in, not core forwarding logic.
- `switch/retention.py` and `switch/windowlog.py` are maintenance passes
  riding along in the switch's own loop (§3.4 of the LLD), not forwarding
  itself; a minimal rebuild could run them elsewhere or omit them initially.
