# Build 65 — the log cannot identify a strand

## Result

No. The checksummed build 58 attempt-4 Docker log cannot identify either
terminal strand. Sequence 9956 (`50a8ff8ddaa14da49ae32155171f7d85`) has only
`popped` and `forwarded`; sequence 9990
(`77e6f275c75c401392faee0e7b38d94d`) has the same two records. Each trace is
also consistent with an in-flight port or a log read before its successor.
`stranded-ingress.jsonl`, not `docker.log`, is what establishes that both frames
remained queued.

The earlier sequence 9935 claim was from a different attempt. In attempt 4 it
is `26a69117fd454b84acf3cd4165cba8f5`, and the log has all four of `popped`,
`forwarded`, `received`, and `opened`. All files named by the bundle's
`SHA256SUMS` passed verification before this audit.

## Transition audit

“Watchdog” means the transition cannot be settled by the component performing
it. The existing watchdog is the observer boundary; extending it would mean
reading aged custody records and ingress depth or frame headers, then alerting.
It must not pop, kick, or otherwise retry delivery.

| Transition | Record and evidence | Classification |
|---|---|---|
| address or policy refuses a send | `send_refused`, before assembly (`src/flock/bus/doors.py:28-52`) | already visible |
| frame assembly succeeds | none; it is internal work and has not entered custody (`src/flock/bus/doors.py:41-43`) | deliberately silent |
| egress write fails | `send_failed`, with the assembled frame's identity (`src/flock/bus/doors.py:53-60`) | cheap to emit — added |
| frame is written to egress | `sent`, emitted after `rpush` (`src/flock/bus/doors.py:53-62`) | visible, except the write→record crash gap |
| sender dies after the write and before `sent` | no record; egress remains non-empty | watchdog's job |
| switch pops a valid frame | `popped` (`src/flock/switch/service.py:68-92`) | visible, except the pop→record crash gap |
| switch dies after pop and before `popped` | no record and the frame is no longer queued | watchdog's job |
| switch pops a malformed frame | `popped` plus `dead_lettered` with unknown identity (`src/flock/switch/service.py:75-82`) | visible as a failure, not joinable to a malformed identity |
| switch corrects source attribution | `source_stamped` (`src/flock/switch/service.py:85-99`) | visible |
| destination is absent from the roster | `dead_lettered` under the sender (`src/flock/switch/service.py:115-118`) | visible |
| ingress write fails | `forward_failed`, with the popped frame's identity (`src/flock/switch/service.py:119-123`) | cheap to emit — added |
| frame is written to one ingress | `forwarded`, emitted after `rpush` (`src/flock/switch/service.py:119-125`) | visible, except the write→record crash gap |
| switch dies after an ingress write and before `forwarded` | last record is `popped`, while the frame is queued | watchdog's job |
| broadcast fan-out commits | one `forwarded` with `count` after the pipeline (`src/flock/switch/service.py:101-113`) | visible; per-recipient ingress identity is not recorded |
| switch cannot spawn the destination port | `kick_failed`, correlated to the frame (`src/flock/switch/service.py:31-45`) | cheap to emit — corrected from unjoinable `error` |
| switch spawns the destination port | `kick_started`, naming the real recipient (`src/flock/switch/service.py:46-55`) | cheap to emit — added |
| kicked port observes a pause | no pop and no record; the frame deliberately stays queued (`src/flock/port/deliver.py:84-86`) | deliberately silent |
| kicked port finds an empty ingress | no record (`src/flock/bus/doors.py:76-83`) | deliberately silent; a sibling may already have popped it |
| kicked port dies before popping | no successor after `kick_started`; frame stays in ingress | watchdog's job |
| port pops a frame | `received`, after parse (`src/flock/bus/doors.py:76-90`) | visible, except the pop→record crash gap |
| port dies after pop and before `received` | no successor and no queued frame | watchdog's job; exact attribution needs aged kick/custody state |
| opener is unknown or raises | frame is written to dead and `dead_lettered` (`src/flock/bus/doors.py:91-105`) | visible, except the dead-write→record crash gap |
| switch or port dies after a dead write and before `dead_lettered` | frame exists only in a dead queue, with no terminal log record | watchdog's job |
| opener completes | `opened` (`src/flock/bus/doors.py:96-106`) | visible |
| ticket opener writes the board | `board_write_confirmed`; failures are `board_write_failed` (`src/flock/port/openers.py:162-193`) | visible outside the five custody records |
| tmux verification becomes eligible | marker exists only after the opener starts (`src/flock/port/openers.py:18-50`) | cannot observe a pre-pop strand |
| verifier judges a marker | `delivery_unjudged` or `delivery_unverified`; a verified marker is deleted silently (`src/flock/switch/verification.py:73-125`) | deliberately silent on success |

Counts for silent transitions in this table: four cheap records implemented,
six watchdog observations not implemented, and four deliberately silent
transitions. The crash gaps are real: a JSON line written after a queue mutation
cannot be atomic with that Redis operation. Closing them requires the watchdog
to compare aged records with queue state, or a future durable custody ledger;
putting polling or retries in the switch would violate the component boundary.

## Negative controls

The unit gates force each newly recorded branch. An egress exception produces
only `send_failed`, never `sent`. An ingress exception produces `popped` then
`forward_failed`, never `forwarded` or a kick. A successful spawn produces
`kick_started`; a failed spawn produces `kick_failed` and never
`kick_started`. These assertions distinguish a record that genuinely follows
its transition from one emitted unconditionally.
