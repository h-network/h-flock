# Verification round — bus lane

Read at `c405bf6662952906eeb1ef0b474001a8747c713c`, the main tip supplied when
this lane started. Code led every verdict. Dated `BUILD-*` and `VERIFIED-*`
records were not edited.

## Fixed contradictions

1. `CONTRACTS` §3 opened with six successful-unicast records but later called
   the same path five, omitted `kick_started` from its event block, and described
   broadcast as a receive-side pair per recipient. The switch emits
   `kick_started` after each successful spawn (`src/flock/switch/service.py:82-102`),
   including each accepted broadcast recipient (`src/flock/switch/service.py:155-172`).
   `CONTRACTS.md:229-233,274-325` now consistently describes six unicast records,
   seven possible envelope events including the terminal alternative, and the
   broadcast's per-recipient `kick_started`/`received`/`opened` trio.

2. `LLD-bus-and-switch` assigned activity tailing, presence sampling, and
   delivery verification to the switch and stated a ten-second verification
   default. The running constructors are in the watchdog and use 120 seconds
   (`src/flock/watchdog/service.py:373-392`); the switch retains only window-log
   tailing and retention (`src/flock/switch/service.py:192-224,250-265`).
   `LLD-bus-and-switch.md:320-336,384-526` now separates the watchdog observation
   pass from switch housekeeping and names both cadences and owners.

3. The LLD said verification looked only for later input. The verifier admits
   the configured activity kinds and tests any timestamp later than the marker
   (`src/flock/watchdog/verification.py:60-70,111-142`).
   `LLD-bus-and-switch.md:476-505` now says later CLI activity.

## Fixed absences

1. The living record contract had no `writer`. `log_record` reads the process
   override once and emits `writer` as that value or `module`
   (`src/flock/bus/logging.py:8,74-81`). `CONTRACTS.md:257-269` now makes the
   label required and explicitly says it is provenance, not a credential;
   `NAMING-bus.md` inventories `writer` and `FLOCK_WRITER`.

2. No living document described the durable custody mirror.
   `mirror()` appends the already formatted stdout record and never raises
   (`src/flock/bus/logging.py:27-51`); compose mounts the named custody volume
   (`container/compose.yaml:105-123`). `CONTRACTS.md:242-255` and
   `LLD-bus-and-switch.md` §3.4 now describe `FLOCK_CUSTODY_FILE`, its byte-copy
   rule, survival under ordinary container removal, and deletion with explicit
   volume removal. `NAMING-bus.md` inventories the function and environment
   variable.

3. `delivery.markers`, `usage.requests`, `usage.attributed`, and tenant `usage`
   existed only in code. Their classification is settled in
   `src/flock/bus/resources.py:6-48`; marker production is at
   `src/flock/port/openers.py:44-71`, and usage correlation/deduplication/storage
   is at `src/flock/watchdog/activity.py:294-452`. The LLD queue/resource table
   and observation pass now document all four, CONTRACTS §3 documents the usage
   record, and `NAMING-bus.md` inventories each key.

4. The minimal RESP client's `xrange` implementation had no living-doc entry.
   `NAMING-bus.md` now inventories the method at `src/flock/bus/resp.py:93-113`.

## Stale citations

The citation checker reported no near misses in the three bus-owned living
documents before this edit. After the individual additions and corrections it
still reports no hard failure or near miss in those files. Dated records were
left unchanged.

## Handed to architect — outside this lane's sections

These are unambiguous contradictions in architect-owned parts of `CONTRACTS`;
this branch does not edit them:

- `CONTRACTS.md:693-695` says `blocked` is written by the switch, not the
  watchdog. `DeliveryVerifier.poll` writes and deletes it at
  `src/flock/watchdog/verification.py:78-142`, and the verifier is constructed
  by `src/flock/watchdog/service.py:373-387`.
- `CONTRACTS.md:735-737` says `pending.verify` is judged and dropped by the
  switch. The same verifier code performs `XRANGE` and `XDEL` from the watchdog.
- `CONTRACTS.md:798-800` says the switch tails activity, gives
  `VERIFY_AFTER_SECONDS` default 10, and says `WATCHDOG_ENABLED=0` exits the
  process. Code assigns activity to the watchdog, defaults verification to 120,
  and keeps observers running while only alerting is disabled
  (`src/flock/watchdog/service.py:373-407`).
- The operator-facing `office usage [--agent] [--since] [--json]` syntax remains
  undocumented. This branch documents the underlying tenant usage Stream in
  the bus LLD, but command syntax belongs with the architect-owned office
  command contract rather than a bus transport section
  (`src/flock/office/cli.py:604-660,766-767`).

## Code-side finding — not changed

`src/flock/bus/logging.py:70-72` still says a synthetic lifecycle stream ID
makes the four records of an envelope harder to find. The implemented and now
documented successful-unicast set has six. This is a stale code docstring, not a
runtime defect; the round forbids code edits, so it is reported rather than
fixed here.

No runtime code defect was found.
