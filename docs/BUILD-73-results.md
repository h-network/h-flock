# Build 73 results — v4 reserved header, TTL and hops

Worked from main at 0b01b6d. Branch: bus/build-73-v4-reserved.

## Verdict

PASS. Version 4 freezes the header at 256 bytes, allocates TTL and hop count,
and leaves 59 ignored bytes for future fields. The switch remains independent
of body size and shape.

⚠ **This build does not close the autonomous-agent reply loop at
`TODO.md:33`.** A reply is a new frame with fresh lineage and a fresh TTL. The
new fields bound repeated forwarding of the same frame and provide the L2/L3
primitive for a future router; they do not bound a conversation that creates
new frames.

## Wire contract

The header is 256 ASCII bytes: version 4 at offset 0; stream and correlation IDs
at 1 and 33; 63-byte source and destination fields at 65 and 128; three-digit
TTL at 191 (default 016); three-digit hops at 194 (starts 000); and 59 reserved
bytes at 197. The JSON body begins at 256 and retains kind, ts, l3 and payload.

Reserved bytes are ignored even when non-space. An allocated three-byte field
containing spaces is absent. HEADER_WIDTH is frozen: a future field consumes
reserved space or requires a new version.

Every switch forward decrements TTL and increments hops by fixed-offset splice.
TTL reaching zero dead-letters under the sender and issues no kick. The JSON
body is never decoded or re-encoded by the switch.

## Flat-read measurement

h-oracle, in-container perf_counter, n=200, with all six cases rotated through
every measurement position. Block-order results were rejected: measuring all
string cases before nested produced a 4.3 versus 3.3 µs split on identical
header work as CPU state changed.

| shape | payload | parse_for_switch p50/p95 µs | RPUSH p50/p95 µs | frame bytes |
|---|---:|---:|---:|---:|
| string | 16 B | 3.350/3.440 | 19.125/27.390 | 416 |
| string | 64 KiB | 3.360/3.500 | 27.690/55.810 | 65,936 |
| string | 1 MiB | 3.350/3.430 | 233.855/342.231 | 1,048,976 |
| nested | 16 B | 3.360/3.450 | 19.260/31.640 | 421 |
| nested | 64 KiB | 3.360/3.430 | 27.801/37.400 | 65,941 |
| nested | 1 MiB | 3.360/3.450 | 236.295/338.600 | 1,048,993 |

Header-read p50 spans only 3.350–3.360 µs across 16 B through 1 MiB and both
shapes. RPUSH continues to scale with bytes carried, as expected. Final CSV
sha256: 6a9fa3ca1fc9a3c5d6331e79b6a862383385c1949a2ac846c23482295293a94e.

The small string frame grew from 351 to 416 bytes: +65 bytes.

## Negative controls

- A frame injected with TTL 001 produced popped then switch dead_lettered with
  reason ttl expired at forward. Its dead copy has TTL 000 and hops 001, and no
  port kick occurred.
- A frame with all 59 reserved bytes changed from spaces to non-space values
  completed a full parse with TTL 16 and hops 0. Unknown reserved content is
  ignored rather than rejected.
- A forged-source real switch delivery produced the source stamp, TTL 15 and
  hops 1 while every byte after offset 256 remained identical.
- Searching src/flock/switch/service.py for json. returned no matches.

## Compatibility and correctness

Version 4 is a hard break. Container entrypoint still invokes purge_transport;
its transport set includes ingress, egress and dead, and it separately deletes
delivering. Durable boards and streams remain outside that purge.

- python3 -m pytest -q: 388 passed, 5 subtests passed.
- accept.sh on h-lab: PASS=26 FAIL=0; sim-blocked 19/0; exit 0; clean teardown.
- Conservation on h-lab: 10,000 sent, 9,998 delivered once, zero duplicates,
  zero dead, one terminal strand, one FIFO-attributed switch-kill loss, zero
  unexplained; read-only reconciliation exit 0 after the duplicate and loss
  negative controls both fired.

The terminal frame remained in cons-72 ingress with no successor kick. The main
harness waits up to 2,400 seconds for zero queue depth before reconciling, so it
cannot promptly classify the strand it is designed to count. RECONCILE_ONLY was
run over the unchanged queue and static log; the waiting harness was then
stopped without clearing or re-kicking the frame. This is a harness liveness
finding, not a v4 conservation failure.

Evidence sha256:

- acceptance log: 9c6948c34b7bad94e50d07bd74fa520112740f3089e36231f7983c63699809c5
- conservation ledger: d56ed522f3ac1d55a343cbd0231d5462859424c35f4999e20553a900bcb40f6b
- conservation docker log: 5f1fbb4228bc98c9be5c9e92ee2fa95c4ffebc152b3c7bd34ff0886a327ae43c
- reconciliation output: d5658846689544550fab945aa1f8b9565570dac355aa71fe879cf7a824988b96

The bus73 lab project was removed with down -v. Only h-cli remained.
