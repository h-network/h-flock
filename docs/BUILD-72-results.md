# Build 72 results — fixed-width L2 header

Worked from main at 0164c98 after the section 5.2 gate was corrected. Branch:
bus/build-72-fixed-header.

## Verdict

PASS. Version 3 is a hard wire break. The switch reads and validates only the
191-byte ASCII header. It neither decodes nor validates the JSON body. The
normal header-read cost is flat across payload sizes and shapes; Redis RPUSH
continues to scale with bytes carried, as expected.

## Pre-change evidence

All rows are fresh h-oracle tenants, 2,000/2,000 complete paths, zero dead
letters and zero parse failures.

| payload | popped to forwarded p50/p95 | steady-state | log sha256 |
|---:|---:|---:|---|
| 16 B | 0/1 ms | 848.52/s | 51c564785d81ef2683d1351a4770d799499f86980fc05eff92b11c2b91a57946 |
| 4 KiB | 0/1 ms | 838.22/s | e3c86acaf08a884d2bffec5cc8a8b9ba2770d5231ed6e2702b1ff4d6aa7a1ecf |
| 64 KiB | 0/1 ms | 775.68/s | bccf8064e3351fc563a94fca5a4540f552b67c4ea6345faa4926bcf26675c766 |
| 1 MiB | 1/2 ms | 289.67/s | aa1caaf006f8eea872a169d5a900f41cd7ba685e62dafc4817fb836cbaa65b8e |

The perf-counter decomposition, n=200, established that json.loads was 89% of
loads plus RPUSH for a 64 KiB nested payload and 94% at 1 MiB nested. The first
decomposition invocation omitted docker exec -i and produced zero samples; it
was rejected rather than treated as a measurement.

## Fixed-header decomposition

h-oracle, in-container perf_counter, n=200. The switch-read column is
parse_for_switch alone. The ceiling is 1,000,000 divided by read plus RPUSH p50;
it is context, not the pass condition.

| shape | size | switch read p50/p95 µs | RPUSH p50/p95 µs | ceiling/s |
|---|---:|---:|---:|---:|
| string | 16 B | 3.08/3.13 | 12.30/14.27 | 65,019 |
| string | 64 KiB | 3.13/3.20 | 25.93/33.83 | 34,412 |
| string | 1 MiB | 3.05/3.12 | 237.60/329.79 | 4,156 |
| nested | 16 B | 3.01/3.10 | 12.11/12.65 | 66,133 |
| nested | 64 KiB | 3.01/3.11 | 25.05/27.15 | 35,638 |
| nested | 1 MiB | 3.15/3.23 | 236.77/263.84 | 4,168 |

The switch-read medians span 3.01–3.15 µs: 0.14 µs absolute and 4.7% relative
from the minimum, with no payload-size or shape slope. The RPUSH slope remains.
CSV sha256: 71694f3a5c02813d47c99d1da8522f5795ed7be6a1bcab7e5c34c4b22db0087c.

Source stamping is not a normal-path cost. It is a fixed-offset splice only,
performs no JSON operation, and the unit gate compares every body byte before
and after the correction.

## Post-change system sweep

Every row used a fresh h-oracle tenant and completed 2,000/2,000 paths with
zero dead letters and zero parse failures.

| payload | popped to forwarded p50/p95 | steady-state | change from pre | log sha256 |
|---:|---:|---:|---:|---|
| 16 B | 0/1 ms | 853.87/s | +0.63% | 5c44cd9f25a1f8bed9ad886e143d216f8dd85d1017ccd4da7f36ef20ac991bd3 |
| 4 KiB | 0/1 ms | 832.12/s | -0.73% | 91504cef31b5fc4cecc6ae7cbcce451a07c791aa0ce919ee604b13696959a058 |
| 64 KiB | 0/1 ms | 773.06/s | -0.34% | 490e382e51257d9a60c0bb277393330946a12f94f1b082a3daef81800295e6cc |
| 1 MiB | 1/1 ms | 409.99/s | +41.54% | 513f90bda57a9d24d102930089a3365d84b95b900300ce2b6a37d9c6ec64f324 |

Small-payload end-to-end throughput did not move. The 1 MiB increase is the old
payload parse disappearing after it had become a bottleneck; it is not the gate.
Two earlier post-change runs were rejected because a detached orchestration
loop overlapped them and analyse-run correctly reported 4,000 paths against an
expectation of 2,000.

For the 16-byte string decomposition fixture the wire grew from 315 to 351
bytes: +36 bytes, not the approximately 60-byte estimate in the spec.

## Boundaries and negative controls

There are no json references in src/flock/switch/service.py. Byte input decodes
only raw[:191] as ASCII. A non-UTF-8 corrupt body therefore crosses the switch
and fails only when the port parses the complete frame.

A bad header produced popped then switch dead_lettered, no kick. A valid header
with a corrupt body produced popped, forwarded, kick_started, then port
dead_lettered. The port record retains the header stream_id and actual recipient,
so analyse-run can join sent, popped and forwarded to the terminal dead letter;
received and opened are correctly absent. A malformed header has no trustworthy
join key and remains unknown.

Transport purge remains a hard-v3 migration boundary: entrypoint invokes
purge_transport, whose resource set includes ingress, egress and dead and which
also deletes delivering. Durable boards and streams are outside that set.

## Correctness

- python3 -m pytest -q: 386 passed, 5 subtests passed.
- accept.sh on h-lab: PASS=26 FAIL=0; sim-blocked 19/0; exit 0; clean teardown.
- Conservation on h-lab: 10,000 sent, 9,998 delivered once, zero duplicates,
  zero dead, zero strands, two switch-kill-attributed losses, zero unexplained;
  reconciliation exit 0 after both duplicate and loss negative controls fired.
- Conservation ledger sha256:
  aca97f9006308531d2cbb35094fcb0e8788a24d7fca89fec2a4b5af4e0bb91f3.
- Conservation docker log sha256:
  6be99813c31eb37d002b5e6abf147c1a2763e57ec3b40561648177cd2ce263c6.

The lab project was removed with down -v. Only h-cli remained.
