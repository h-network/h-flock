# Build 69 — broadcast conservation results

> ⚠ **The figures below name no host, and the spread between our two is 130×**
> — identical scripts read **6.5/s on the 4-vCPU lab** and **853/s on h-oracle**.
> Read every `/s` here as this build's own evidence on an unrecorded host,
> **never as a capability**. `BUILD-CONVENTION` §3.0 is the rule that followed;
> [`DRIFT`](DRIFT.md) §4 is the finding.

Tested branch tip `e54b1e2` on the disposable `broadcast69` tenant. The frame
format did not change: broadcast frames retained L2 `destination: all` while
receive-side custody records named the actual participant.

## Broadcast gates

Both negative controls ran before clean broadcast traffic.

- **Duplicate:** one raw broadcast frame was enqueued twice through the real
  source egress path. All 99 expected `(stream_id, recipient)` keys were
  delivered twice. Reconciliation reported 99 duplicates and exited 2, with
  zero loss, unexpected recipients, or parse failures.
- **Loss:** one recipient was paused and its copy was deliberately removed from
  ingress. Reconciliation reported 98 delivered once and exactly one loss,
  `cons-1`, then exited 1. There were zero duplicates, unexpected recipients,
  or parse failures.

The clean mixed phase sent 20 broadcasts from `cons-0` to the other 99
participants, plus 100 unicasts. Its recipient-keyed result was exact:

```text
BROADCAST_RECONCILE expected=2080 delivered_once=2080 duplicates=0 lost=0 unexpected_recipient=0 parse_failures=0
```

This proves that N `opened` records sharing a stream ID are legitimate only
when their recipient keys differ, while a repeated `(stream_id, recipient)` is
a duplicate.

## Fan-out cost

The baseline submitted 20 unicasts. The broadcast phase submitted 20
broadcasts plus 100 mixed unicasts, producing 2,080 recipient deliveries.
Samples are `timestamp, concurrent flock.port processes, container CPU`.

| phase | samples | port median / peak | CPU median / peak | sampled duration |
|---|---:|---:|---:|---:|
| 20 unicasts | 4 | 0 / 0 | 375.01% / 621.06% | 6.45 s |
| 20×99 broadcast + 100 unicasts | 61 | 29 / 61 | 873.46% / 2347.08% | 218.59 s |

The sampler missed the short-lived unicast processes but did observe their CPU.
The broadcast multiplier is visible directly: up to 61 concurrent kicked ports
and 23.47 cores, compared with no concurrently sampled unicast ports and a
6.21-core baseline peak.

## Existing unicast phase

The original 100×100 conservation phase remained in the harness and was run
unchanged with five port kills and three switch kills. Its duplicate and loss
negative controls first produced their required exit codes 2 and 1.

```text
RECONCILE sent=10000 delivered_once=9997 duplicates=0 dead=0 stranded=1 lost_attributed=2 lost_unexplained=0
PARSE_FAILURES docker_json=0 dead_json=0 ingress_json=0 event_ts=0
INJECTION_COVERAGE seconds=54.498 fraction=0.174853
```

The categories balance exactly to 10,000. The one terminal strand is the known
single-pop baseline, not a regression. Both losses were attributed to switch
kills; there were zero duplicates and unexplained losses.

## Verification

- `python3 -m pytest -q`: **376 passed, 5 subtests passed**.
- Unchanged 100×20 `fabric-bench`: **2,000/2,000**, 246.3 seconds,
  **8.12 delivered/s**, above the 6.45/s requirement.
- Unicast custody remains byte-identical in destination semantics because its
  actual recipient equals its L2 destination; the focused round-trip tests
  remain green.

Checksummed lab-local evidence is under `/home/h-lab/tmux-build69`, with 36
files listed in `/home/h-lab/tmux-build69/evidence.sha256`. The scoped tenant
was removed with `docker compose down -v`; only operator-owned `h-cli` remained.
